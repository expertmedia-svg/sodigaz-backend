from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Delivery, IntegrationOutbox, SageMissionStatusEnum
from app.time_utils import utc_now


def _get_event_endpoints() -> dict[str, str]:
    return {
        "delivery": settings.SAGE_X3_DELIVERY_ENDPOINT,
        "delivery_completed": settings.SAGE_X3_DELIVERY_ENDPOINT,
        "DELIVERY_CONFIRMED": settings.SAGE_X3_DELIVERY_ENDPOINT,
        "COLLECTION_CONFIRMED": settings.SAGE_X3_DELIVERY_ENDPOINT,
        "stock_movement": settings.SAGE_X3_STOCK_MOVEMENT_ENDPOINT,
    }


def _send_mock_event(event: IntegrationOutbox) -> dict:
    return {
        "status": "mock_sent",
        "message": "Event processed in mock mode",
        "message_id": event.external_message_id,
        "event_type": event.event_type,
    }


def _send_to_sage_x3(event: IntegrationOutbox, client: httpx.Client) -> dict:
    endpoint = _get_event_endpoints().get(event.event_type)
    if not endpoint:
        raise ValueError(f"Unsupported outbox event type: {event.event_type}")

    if not settings.SAGE_X3_BASE_URL:
        raise ValueError("SAGE_X3_BASE_URL is not configured")

    headers = {"Content-Type": "application/json"}
    auth = None

    if settings.SAGE_X3_AUTH_SCHEME.lower() == "basic" and settings.SAGE_X3_API_USER:
        auth = (settings.SAGE_X3_API_USER, settings.SAGE_X3_API_PASSWORD)
    elif settings.SAGE_X3_API_KEY:
        if settings.SAGE_X3_AUTH_SCHEME.lower() == "bearer":
            headers[settings.SAGE_X3_AUTH_HEADER] = f"Bearer {settings.SAGE_X3_API_KEY}"
        else:
            headers[settings.SAGE_X3_AUTH_HEADER] = settings.SAGE_X3_API_KEY

    response = client.post(
        f"{settings.SAGE_X3_BASE_URL.rstrip('/')}{endpoint}",
        json=event.payload_json,
        headers=headers,
        auth=auth,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError:
        payload = {"body": response.text}

    return {
        "status": "sent",
        "endpoint": endpoint,
        "status_code": response.status_code,
        "response": payload,
    }


def _build_auth_info() -> tuple[dict[str, str], Optional[tuple[str, str]]]:
    headers = {"Content-Type": "application/json"}
    auth = None

    if settings.SAGE_X3_AUTH_SCHEME.lower() == "basic" and settings.SAGE_X3_API_USER:
        auth = (settings.SAGE_X3_API_USER, settings.SAGE_X3_API_PASSWORD)
    elif settings.SAGE_X3_API_KEY:
        if settings.SAGE_X3_AUTH_SCHEME.lower() == "bearer":
            headers[settings.SAGE_X3_AUTH_HEADER] = f"Bearer {settings.SAGE_X3_API_KEY}"
        else:
            headers[settings.SAGE_X3_AUTH_HEADER] = settings.SAGE_X3_API_KEY
    
    return headers, auth


def _apply_delivery_sync_side_effect(db: Session, event: IntegrationOutbox) -> None:
    if event.aggregate_type != "delivery":
        return

    try:
        delivery_id = int(event.aggregate_id)
    except (TypeError, ValueError):
        return

    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if delivery is None:
        return

    if event.status == "sent":
        delivery.external_status = SageMissionStatusEnum.SYNCED
        delivery.external_sync_at = event.sent_at or utc_now()
        delivery.external_error = None
    elif event.status in {"failed_retryable", "failed_dead_letter"}:
        delivery.external_error = event.error_message


def check_sage_x3_health(client: Optional[httpx.Client] = None) -> dict:
    if settings.SAGE_X3_PUSH_MODE == "mock":
        return {
            "status": "healthy",
            "mode": "mock",
            "base_url": settings.SAGE_X3_BASE_URL or None,
            "detail": "Mock mode enabled",
        }

    if not settings.SAGE_X3_BASE_URL:
        return {
            "status": "unconfigured",
            "mode": settings.SAGE_X3_PUSH_MODE,
            "base_url": None,
            "detail": "SAGE_X3_BASE_URL is not configured",
        }

    own_client = None
    http_client = client
    if http_client is None:
        own_client = httpx.Client(timeout=settings.SAGE_X3_TIMEOUT_SECONDS)
        http_client = own_client

    try:
        endpoint = settings.SAGE_X3_HEALTH_ENDPOINT or ""
        url = f"{settings.SAGE_X3_BASE_URL.rstrip('/')}{endpoint}"
        headers, auth = _build_auth_info()
        response = http_client.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            payload = {"body": response.text}
        return {
            "status": "healthy",
            "mode": settings.SAGE_X3_PUSH_MODE,
            "base_url": settings.SAGE_X3_BASE_URL,
            "health_url": url,
            "status_code": response.status_code,
            "response": payload,
        }
    except Exception as exc:
        return {
            "status": "unreachable",
            "mode": settings.SAGE_X3_PUSH_MODE,
            "base_url": settings.SAGE_X3_BASE_URL,
            "health_url": f"{settings.SAGE_X3_BASE_URL.rstrip('/')}{settings.SAGE_X3_HEALTH_ENDPOINT or ''}",
            "detail": str(exc),
        }
    finally:
        if own_client is not None:
            own_client.close()


def process_pending_outbox_events(
    db: Session,
    *,
    limit: int = 50,
    client: Optional[httpx.Client] = None,
) -> dict:
    now = utc_now()
    query = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.status.in_(["pending", "failed_retryable"])
    ).order_by(IntegrationOutbox.created_at.asc())

    events = query.limit(limit).all()
    results = []

    own_client = None
    http_client = client
    if http_client is None and settings.SAGE_X3_PUSH_MODE != "mock":
        own_client = httpx.Client(timeout=settings.SAGE_X3_TIMEOUT_SECONDS)
        http_client = own_client

    try:
        for event in events:
            event.status = "sending"
            event.last_attempt_at = now
            db.flush()

            try:
                if settings.SAGE_X3_PUSH_MODE == "mock":
                    response_payload = _send_mock_event(event)
                else:
                    response_payload = _send_to_sage_x3(event, http_client)

                event.status = "sent"
                event.response_json = response_payload
                event.error_message = None
                event.sent_at = utc_now()
                _apply_delivery_sync_side_effect(db, event)
                results.append(
                    {
                        "id": event.id,
                        "aggregate_id": event.aggregate_id,
                        "aggregate_type": event.aggregate_type,
                        "event_type": event.event_type,
                        "message_id": event.external_message_id,
                        "status": event.status,
                    }
                )
            except Exception as exc:
                event.retry_count += 1
                event.error_message = str(exc)
                if event.retry_count >= settings.INTEGRATION_OUTBOX_MAX_RETRIES:
                    event.status = "failed_dead_letter"
                else:
                    event.status = "failed_retryable"

                _apply_delivery_sync_side_effect(db, event)

                results.append(
                    {
                        "id": event.id,
                        "aggregate_id": event.aggregate_id,
                        "aggregate_type": event.aggregate_type,
                        "event_type": event.event_type,
                        "message_id": event.external_message_id,
                        "status": event.status,
                        "error": event.error_message,
                    }
                )

        db.commit()
    finally:
        if own_client is not None:
            own_client.close()

    return {
        "processed": len(events),
        "sent": sum(1 for item in results if item["status"] == "sent"),
        "failed": sum(1 for item in results if item["status"] != "sent"),
        "results": results,
    }