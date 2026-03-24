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


def test_ravitailleur_today_deliveries_empty(client):
    # Créer un ravitailleur
    _register_user(client, "rav1@example.com", "rav1", role="ravitailleur")
    token = _login(client, "rav1")

    # Il n'a pas encore de livraisons planifiées -> liste vide
    r = client.get(
        "/api/ravitailleur/today-deliveries",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)