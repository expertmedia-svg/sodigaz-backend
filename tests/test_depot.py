def _register_user(client, email, username, role):
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


def test_depot_info_for_manager(client):
    # Créer un admin et un gestionnaire de dépôt
    admin_data = _register_user(client, "admin-depot@example.com", "admin_depot", role="admin")
    admin_token = _login(client, "admin_depot")

    depot_manager_data = _register_user(
        client,
        "manager1@example.com",
        "manager1",
        role="depot",
    )
    manager_id = depot_manager_data["user"]["id"]

    # Créer un dépôt via l'API admin
    depot_payload = {
        "name": "Depot Test 1",
        "latitude": 0.0,
        "longitude": 0.0,
        "capacity": 1000.0,
        "address": "Adresse test",
        "phone": "123456789",
        "manager_id": manager_id,
    }
    r = client.post(
        "/api/admin/depots",
        json=depot_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200

    # Connexion en tant que gestionnaire de dépôt
    manager_token = _login(client, "manager1")

    r = client.get(
        "/api/depot/info",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Depot Test 1"
    assert data["capacity"] == 1000.0