def test_register_and_login_admin(client):
    # Inscription d'un admin
    register_payload = {
        "email": "admin@example.com",
        "username": "admin_test",
        "password": "secret123",
        "full_name": "Admin Test",
        "role": "admin",
    }
    r = client.post("/api/auth/register", json=register_payload)
    if r.status_code != 200:
        print("REGISTER_ERROR", r.status_code, r.json())
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["user"]["username"] == "admin_test"
    assert data["user"]["role"] == "admin"

    # Connexion de l'admin
    login_payload = {"username": "admin_test", "password": "secret123"}
    r = client.post("/api/auth/login", json=login_payload)
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["user"]["username"] == "admin_test"