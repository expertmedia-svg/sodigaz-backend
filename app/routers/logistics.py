from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import Delivery, Depot, ExternalMapping, IntegrationOutbox, SageMissionStatusEnum
from app.schemas import SageMissionInbound
from app.time_utils import utc_now_iso, utc_now


router = APIRouter(prefix="/api/logistics/v1", tags=["logistics"])


class LogisticsReference(BaseModel):
    delivery_id: Optional[int] = None
    confirmation_id: Optional[str] = None


class LogisticsDeliveryPayload(BaseModel):
    message_id: str
    occurred_at: datetime
    depot: str
    product: str
    quantity: int
    empty_quantity: int = 0
    delivery_agent: str
    customer: str
    delivery_date: date
    source: str = "backend"
    reference: Optional[LogisticsReference] = None


class StockMovementPayload(BaseModel):
    message_id: str
    occurred_at: datetime
    depot: str
    product: str
    movement_type: str
    quantity: int
    empty_quantity: int = 0
    source: str = "backend"
    reference: Optional[dict] = None


def _create_outbox_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    message_id: str,
    payload: dict,
) -> dict:
    db: Session = SessionLocal()
    try:
        existing = db.query(IntegrationOutbox).filter(
            IntegrationOutbox.external_message_id == message_id
        ).first()
        if existing:
            return {
                "status": "accepted",
                "message_id": existing.external_message_id,
                "outbox_id": existing.id,
                "state": existing.status,
                "replayed": True,
            }

        outbox_event = IntegrationOutbox(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            external_message_id=message_id,
            payload_json=payload,
            status="pending",
        )
        db.add(outbox_event)
        db.commit()
        db.refresh(outbox_event)
        return {
            "status": "accepted",
            "message_id": outbox_event.external_message_id,
            "outbox_id": outbox_event.id,
            "state": outbox_event.status,
            "replayed": False,
        }
    finally:
        db.close()


def _resolve_depot_code(db: Session, depot: Depot) -> str:
    mapping = db.query(ExternalMapping).filter(
        ExternalMapping.system_name == "sage_x3",
        ExternalMapping.entity_type == "depot",
        ExternalMapping.internal_id == str(depot.id),
        ExternalMapping.is_active == True,
    ).first()
    return mapping.external_code if mapping else depot.name


@router.post("/deliveries")
def publish_logistics_delivery(payload: LogisticsDeliveryPayload):
    return _create_outbox_event(
        event_type="delivery",
        aggregate_type="delivery",
        aggregate_id=str(payload.reference.delivery_id) if payload.reference and payload.reference.delivery_id else payload.customer,
        message_id=payload.message_id,
        payload=payload.model_dump(mode="json"),
    )


@router.post("/stock-movements")
def publish_stock_movement(payload: StockMovementPayload):
    return _create_outbox_event(
        event_type="stock_movement",
        aggregate_type="stock_movement",
        aggregate_id=f"{payload.depot}:{payload.product}:{payload.movement_type}",
        message_id=payload.message_id,
        payload=payload.model_dump(mode="json"),
    )


@router.get("/inventory")
def get_inventory_snapshot(depot: Optional[str] = Query(default=None)):
    db: Session = SessionLocal()
    try:
        depots_query = db.query(Depot).filter(Depot.is_active == True)
        depots = depots_query.all()
        response = []
        for item in depots:
            depot_code = _resolve_depot_code(db, item)
            if depot and depot_code != depot and item.name != depot:
                continue

            response.append(
                {
                    "depot": depot_code,
                    "depot_name": item.name,
                    "inventory": [
                        {
                            "product": "GAZ_6KG",
                            "full_quantity": item.stock_6kg_plein,
                            "empty_quantity": item.stock_6kg_vide,
                        },
                        {
                            "product": "GAZ_12KG",
                            "full_quantity": item.stock_12kg_plein,
                            "empty_quantity": item.stock_12kg_vide,
                        },
                    ],
                    "updated_at": item.created_at.isoformat() if item.created_at else None,
                }
            )

        return {
            "count": len(response),
            "items": response,
            "generated_at": utc_now_iso(),
        }
    finally:
        db.close()


@router.get("/deliveries/{delivery_id}")
def get_logistics_delivery(delivery_id: int):
    db: Session = SessionLocal()
    try:
        delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")

        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        depot_code = _resolve_depot_code(db, depot) if depot else None

        return {
            "delivery_id": delivery.id,
            "depot": depot_code,
            "destination_name": delivery.destination_name,
            "driver_id": delivery.driver_id,
            "status": delivery.status.value,
            "scheduled_date": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
            "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
            "lines": [
                {
                    "product": "GAZ_6KG",
                    "quantity": delivery.quantity_6kg,
                    "empty_quantity": delivery.quantity_6kg_vide_recupere or 0,
                },
                {
                    "product": "GAZ_12KG",
                    "quantity": delivery.quantity_12kg,
                    "empty_quantity": delivery.quantity_12kg_vide_recupere or 0,
                },
            ],
        }
    finally:
        db.close()


@router.get("/integration-events")
def get_integration_events(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    db: Session = SessionLocal()
    try:
        query = db.query(IntegrationOutbox).order_by(IntegrationOutbox.created_at.desc())
        if status:
            query = query.filter(IntegrationOutbox.status == status)
        events = query.limit(limit).all()
        return [
            {
                "id": event.id,
                "event_type": event.event_type,
                "direction": event.direction,
                "system_name": event.system_name,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "message_id": event.external_message_id,
                "status": event.status,
                "retry_count": event.retry_count,
                "created_at": event.created_at.isoformat(),
                "sent_at": event.sent_at.isoformat() if event.sent_at else None,
            }
            for event in events
        ]
    finally:
        db.close()


# --- SAGE X3 INBOUND MISSIONS ---

@router.post("/sage-missions/inbound")
def receive_sage_mission_inbound(
    payload: SageMissionInbound,
    db: Session = Depends(get_db)
):
    """
    Endpoint pour recevoir les missions du cahier de charge Sage X3.
    
    Les missions arrivent avec statut 'pending_approval' et attendent validation admin.
    
    Authentification: Header 'X-Sage-X3-Token' validation (cf. config)
    """
    # Vérifier que le dépôt existe
    depot = db.query(Depot).filter(Depot.id == payload.depot_id).first()
    if not depot:
        raise HTTPException(
            status_code=404,
            detail=f"Dépôt introuvable (depot_id={payload.depot_id})"
        )
    
    # Vérifier pas de doublon basé sur external_delivery_id
    existing = db.query(Delivery).filter(
        Delivery.external_delivery_id == payload.external_delivery_id
    ).first()
    if existing:
        # Idempotence: retourner existant si même ID
        if existing.external_status == SageMissionStatusEnum.PENDING_APPROVAL:
            return {
                "success": True,
                "message": "Mission déjà reçue en attente d'approbation",
                "delivery_id": existing.id,
                "external_delivery_id": payload.external_delivery_id,
                "status": "pending_approval"
            }
    
    # Créer la mission locale
    mission = Delivery(
        depot_id=payload.depot_id,
        destination_name=payload.destination_name,
        destination_address=payload.destination_address,
        destination_latitude=payload.destination_latitude,
        destination_longitude=payload.destination_longitude,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        quantity_6kg=payload.quantity_6kg,
        quantity_12kg=payload.quantity_12kg,
        quantity=payload.quantity_6kg + payload.quantity_12kg,
        scheduled_date=payload.scheduled_date,
        notes=payload.notes,
        # Sage X3 tracking
        source_type="sage_inbound",
        external_delivery_id=payload.external_delivery_id,
        external_status=SageMissionStatusEnum.PENDING_APPROVAL,
        created_at=utc_now()
    )
    
    db.add(mission)
    db.commit()
    db.refresh(mission)
    
    # Event pour tracking
    outbox_event = IntegrationOutbox(
        event_type="mission_received",
        aggregate_type="delivery",
        aggregate_id=mission.id,
        payload_json={
            "delivery_id": mission.id,
            "external_delivery_id": payload.external_delivery_id,
            "destination_name": payload.destination_name,
            "depot_id": payload.depot_id
        },
        external_message_id=f"mission_received_{payload.external_delivery_id}_{utc_now_iso()}"
    )
    db.add(outbox_event)
    db.commit()
    
    return {
        "success": True,
        "message": f"Mission {payload.external_delivery_id} reçue avec succès",
        "delivery_id": mission.id,
        "external_delivery_id": payload.external_delivery_id,
        "status": "pending_approval"
    }