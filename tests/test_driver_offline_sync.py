from datetime import datetime, timedelta

from app.models import (
    Delivery,
    DeliveryConfirmationEvent,
    DeliveryStatusEnum,
    Depot,
    RoleEnum,
    SyncConflict,
    Truck,
    User,
)
from app.auth import hash_password


def _create_driver(db, username="driver-offline"):
    driver = User(
        email=f"{username}@example.com",
        username=username,
        full_name="Driver Offline",
        hashed_password=hash_password("secret123"),
        role=RoleEnum.RAVITAILLEUR,
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


def _login_token(client, username="driver-offline", password="secret123"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _seed_driver_mission(db, driver):
    depot = Depot(
        name=f"Depot-{driver.username}",
        manager_id=None,
        latitude=12.37,
        longitude=-1.52,
        stock_6kg_plein=40,
        stock_12kg_plein=25,
        stock_6kg_vide=5,
        stock_12kg_vide=3,
        capacity_6kg=100,
        capacity_12kg=100,
        address="Ouagadougou secteur 1",
        city="Ouagadougou",
        phone="70000000",
    )
    db.add(depot)
    db.commit()
    db.refresh(depot)

    truck = Truck(
        license_plate=f"11-{driver.id:03d}-BF",
        driver_id=driver.id,
        capacity_6kg=100,
        capacity_12kg=80,
        current_load_6kg_plein=22,
        current_load_12kg_plein=14,
        current_load_6kg_vide=2,
        current_load_12kg_vide=1,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)

    delivery = Delivery(
        truck_id=truck.id,
        depot_id=depot.id,
        destination_name="Client Rural A",
        destination_address="Village Kamboinse",
        destination_latitude=12.38,
        destination_longitude=-1.55,
        contact_name="Boutique A",
        contact_phone="71000000",
        driver_id=driver.id,
        quantity_6kg=0,
        quantity_12kg=10,
        quantity=10,
        scheduled_date=datetime.utcnow() + timedelta(hours=2),
        status=DeliveryStatusEnum.PENDING,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    return depot, truck, delivery


def test_driver_bootstrap_returns_assignments_and_truck_stock(client, db):
    driver = _create_driver(db, username="driver-bootstrap")
    _seed_driver_mission(db, driver)
    token = _login_token(client, username="driver-bootstrap")

    response = client.get(
        "/api/driver/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["driver"]["id"] == driver.id
    assert len(payload["assignments"]) == 1
    assert payload["truck_stock"][0]["product"] == "GAZ_6KG"
    assert payload["reference_data"]["sync_policy_version"] == 1


def test_driver_sync_batch_accepts_offline_delivery_confirmation(client, db):
    driver = _create_driver(db, username="driver-sync-ok")
    _, _, delivery = _seed_driver_mission(db, driver)
    token = _login_token(client, username="driver-sync-ok")

    response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-001",
            "driver_id": driver.id,
            "batch_id": "batch-sync-ok-001",
            "sent_at": "2026-03-12T15:40:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-1-DEL-1-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 10,
                        "quantity_empty_collected": 8,
                        "customer": "CLIENT_045",
                        "confirmed_by": "M. Ouedraogo",
                        "customer_phone": "72000000",
                        "confirmation_mode": "signature",
                        "signature_base64": "base64-signature",
                        "gps": {
                            "latitude": 12.371,
                            "longitude": -1.519,
                            "accuracy": 15.5
                        },
                        "delivered_at": "2026-03-12T14:52:03Z"
                    }
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["accepted"] == 1
    assert payload["results"][0]["status"] == "accepted"

    db.refresh(delivery)
    assert delivery.status == DeliveryStatusEnum.COMPLETED
    assert delivery.quantity_12kg_vide_recupere == 8

    event = db.query(DeliveryConfirmationEvent).filter(
        DeliveryConfirmationEvent.delivery_id == delivery.id
    ).one()
    assert event.customer_reference == "CLIENT_045"
    assert event.device_id == "SM-A057-001"


def test_driver_sync_batch_accepts_anomaly_report(client, db):
    driver = _create_driver(db, username="driver-sync-anomaly")
    _, _, delivery = _seed_driver_mission(db, driver)
    token = _login_token(client, username="driver-sync-anomaly")

    response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-003",
            "driver_id": driver.id,
            "batch_id": "batch-sync-anomaly-001",
            "sent_at": "2026-03-12T15:40:00Z",
            "operations": [
                {
                    "type": "anomaly_report",
                    "idempotency_key": "DRV-1-ANOM-1-001",
                    "payload": {
                        "report_id": "anom-001",
                        "delivery_id": delivery.id,
                        "anomaly_type": "client_absent",
                        "notes": "Client absent, prendre photo.",
                        "reported_by": "Driver A",
                        "reported_at": "2026-03-12T14:52:03Z",
                        "gps": {
                            "latitude": 12.371,
                            "longitude": -1.519,
                            "accuracy": 10.5
                        }
                    }
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["accepted"] == 1
    assert payload["results"][0]["status"] == "accepted"

    db.refresh(delivery)
    assert delivery.status == DeliveryStatusEnum.IN_PROGRESS
    assert "client_absent" in (delivery.notes or "")


def test_driver_sync_batch_is_idempotent_for_replayed_batches(client, db):
    driver = _create_driver(db, username="driver-sync-replay")
    _, _, delivery = _seed_driver_mission(db, driver)
    token = _login_token(client, username="driver-sync-replay")

    request_body = {
        "device_id": "SM-A057-001",
        "driver_id": driver.id,
        "batch_id": "batch-sync-replay-001",
        "sent_at": "2026-03-12T15:40:00Z",
        "operations": [
            {
                "type": "delivery_confirmation",
                "idempotency_key": "DRV-REPLAY-DEL-CONF-001",
                "payload": {
                    "confirmation_id": "conf-replay-001",
                    "delivery_id": delivery.id,
                    "product": "GAZ_12KG",
                    "quantity_delivered": 10,
                    "quantity_empty_collected": 5,
                    "confirmation_mode": "code",
                    "confirmation_code": "4729",
                    "delivered_at": "2026-03-12T14:52:03Z"
                }
            }
        ]
    }

    first_response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json=request_body,
    )
    second_response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json=request_body,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == second_response.json()

    events = db.query(DeliveryConfirmationEvent).filter(
        DeliveryConfirmationEvent.delivery_id == delivery.id
    ).all()
    assert len(events) == 1


def test_driver_sync_batch_creates_conflict_for_completed_delivery(client, db):
    driver = _create_driver(db, username="driver-sync-conflict")
    _, _, delivery = _seed_driver_mission(db, driver)
    delivery.status = DeliveryStatusEnum.COMPLETED
    delivery.actual_end = datetime.utcnow()
    db.commit()
    token = _login_token(client, username="driver-sync-conflict")

    response = client.post(
        "/api/driver/sync/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "device_id": "SM-A057-001",
            "driver_id": driver.id,
            "batch_id": "batch-sync-conflict-001",
            "sent_at": "2026-03-12T15:40:00Z",
            "operations": [
                {
                    "type": "delivery_confirmation",
                    "idempotency_key": "DRV-CONFLICT-DEL-CONF-001",
                    "payload": {
                        "confirmation_id": "conf-conflict-001",
                        "delivery_id": delivery.id,
                        "product": "GAZ_12KG",
                        "quantity_delivered": 10,
                        "quantity_empty_collected": 2,
                        "confirmation_mode": "code",
                        "confirmation_code": "1111",
                        "delivered_at": "2026-03-12T14:52:03Z"
                    }
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["conflicts"] == 1
    assert payload["results"][0]["code"] == "DELIVERY_ALREADY_COMPLETED"

    conflicts = db.query(SyncConflict).filter(SyncConflict.delivery_id == delivery.id).all()
    assert len(conflicts) == 1