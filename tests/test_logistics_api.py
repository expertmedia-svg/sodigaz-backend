from datetime import datetime, timedelta
from uuid import uuid4

from app.models import Delivery, DeliveryStatusEnum, Depot, ExternalMapping, IntegrationOutbox, Truck, User, RoleEnum
from app.auth import hash_password


def _seed_logistics_context(db, suffix=None):
    suffix = suffix or uuid4().hex[:8]
    driver = User(
        email=f"logistics-driver-{suffix}@example.com",
        username=f"logistics-driver-{suffix}",
        full_name="Driver Logistics",
        hashed_password=hash_password("secret123"),
        role=RoleEnum.RAVITAILLEUR,
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)

    depot = Depot(
        name=f"Ouaga Centre {suffix}",
        latitude=12.3714,
        longitude=-1.5197,
        stock_6kg_plein=50,
        stock_12kg_plein=30,
        stock_6kg_vide=8,
        stock_12kg_vide=5,
        capacity_6kg=200,
        capacity_12kg=200,
        address="Centre-ville",
        city="Ouagadougou",
        phone="70000000",
    )
    db.add(depot)
    db.commit()
    db.refresh(depot)

    db.add(
        ExternalMapping(
            system_name="sage_x3",
            entity_type="depot",
            internal_id=str(depot.id),
            external_code="OUAGA01",
        )
    )

    truck = Truck(
        license_plate=f"11-{suffix[:4].upper()}-BF",
        driver_id=driver.id,
        capacity_6kg=100,
        capacity_12kg=80,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)

    delivery = Delivery(
        truck_id=truck.id,
        depot_id=depot.id,
        destination_name="CLIENT_045",
        destination_address="Zone rurale",
        destination_latitude=12.40,
        destination_longitude=-1.55,
        contact_name="Client Rural",
        contact_phone="71000000",
        driver_id=driver.id,
        quantity_6kg=0,
        quantity_12kg=10,
        quantity=10,
        quantity_12kg_vide_recupere=7,
        scheduled_date=datetime.utcnow() + timedelta(hours=2),
        status=DeliveryStatusEnum.COMPLETED,
        actual_end=datetime.utcnow(),
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    return depot, delivery


def test_publish_logistics_delivery_writes_outbox(client, db):
    suffix = uuid4().hex[:8]
    _, delivery = _seed_logistics_context(db, suffix=suffix)
    message_id = f"erp-msg-{suffix}"

    response = client.post(
        "/api/logistics/v1/deliveries",
        json={
            "message_id": message_id,
            "occurred_at": "2026-03-12T12:00:00Z",
            "depot": "OUAGA01",
            "product": "GAZ_12KG",
            "quantity": 10,
            "empty_quantity": 7,
            "delivery_agent": "LIV002",
            "customer": "CLIENT_045",
            "delivery_date": "2026-03-12",
            "source": "mobile_offline_sync",
            "reference": {
                "delivery_id": delivery.id,
                "confirmation_id": "conf-001"
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    outbox = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == message_id
    ).one()
    assert outbox.event_type == "delivery"


def test_get_inventory_snapshot_returns_mapped_depot_code(client, db):
    _seed_logistics_context(db)

    response = client.get("/api/logistics/v1/inventory")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert any(item["depot"] == "OUAGA01" for item in payload["items"])


def test_get_delivery_detail_for_logistics(client, db):
    _, delivery = _seed_logistics_context(db)

    response = client.get(f"/api/logistics/v1/deliveries/{delivery.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery_id"] == delivery.id
    assert payload["depot"] == "OUAGA01"


def test_get_integration_events_lists_outbox_entries(client, db):
    suffix = uuid4().hex[:8]
    _seed_logistics_context(db)
    client.post(
        "/api/logistics/v1/stock-movements",
        json={
            "message_id": f"erp-stock-{suffix}",
            "occurred_at": "2026-03-12T12:00:00Z",
            "depot": "OUAGA01",
            "product": "GAZ_12KG",
            "movement_type": "delivery_out",
            "quantity": 10,
            "empty_quantity": 7,
            "source": "backend"
        },
    )

    response = client.get("/api/logistics/v1/integration-events?status=pending")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 1
    assert payload[0]["status"] == "pending"