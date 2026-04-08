from datetime import datetime, timedelta
from decimal import Decimal

from app.auth import hash_password
from app.models import (
    Delivery,
    DeliveryStatusEnum,
    Depot,
    IntegrationOutbox,
    PricingRule,
    Program,
    ProgramLine,
    RoleEnum,
    Truck,
    User,
)
from app.services.pricing_service import calculate_delivery_amount


def _create_user(db, *, username: str, role: RoleEnum, password: str = "secret123") -> User:
    user = User(
        email=f"{username}@example.com",
        username=username,
        full_name=username.replace("-", " ").title(),
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login_token(client, *, username: str, password: str = "secret123") -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _seed_program_context(db, *, suffix: str) -> tuple[User, Depot, Truck]:
    driver = _create_user(db, username=f"driver-{suffix}", role=RoleEnum.RAVITAILLEUR)
    depot = Depot(
        name=f"Depot-{suffix}",
        manager_id=None,
        latitude=12.3714,
        longitude=-1.5197,
        stock_6kg_plein=80,
        stock_12kg_plein=60,
        stock_6kg_vide=10,
        stock_12kg_vide=8,
        capacity_6kg=120,
        capacity_12kg=120,
        address="Ouagadougou secteur 1",
        city="Ouagadougou",
        phone="70000000",
    )
    db.add(depot)
    db.commit()
    db.refresh(depot)

    truck = Truck(
        license_plate=f"TRK-{suffix}",
        driver_id=driver.id,
        capacity_6kg=120,
        capacity_12kg=100,
        current_load_6kg_plein=40,
        current_load_12kg_plein=30,
        current_load_6kg_vide=3,
        current_load_12kg_vide=2,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)

    return driver, depot, truck


def _program_payload(*, program_code: str, depot_id: int, truck_id: int, driver_id: int, sync_version: int, lines: list[dict]) -> dict:
    return {
        "program_code": program_code,
        "program_type": "DELIVERY",
        "site": "SOD-BF-01",
        "date": "2026-04-08",
        "time": "08:30",
        "depot_id": depot_id,
        "truck_id": truck_id,
        "driver_id": driver_id,
        "transporter": "SODIGAZ Logistics",
        "status": "active",
        "source_updated_at": "2026-04-08T07:30:00Z",
        "sync_version": sync_version,
        "lines": lines,
    }


def test_sage_program_upsert_is_idempotent_and_projects_deliveries(client, db):
    driver, depot, truck = _seed_program_context(db, suffix="program-idempotent")
    db.add(
        PricingRule(
            product_code="GAZ_12KG",
            product_label="Gaz 12 kg",
            depot_id=depot.id,
            unit_price=Decimal("6500.00"),
            tax_rate=Decimal("0.1800"),
            active=True,
        )
    )
    db.commit()

    payload = _program_payload(
        program_code="PRG-IDEMP-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-L1",
                "client_code": "CLI-01",
                "client_name": "Client A",
                "destination_address": "Secteur 10",
                "product_code": "GAZ_12KG",
                "product_label": "Gaz 12 kg",
                "quantity_planned": 12,
            },
            {
                "line_code": "L2",
                "external_line_id": "EXT-L2",
                "client_code": "CLI-02",
                "client_name": "Client B",
                "destination_address": "Secteur 11",
                "product_code": "GAZ_6KG",
                "product_label": "Gaz 6 kg",
                "quantity_planned": 20,
                "unit_price": "3000.00",
                "tax_rate": "0.10",
            },
        ],
    )

    first_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )
    second_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["replayed"] is False
    assert second_response.json()["replayed"] is True

    program = db.query(Program).filter(Program.program_code == "PRG-IDEMP-001").one()
    assert program.program_type.value == "DELIVERY"
    assert program.site_code == "SOD-BF-01"
    assert program.program_time == "08:30"
    assert len(program.lines) == 2

    projected_deliveries = db.query(Delivery).filter(Delivery.program_id == program.id).all()
    assert len(projected_deliveries) == 2

    twelve_kg_line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-L1").one()
    assert twelve_kg_line.unit_price == Decimal("6500.00")
    assert twelve_kg_line.tax_rate == Decimal("0.1800")

    inbound_events = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == "sage_program:PRG-IDEMP-001:v1"
    ).all()
    assert len(inbound_events) == 1


def test_collection_program_upsert_and_confirmation_creates_collection_event(client, db):
    driver, depot, truck = _seed_program_context(db, suffix="collection-program")

    payload = _program_payload(
        program_code="PRG-COL-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "external_line_id": "EXT-COL-1",
                "client_id": "CLI-COL-01",
                "client_name": "Client Collecte",
                "product_code": "GAZ_12KG",
                "article": "BOUT12",
                "zone": "Zone Nord",
                "quantity_planned": 6,
                "delivery_mode": "PCOL",
                "collection_sheet": "FICHE-01",
                "comment": "Retour bouteilles vides",
            }
        ],
    )
    payload["program_type"] = "COLLECTION"

    create_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )
    assert create_response.status_code == 200

    program = db.query(Program).filter(Program.program_code == "PRG-COL-001").one()
    line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-COL-1").one()
    delivery = db.query(Delivery).filter(Delivery.program_id == program.id).one()

    assert program.program_type.value == "COLLECTION"
    assert line.quantity_collected == 0
    assert delivery.program_type == "COLLECTION"
    assert delivery.total_amount is None

    token = _login_token(client, username="driver-collection-program")
    sync_response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-collection-001",
            "driver_id": driver.id,
            "batch_id": "batch-collection-confirm-001",
            "sent_at": "2026-04-08T10:15:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-COLLECTION-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-collection-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_collected": 6,
                        "quantity_empty_collected": 6,
                        "confirmed_by": "Client Collecte",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.375,
                            "longitude": -1.525,
                            "accuracy": 8.0,
                        },
                        "delivered_at": "2026-04-08T10:10:00Z",
                    },
                }
            ],
        },
    )

    assert sync_response.status_code == 200
    db.refresh(line)
    db.refresh(delivery)

    assert line.quantity_collected == 6
    assert line.status == "collected"
    assert delivery.collected_quantity_total == 6
    assert delivery.total_amount is None

    outbox_event = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == "delivery_confirmation:conf-collection-001"
    ).one()
    assert outbox_event.event_type == "COLLECTION_CONFIRMED"
    assert outbox_event.payload_json["quantity_collected"] == 6


def test_sage_program_upsert_cancels_stale_lines_and_projected_delivery(client, db):
    driver, depot, truck = _seed_program_context(db, suffix="program-stale")

    initial_payload = _program_payload(
        program_code="PRG-STALE-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-S1",
                "client_name": "Client Stable",
                "product_code": "GAZ_6KG",
                "quantity_planned": 8,
            },
            {
                "line_code": "L2",
                "external_line_id": "EXT-S2",
                "client_name": "Client Removed",
                "product_code": "GAZ_12KG",
                "quantity_planned": 4,
            },
        ],
    )

    updated_payload = _program_payload(
        program_code="PRG-STALE-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=2,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-S1",
                "client_name": "Client Stable",
                "product_code": "GAZ_6KG",
                "quantity_planned": 10,
            },
        ],
    )

    first_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=initial_payload,
    )
    second_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=updated_payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    stale_line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-S2").one()
    assert stale_line.status == "cancelled"
    assert stale_line.delivery is not None
    assert stale_line.delivery.status == DeliveryStatusEnum.CANCELLED


def test_calculate_delivery_amount_returns_expected_totals():
    summary = calculate_delivery_amount(
        quantity_delivered=7,
        unit_price=Decimal("1250.00"),
        tax_rate=Decimal("0.1800"),
    )

    assert summary["unit_price"] == Decimal("1250.00")
    assert summary["tax_rate"] == Decimal("0.1800")
    assert summary["subtotal_amount"] == Decimal("8750.00")
    assert summary["tax_amount"] == Decimal("1575.00")
    assert summary["total_amount"] == Decimal("10325.00")


def test_driver_sync_confirmation_updates_program_line_and_creates_outbox_event(client, db):
    driver, depot, truck = _seed_program_context(db, suffix="driver-program-confirm")
    db.add(
        PricingRule(
            product_code="GAZ_12KG",
            product_label="Gaz 12 kg",
            depot_id=depot.id,
            unit_price=Decimal("1000.00"),
            tax_rate=Decimal("0.1800"),
            active=True,
        )
    )
    db.commit()

    program = Program(
        program_code="PRG-DRV-001",
        program_date=datetime.utcnow() + timedelta(hours=1),
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        transporter_name="SODIGAZ Logistics",
        status="active",
        sync_version=1,
    )
    db.add(program)
    db.commit()
    db.refresh(program)

    line = ProgramLine(
        program_id=program.id,
        line_code="L-CNF-1",
        external_line_id="EXT-CNF-1",
        client_name="Client Confirmation",
        destination_address="Karpala",
        product_code="GAZ_12KG",
        product_label="Gaz 12 kg",
        quantity_planned=10,
        quantity_delivered=0,
        status="pending",
    )
    db.add(line)
    db.commit()
    db.refresh(line)

    delivery = Delivery(
        truck_id=truck.id,
        depot_id=depot.id,
        destination_name="Client Confirmation",
        destination_address="Karpala",
        driver_id=driver.id,
        quantity_6kg=0,
        quantity_12kg=10,
        quantity=10,
        status=DeliveryStatusEnum.PENDING,
        scheduled_date=datetime.utcnow() + timedelta(hours=2),
        source_type="sage_program",
        external_delivery_id="PRG-DRV-001:L-CNF-1",
        program_id=program.id,
        program_line_id=line.id,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    token = _login_token(client, username="driver-driver-program-confirm")
    response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-program-001",
            "driver_id": driver.id,
            "batch_id": "batch-program-confirm-001",
            "sent_at": "2026-04-08T09:45:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-PROGRAM-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-program-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 10,
                        "quantity_empty_collected": 7,
                        "customer": "CLI-PROGRAM-001",
                        "confirmed_by": "Client Confirmation",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.370,
                            "longitude": -1.520,
                            "accuracy": 9.5,
                        },
                        "delivered_at": "2026-04-08T09:40:00Z",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["accepted"] == 1
    assert payload["results"][0]["amount_summary"]["total_amount"] == "11800.00"

    db.refresh(line)
    db.refresh(delivery)

    assert line.quantity_delivered == 10
    assert line.status == "delivered"
    assert line.unit_price == Decimal("1000.00")
    assert line.tax_amount == Decimal("1800.00")
    assert delivery.status == DeliveryStatusEnum.COMPLETED
    assert delivery.total_amount == Decimal("11800.00")
    assert delivery.quantity_12kg_vide_recupere == 7

    outbox_event = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == "delivery_confirmation:conf-program-001"
    ).one()
    assert outbox_event.event_type == "DELIVERY_CONFIRMED"
    assert outbox_event.status == "pending"
    assert outbox_event.payload_json["program_code"] == "PRG-DRV-001"