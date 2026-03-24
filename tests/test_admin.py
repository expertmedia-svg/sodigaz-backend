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