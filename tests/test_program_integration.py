from datetime import datetime, timedelta
from decimal import Decimal

from app.config import settings
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
    SageMissionStatusEnum,
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


def test_bidirectional_program_flow_completes_program_and_removes_it_from_driver_today_view(client, db):
    driver, depot, truck = _seed_program_context(db, suffix="bidirectional-flow")
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
        program_code="PRG-BIDIR-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-BIDIR-1",
                "client_code": "CLI-BIDIR-01",
                "client_name": "Client Bidirectionnel",
                "destination_address": "Secteur 12",
                "product_code": "GAZ_12KG",
                "product_label": "Gaz 12 kg",
                "quantity_planned": 12,
            }
        ],
    )

    create_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )
    assert create_response.status_code == 200

    token = _login_token(client, username="driver-bidirectional-flow")

    before_bootstrap = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert before_bootstrap.status_code == 200
    assert len(before_bootstrap.json()["assignments"]) == 1
    assert len(before_bootstrap.json()["today_programs"]) == 1

    program = db.query(Program).filter(Program.program_code == "PRG-BIDIR-001").one()
    line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-BIDIR-1").one()
    delivery = db.query(Delivery).filter(Delivery.program_id == program.id).one()

    sync_response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-bidir-001",
            "driver_id": driver.id,
            "batch_id": "batch-bidir-confirm-001",
            "sent_at": "2026-04-09T09:00:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-BIDIR-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-bidir-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 12,
                        "quantity_empty_collected": 10,
                        "customer": "CLI-BIDIR-01",
                        "confirmed_by": "Client Bidirectionnel",
                        "customer_phone": "72000011",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.371,
                            "longitude": -1.519,
                            "accuracy": 7.5
                        },
                        "delivered_at": "2026-04-09T08:55:00Z"
                    }
                }
            ]
        },
    )

    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["summary"]["accepted"] == 1
    assert sync_payload["sage_outbox"]["sent"] >= 1
    assert sync_payload["sage_outbox"]["failed"] == 0

    db.refresh(program)
    db.refresh(line)
    db.refresh(delivery)

    assert line.quantity_delivered == 12
    assert line.status == "delivered"
    assert delivery.status == DeliveryStatusEnum.COMPLETED
    assert delivery.delivered_quantity_total == 12
    assert delivery.external_status == SageMissionStatusEnum.SYNCED
    assert delivery.external_sync_at is not None
    assert program.status == "completed"

    confirmation_event = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == "delivery_confirmation:conf-bidir-001"
    ).one()
    assert confirmation_event.status == "sent"
    assert confirmation_event.payload_json["program_code"] == "PRG-BIDIR-001"
    assert confirmation_event.payload_json["program_line_id"] == line.id

    after_bootstrap = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after_bootstrap.status_code == 200
    assert after_bootstrap.json()["assignments"] == []
    assert after_bootstrap.json()["today_programs"] == []


def test_partial_driver_validation_keeps_program_in_progress_until_all_lines_are_done(client, db):
    driver, depot, truck = _seed_program_context(db, suffix="partial-flow")
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
        program_code="PRG-PARTIAL-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-PARTIAL-1",
                "client_code": "CLI-PART-01",
                "client_name": "Client Partiel A",
                "destination_address": "Secteur 14",
                "product_code": "GAZ_12KG",
                "product_label": "Gaz 12 kg",
                "quantity_planned": 12,
            },
            {
                "line_code": "L2",
                "external_line_id": "EXT-PARTIAL-2",
                "client_code": "CLI-PART-02",
                "client_name": "Client Partiel B",
                "destination_address": "Secteur 15",
                "product_code": "GAZ_6KG",
                "product_label": "Gaz 6 kg",
                "quantity_planned": 8,
                "unit_price": "3000.00",
                "tax_rate": "0.10",
            },
        ],
    )

    create_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )
    assert create_response.status_code == 200

    token = _login_token(client, username="driver-partial-flow")

    before_bootstrap = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert before_bootstrap.status_code == 200
    assert len(before_bootstrap.json()["assignments"]) == 2
    assert len(before_bootstrap.json()["today_programs"]) == 1
    assert before_bootstrap.json()["today_programs"][0]["status"] == "active"

    program = db.query(Program).filter(Program.program_code == "PRG-PARTIAL-001").one()
    first_line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-PARTIAL-1").one()
    second_line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-PARTIAL-2").one()
    first_delivery = db.query(Delivery).filter(Delivery.program_line_id == first_line.id).one()
    second_delivery = db.query(Delivery).filter(Delivery.program_line_id == second_line.id).one()

    sync_response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-partial-001",
            "driver_id": driver.id,
            "batch_id": "batch-partial-confirm-001",
            "sent_at": "2026-04-09T10:00:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-PARTIAL-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-partial-001",
                        "delivery_id": first_delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 12,
                        "quantity_empty_collected": 12,
                        "customer": "CLI-PART-01",
                        "confirmed_by": "Client Partiel A",
                        "customer_phone": "72000021",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.371,
                            "longitude": -1.519,
                            "accuracy": 6.5
                        },
                        "delivered_at": "2026-04-09T09:55:00Z"
                    }
                }
            ]
        },
    )

    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["summary"]["accepted"] == 1
    assert sync_payload["sage_outbox"]["sent"] >= 1
    assert sync_payload["sage_outbox"]["failed"] == 0

    db.refresh(program)
    db.refresh(first_line)
    db.refresh(second_line)
    db.refresh(first_delivery)
    db.refresh(second_delivery)

    assert first_line.status == "delivered"
    assert first_line.quantity_delivered == 12
    assert first_delivery.status == DeliveryStatusEnum.COMPLETED
    assert first_delivery.external_status == SageMissionStatusEnum.SYNCED

    assert second_line.status == "pending"
    assert second_delivery.status == DeliveryStatusEnum.PENDING
    assert program.status == "in_progress"

    after_bootstrap = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after_bootstrap.status_code == 200
    bootstrap_payload = after_bootstrap.json()
    assert len(bootstrap_payload["assignments"]) == 1
    assert bootstrap_payload["assignments"][0]["id"] == second_delivery.id
    assert len(bootstrap_payload["today_programs"]) == 1
    assert bootstrap_payload["today_programs"][0]["status"] == "in_progress"

    line_statuses = {
        line["line_code"]: line["status"]
        for line in bootstrap_payload["today_programs"][0]["lines"]
    }
    assert line_statuses == {"L1": "delivered", "L2": "pending"}


def test_outbound_sage_failure_sets_external_error_but_keeps_driver_flow_consistent(client, db, monkeypatch):
    from app.services import outbox_worker

    driver, depot, truck = _seed_program_context(db, suffix="sage-failure")
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
        program_code="PRG-FAIL-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-FAIL-1",
                "client_code": "CLI-FAIL-01",
                "client_name": "Client Echec Sage",
                "destination_address": "Secteur 16",
                "product_code": "GAZ_12KG",
                "product_label": "Gaz 12 kg",
                "quantity_planned": 12,
            }
        ],
    )

    create_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )
    assert create_response.status_code == 200

    token = _login_token(client, username="driver-sage-failure")
    program = db.query(Program).filter(Program.program_code == "PRG-FAIL-001").one()
    line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-FAIL-1").one()
    delivery = db.query(Delivery).filter(Delivery.program_id == program.id).one()

    monkeypatch.setattr(settings, "SAGE_X3_PUSH_MODE", "http")

    def _boom(event, client):
        raise RuntimeError("Sage unreachable for test")

    monkeypatch.setattr(outbox_worker, "_send_to_sage_x3", _boom)

    sync_response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-failure-001",
            "driver_id": driver.id,
            "batch_id": "batch-failure-confirm-001",
            "sent_at": "2026-04-09T11:00:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-FAIL-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-failure-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 12,
                        "quantity_empty_collected": 8,
                        "customer": "CLI-FAIL-01",
                        "confirmed_by": "Client Echec Sage",
                        "customer_phone": "72000031",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.371,
                            "longitude": -1.519,
                            "accuracy": 5.5
                        },
                        "delivered_at": "2026-04-09T10:55:00Z"
                    }
                }
            ]
        },
    )

    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["summary"]["accepted"] == 1
    assert sync_payload["sage_outbox"]["sent"] == 0
    assert sync_payload["sage_outbox"]["failed"] >= 1

    db.refresh(program)
    db.refresh(line)
    db.refresh(delivery)

    assert delivery.status == DeliveryStatusEnum.COMPLETED
    assert delivery.delivered_quantity_total == 12
    assert line.status == "delivered"
    assert line.quantity_delivered == 12
    assert program.status == "completed"
    assert delivery.external_status is None
    assert delivery.external_error == "Sage unreachable for test"

    confirmation_event = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == "delivery_confirmation:conf-failure-001"
    ).one()
    assert confirmation_event.status == "failed_retryable"

    after_bootstrap = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after_bootstrap.status_code == 200
    assert after_bootstrap.json()["assignments"] == []
    assert after_bootstrap.json()["today_programs"] == []


def test_failed_retryable_outbox_event_is_sent_after_sage_recovers(client, db, monkeypatch):
    from app.services import outbox_worker

    driver, depot, truck = _seed_program_context(db, suffix="retry-flow")
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
        program_code="PRG-RETRY-001",
        depot_id=depot.id,
        truck_id=truck.id,
        driver_id=driver.id,
        sync_version=1,
        lines=[
            {
                "line_code": "L1",
                "external_line_id": "EXT-RETRY-1",
                "client_code": "CLI-RETRY-01",
                "client_name": "Client Retry Sage",
                "destination_address": "Secteur 17",
                "product_code": "GAZ_12KG",
                "product_label": "Gaz 12 kg",
                "quantity_planned": 12,
            }
        ],
    )

    create_response = client.post(
        "/api/integration/sage/programs",
        headers={"x-sage-x3-token": "test-token-123"},
        json=payload,
    )
    assert create_response.status_code == 200

    token = _login_token(client, username="driver-retry-flow")
    program = db.query(Program).filter(Program.program_code == "PRG-RETRY-001").one()
    line = db.query(ProgramLine).filter(ProgramLine.external_line_id == "EXT-RETRY-1").one()
    delivery = db.query(Delivery).filter(Delivery.program_id == program.id).one()

    monkeypatch.setattr(settings, "SAGE_X3_PUSH_MODE", "http")

    def _boom(event, client):
        raise RuntimeError("Temporary Sage outage")

    monkeypatch.setattr(outbox_worker, "_send_to_sage_x3", _boom)

    first_sync = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-retry-001",
            "driver_id": driver.id,
            "batch_id": "batch-retry-confirm-001",
            "sent_at": "2026-04-09T12:00:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-RETRY-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-retry-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 12,
                        "quantity_empty_collected": 9,
                        "customer": "CLI-RETRY-01",
                        "confirmed_by": "Client Retry Sage",
                        "customer_phone": "72000041",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.371,
                            "longitude": -1.519,
                            "accuracy": 5.0
                        },
                        "delivered_at": "2026-04-09T11:55:00Z"
                    }
                }
            ]
        },
    )

    assert first_sync.status_code == 200
    db.refresh(delivery)
    failed_event = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == "delivery_confirmation:conf-retry-001"
    ).one()
    assert failed_event.status == "failed_retryable"
    assert delivery.external_status is None
    assert delivery.external_error == "Temporary Sage outage"

    def _success(event, client):
        return {
            "status": "sent",
            "message_id": event.external_message_id,
            "accepted": True,
        }

    monkeypatch.setattr(outbox_worker, "_send_to_sage_x3", _success)

    retry_result = outbox_worker.process_pending_outbox_events(db, limit=10)
    db.refresh(delivery)
    db.refresh(failed_event)

    assert retry_result["sent"] >= 1
    assert retry_result["failed"] == 0
    assert failed_event.status == "sent"
    assert delivery.status == DeliveryStatusEnum.COMPLETED
    assert line.status == "delivered"
    assert program.status == "completed"
    assert delivery.external_status == SageMissionStatusEnum.SYNCED
    assert delivery.external_sync_at is not None
    assert delivery.external_error is None

    after_bootstrap = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after_bootstrap.status_code == 200
    assert after_bootstrap.json()["assignments"] == []
    assert after_bootstrap.json()["today_programs"] == []


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