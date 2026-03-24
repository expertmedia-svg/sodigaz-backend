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


def _create_depot_with_admin_and_manager(client):
    # Admin
    _register_user(client, "admin-user@example.com", "admin_user", role="admin")
    admin_token = _login(client, "admin_user")

    # Gestionnaire de dépôt
    depot_manager = _register_user(
        client,
        "manager2@example.com",
        "manager2",
        role="depot",
    )
    manager_id = depot_manager["user"]["id"]

    depot_payload = {
        "name": "Depot Test 2",
        "latitude": 1.0,
        "longitude": 1.0,
        "capacity": 500.0,
        "address": "Adresse test 2",
        "phone": "987654321",
        "manager_id": manager_id,
    }
    r = client.post(
        "/api/admin/depots",
        json=depot_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200


def test_user_all_depots(client):
    # Créer au moins un dépôt accessible
    _create_depot_with_admin_and_manager(client)

    # Créer un utilisateur final
    _register_user(client, "user-final@example.com", "user_final", role="user")
    user_token = _login(client, "user_final")

    r = client.get(
        "/api/user/all-depots",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    depots = r.json()
    assert isinstance(depots, list)
    assert len(depots) >= 1
