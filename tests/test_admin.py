def _register_user(client, email, username, role="user"):
    payload = {
        "email": email,
        "username": username,
        "password": "secret123",
        "full_name": username,
        "role": role,
    }
    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 200
    return r.json()


def _login(client, username, password="secret123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_admin_depots_requires_admin_role(client):
    # Créer un simple utilisateur
    _register_user(client, "user1@example.com", "user1", role="user")
    user_token = _login(client, "user1")

    # Appel de l'endpoint admin avec un user normal -> 403
    r = client.get(
        "/api/admin/depots",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403


def test_admin_depots_with_admin_ok(client):
    # Créer un admin et se connecter
    _register_user(client, "admin2@example.com", "admin2", role="admin")
    admin_token = _login(client, "admin2")

    r = client.get(
        "/api/admin/depots",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_delivery_correction_endpoint(client, db):
    from app.models import Delivery, Truck, Depot, User, RoleEnum
    from datetime import datetime

    # Register and login admin
    _register_user(client, "admin_corr@example.com", "admin_corr", role="admin")
    admin_token = _login(client, "admin_corr")

    # Create dummy depot and truck
    depot = Depot(name="Depot Test Correction", city="Ouagadougou", address="Secteur 15", latitude=12.3, longitude=-1.5)
    db.add(depot)
    db.commit()

    truck = Truck(license_plate="11-AA-1111", capacity_6kg=100, capacity_12kg=100, is_active=True)
    db.add(truck)
    db.commit()

    # Create completed delivery
    delivery = Delivery(
        truck_id=truck.id,
        depot_id=depot.id,
        destination_name="Client Test Correction",
        destination_address="Avenue de la correction",
        destination_latitude=12.3,
        destination_longitude=-1.5,
        quantity_6kg=10,
        quantity_12kg=5,
        delivered_quantity_total=15,
        status="completed",
        scheduled_date=datetime.utcnow()
    )
    db.add(delivery)
    db.commit()

    # Correct quantities via admin HTTP endpoint
    correction_payload = {
        "quantity_6kg": 8,
        "quantity_12kg": 12,
        "comment": "Erreur de comptage sur le terrain"
    }

    r = client.post(
        f"/api/admin/deliveries/{delivery.id}/correct",
        json=correction_payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert r.status_code == 200
    res_data = r.json()
    assert res_data["quantity_6kg"] == 8
    assert res_data["quantity_12kg"] == 12
    assert "[RECTIFICATION LOGISTIQUE]" in res_data["notes"]
    assert "Erreur de comptage" in res_data["notes"]

    # Verify database was updated
    db.refresh(delivery)
    assert delivery.quantity_6kg == 8
    assert delivery.quantity_12kg == 12
    assert delivery.delivered_quantity_total == 20