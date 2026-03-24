from datetime import datetime
from uuid import uuid4

import httpx

from app.auth import hash_password
from app.models import IntegrationHealthCheck, IntegrationOutbox, RoleEnum, SyncConflict, User
from app.services.outbox_worker import check_sage_x3_health, process_pending_outbox_events


def _create_admin(db, username=None):
    username = username or f"admin-{uuid4().hex[:8]}"
    admin = User(
        email=f"{username}@example.com",
        username=username,
        full_name="Admin Test",
        hashed_password=hash_password("secret123"),
        role=RoleEnum.ADMIN,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _admin_token(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_admin_can_list_and_resolve_sync_conflicts(client, db):
    admin = _create_admin(db)
    conflict = SyncConflict(
        aggregate_type="delivery",
        aggregate_id="155",
        delivery_id=None,
        batch_id="batch-001",
        driver_id=None,
        device_id="device-01",
        idempotency_key="DRV-001",
        conflict_type="delivery_already_completed",
        local_payload={"delivery_id": 155},
        server_state={"delivery_status": "completed"},
    )
    db.add(conflict)
    db.commit()
    db.refresh(conflict)

    token = _admin_token(client, admin.username)

    list_response = client.get(
        "/api/admin/sync-conflicts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    assert any(item["id"] == conflict.id for item in list_response.json())

    resolve_response = client.put(
        f"/api/admin/sync-conflicts/{conflict.id}/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={"resolution_status": "resolved_accept_offline"},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["resolution_status"] == "resolved_accept_offline"


def test_admin_can_process_integration_outbox(client, db, monkeypatch):
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_PUSH_MODE", "mock")

    admin = _create_admin(db)
    outbox_event = IntegrationOutbox(
        event_type="delivery",
        aggregate_type="delivery",
        aggregate_id="155",
        external_message_id=f"msg-{uuid4().hex[:8]}",
        payload_json={"delivery_id": 155, "product": "GAZ_12KG", "quantity": 10},
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(outbox_event)
    db.commit()

    token = _admin_token(client, admin.username)

    response = client.post(
        "/api/admin/integration-outbox/process",
        headers={"Authorization": f"Bearer {token}"},
        json={"limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] >= 1
    assert payload["sent"] >= 1

    db.refresh(outbox_event)
    assert outbox_event.status == "sent"


def test_outbox_worker_can_push_to_real_http_endpoint(db, monkeypatch):
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_PUSH_MODE", "http")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_BASE_URL", "https://sage-x3.example.com/api")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_API_KEY", "secret-key")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_AUTH_SCHEME", "api-key")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_AUTH_HEADER", "X-API-Key")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_DELIVERY_ENDPOINT", "/logistics/deliveries")

    captured = {}

    class FakeClient:
        def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return httpx.Response(
                200,
                json={"status": "accepted", "message_id": json["message_id"]},
                request=httpx.Request("POST", url),
            )

    outbox_event = IntegrationOutbox(
        event_type="delivery",
        aggregate_type="delivery",
        aggregate_id="155",
        external_message_id=f"msg-{uuid4().hex[:8]}",
        payload_json={"message_id": f"erp-{uuid4().hex[:8]}", "delivery_id": 155, "quantity": 10},
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(outbox_event)
    db.commit()

    result = process_pending_outbox_events(db, limit=10, client=FakeClient())

    assert result["sent"] == 1
    assert captured["url"] == "https://sage-x3.example.com/api/logistics/deliveries"
    assert captured["headers"]["X-API-Key"] == "secret-key"
    db.refresh(outbox_event)
    assert outbox_event.status == "sent"


def test_check_sage_x3_health_in_mock_mode(monkeypatch):
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_PUSH_MODE", "mock")
    result = check_sage_x3_health()
    assert result["status"] == "healthy"
    assert result["mode"] == "mock"


def test_admin_can_read_integration_health(client, db, monkeypatch):
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_PUSH_MODE", "http")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_BASE_URL", "https://sage-x3.example.com/api")
    monkeypatch.setattr("app.services.outbox_worker.settings.SAGE_X3_HEALTH_ENDPOINT", "/health")

    class FakeHealthClient:
        def get(self, url, headers):
            return httpx.Response(
                200,
                json={"service": "sage_x3", "status": "ok"},
                request=httpx.Request("GET", url),
            )

    failed_event = IntegrationOutbox(
        event_type="delivery",
        aggregate_type="delivery",
        aggregate_id="404",
        external_message_id=f"msg-{uuid4().hex[:8]}",
        payload_json={"delivery_id": 404},
        status="failed_dead_letter",
        retry_count=3,
        error_message="ERP timeout",
        created_at=datetime.utcnow(),
        last_attempt_at=datetime.utcnow(),
    )
    db.add(failed_event)
    stored_check = IntegrationHealthCheck(
        system_name="sage_x3",
        mode="mock",
        status="healthy",
        detail="Stored check",
        base_url="https://sage-x3.example.com/api",
        health_url="https://sage-x3.example.com/api/health",
        status_code=200,
        response_json={"service": "sage_x3", "status": "ok"},
        created_at=datetime.utcnow(),
    )
    db.add(stored_check)
    db.commit()

    monkeypatch.setattr("app.routers.admin.check_sage_x3_health", lambda: check_sage_x3_health(client=FakeHealthClient()))

    admin = _create_admin(db)
    token = _admin_token(client, admin.username)

    response = client.get(
        "/api/admin/integration-outbox/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["response"]["status"] == "ok"
    assert payload["probed_at"]
    assert payload["last_checked_at"]
    assert payload["last_check"]["detail"] == "Stored check"
    assert payload["recent_checks"][0]["detail"] == "Stored check"
    assert payload["recent_errors"][0]["error_message"] == "ERP timeout"


def test_admin_can_trigger_manual_integration_health_check(client, db, monkeypatch):
    monkeypatch.setattr("app.routers.admin.check_sage_x3_health", lambda: {
        "status": "healthy",
        "mode": "mock",
        "detail": "Manual check executed",
    })

    admin = _create_admin(db)
    token = _admin_token(client, admin.username)

    response = client.post(
        "/api/admin/integration-outbox/health/check",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["detail"] == "Manual check executed"
    assert payload["probed_at"]
    assert payload["last_checked_at"]
    assert payload["last_check"]["detail"] == "Manual check executed"
    assert payload["recent_checks"][0]["detail"] == "Manual check executed"
    assert isinstance(payload["recent_errors"], list)

    latest_check = db.query(IntegrationHealthCheck).order_by(IntegrationHealthCheck.created_at.desc()).first()
    assert latest_check is not None
    assert latest_check.detail == "Manual check executed"
    assert latest_check.checked_by == admin.id