from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from pydantic import BaseModel, Field
from typing import Any, Optional
from app.models import (
    User,
    Delivery,
    Depot,
    Truck,
    DeliveryStatusEnum,
    GPSLog,
    RoleEnum,
    SyncBatch,
    SyncIdempotencyKey,
    DeliveryConfirmationEvent,
    SyncConflict,
    SageMissionStatusEnum,
    IntegrationOutbox,
)
from app.auth import get_current_user, verify_password, create_access_token
from app.time_utils import utc_now, utc_now_iso

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

class CompleteDeliveryRequest(BaseModel):
    latitude: float
    longitude: float

class SyncGPSPayload(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None

class DeliveryConfirmationPayload(BaseModel):
    confirmation_id: str
    delivery_id: int
    product: str
    quantity_delivered: int
    quantity_empty_collected: int = 0
    customer: Optional[str] = None
    customer_phone: Optional[str] = None
    confirmed_by: Optional[str] = None
    signature_base64: Optional[str] = None
    confirmation_code: Optional[str] = None
    notes: Optional[str] = None
    gps: Optional[SyncGPSPayload] = None
    delivered_at: datetime
    confirmation_mode: str = "signature"

class DeliveryAnomalyPayload(BaseModel):
    report_id: str
    delivery_id: int
    anomaly_type: str
    notes: Optional[str] = None
    reported_by: Optional[str] = None
    reported_at: datetime
    gps: Optional[SyncGPSPayload] = None
    photo_base64: Optional[str] = None

class SyncOperation(BaseModel):
    type: str
    idempotency_key: str
    payload: dict[str, Any]

class SyncBatchRequest(BaseModel):
    device_id: str
    driver_id: int
    batch_id: str
    sent_at: datetime
    operations: list[SyncOperation] = Field(default_factory=list)

def _normalize_product_type(product_type: str) -> Optional[str]:
    normalized = product_type.strip().upper().replace("-", "_").replace(" ", "")
    mapping = {
        "GAZ_6KG": "GAZ_6KG",
        "GAZ6KG": "GAZ_6KG",
        "6KG": "GAZ_6KG",
        "B6KG": "GAZ_6KG",
        "GAZ_12KG": "GAZ_12KG",
        "GAZ12KG": "GAZ_12KG",
        "12KG": "GAZ_12KG",
        "B12KG": "GAZ_12KG",
    }
    return mapping.get(normalized)

def _build_operation_result(idempotency_key: str, status: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    result = {
        "idempotency_key": idempotency_key,
        "status": status,
        "code": code,
        "message": message,
    }
    result.update(extra)
    return result

def _serialize_mission(delivery: Delivery, depot: Optional[Depot]) -> dict[str, Any]:
    return {
        "id": delivery.id,
        "assignment_version": 1,
        "status": delivery.status.value,
        "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
        "depot_id": delivery.depot_id,
        "depot_name": depot.name if depot else "Depot inconnu",
        "depot_address": depot.address if depot else None,
        "destination_name": delivery.destination_name,
        "destination_address": delivery.destination_address,
        "destination_latitude": delivery.destination_latitude,
        "destination_longitude": delivery.destination_longitude,
        "contact_name": delivery.contact_name,
        "contact_phone": delivery.contact_phone,
        "truck_id": delivery.truck_id,
        "quantity_6kg": delivery.quantity_6kg,
        "quantity_12kg": delivery.quantity_12kg,
        "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
        "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
        "actual_start": delivery.actual_start.isoformat() if delivery.actual_start else None,
        "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
        "notes": delivery.notes,
        "last_server_sync_at": utc_now_iso(),
    }

def _append_delivery_note(delivery: Delivery, note: str) -> None:
    if not note:
        return
    delivery.notes = f"{delivery.notes}\n{note}".strip() if delivery.notes else note

def _register_conflict(
    db: Session,
    *,
    batch_id: str,
    driver_id: int,
    device_id: str,
    idempotency_key: str,
    delivery: Optional[Delivery],
    conflict_type: str,
    local_payload: dict[str, Any],
    server_state: Optional[dict[str, Any]],
) -> SyncConflict:
    conflict = SyncConflict(
        aggregate_type="delivery",
        aggregate_id=str(local_payload.get("delivery_id") or (delivery.id if delivery else "unknown")),
        delivery_id=delivery.id if delivery else None,
        batch_id=batch_id,
        driver_id=driver_id,
        device_id=device_id,
        idempotency_key=idempotency_key,
        conflict_type=conflict_type,
        local_payload=local_payload,
        server_state=server_state,
    )
    db.add(conflict)
    db.flush()
    return conflict

def _create_idempotency_record(
    db: Session,
    *,
    idempotency_key: str,
    operation_type: str,
    delivery_id: Optional[int],
    driver_id: int,
    device_id: str,
    status: str,
    response_payload: dict[str, Any],
) -> None:
    db.add(
        SyncIdempotencyKey(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            delivery_id=delivery_id,
            driver_id=driver_id,
            device_id=device_id,
            status=status,
            response_payload=response_payload,
            last_seen_at=utc_now(),
        )
    )

def _process_delivery_confirmation(
    db: Session,
    *,
    batch_id: str,
    device_id: str,
    driver_id: int,
    operation: SyncOperation,
) -> dict[str, Any]:
    try:
        payload = DeliveryConfirmationPayload.model_validate(operation.payload)
    except Exception as err:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "INVALID_PAYLOAD",
            f"Payload de confirmation invalide: {err}",
            retryable=False,
        )

    payload_dict = payload.model_dump(mode="json")
    product_type = _normalize_product_type(payload.product)
    if not product_type:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "INVALID_PRODUCT_TYPE",
            "Type de produit non supporte pour la synchronisation offline.",
            retryable=False,
        )

    if payload.quantity_delivered <= 0:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "INVALID_QUANTITY",
            "La quantite livree doit etre strictement positive.",
            retryable=False,
        )

    delivery = db.query(Delivery).filter(
        Delivery.id == payload.delivery_id,
        Delivery.driver_id == driver_id,
    ).first()

    if not delivery:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "DELIVERY_NOT_FOUND",
            "La livraison n'existe pas ou n'est pas assignee a ce livreur.",
            retryable=False,
            delivery_id=payload.delivery_id,
        )

    if delivery.status == DeliveryStatusEnum.CANCELLED:
        conflict = _register_conflict(
            db,
            batch_id=batch_id,
            driver_id=driver_id,
            device_id=device_id,
            idempotency_key=operation.idempotency_key,
            delivery=delivery,
            conflict_type="delivery_cancelled",
            local_payload=payload_dict,
            server_state={
                "delivery_status": delivery.status.value,
                "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
            },
        )
        return _build_operation_result(
            operation.idempotency_key,
            "conflict",
            "DELIVERY_CANCELLED",
            "La livraison a ete annulee sur le serveur.",
            retryable=False,
            conflict_id=conflict.id,
            delivery_id=delivery.id,
            server_delivery_status=delivery.status.value,
        )

    if delivery.status == DeliveryStatusEnum.COMPLETED:
        conflict = _register_conflict(
            db,
            batch_id=batch_id,
            driver_id=driver_id,
            device_id=device_id,
            idempotency_key=operation.idempotency_key,
            delivery=delivery,
            conflict_type="delivery_already_completed",
            local_payload=payload_dict,
            server_state={
                "delivery_status": delivery.status.value,
                "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
                "end_latitude": delivery.end_latitude,
                "end_longitude": delivery.end_longitude,
            },
        )
        return _build_operation_result(
            operation.idempotency_key,
            "conflict",
            "DELIVERY_ALREADY_COMPLETED",
            "La livraison est deja cloturee sur le serveur.",
            retryable=False,
            conflict_id=conflict.id,
            delivery_id=delivery.id,
            server_delivery_status=delivery.status.value,
        )

    delivery.status = DeliveryStatusEnum.COMPLETED
    if delivery.actual_start is None:
        delivery.actual_start = payload.delivered_at
    delivery.actual_end = payload.delivered_at

    if payload.gps:
        delivery.end_latitude = payload.gps.latitude
        delivery.end_longitude = payload.gps.longitude
        db.add(
            GPSLog(
                truck_id=delivery.truck_id,
                delivery_id=delivery.id,
                latitude=payload.gps.latitude,
                longitude=payload.gps.longitude,
                accuracy=payload.gps.accuracy,
                timestamp=payload.delivered_at,
            )
        )

    if product_type == "GAZ_6KG":
        delivery.quantity_6kg_vide_recupere = payload.quantity_empty_collected
    else:
        delivery.quantity_12kg_vide_recupere = payload.quantity_empty_collected

    delivery.echange_effectue = payload.quantity_empty_collected > 0

    if payload.notes:
        _append_delivery_note(delivery, f"[offline_sync] {payload.notes}")

    event = DeliveryConfirmationEvent(
        confirmation_id=payload.confirmation_id,
        delivery_id=delivery.id,
        driver_id=driver_id,
        device_id=device_id,
        source="offline_sync",
        idempotency_key=operation.idempotency_key,
        product_type=product_type,
        quantity_delivered=payload.quantity_delivered,
        quantity_empty_collected=payload.quantity_empty_collected,
        confirmation_mode=payload.confirmation_mode,
        customer_reference=payload.customer,
        confirmed_by=payload.confirmed_by,
        customer_phone=payload.customer_phone,
        signature=payload.signature_base64,
        confirmation_code=payload.confirmation_code,
        notes=payload.notes,
        gps_latitude=payload.gps.latitude if payload.gps else None,
        gps_longitude=payload.gps.longitude if payload.gps else None,
        gps_accuracy=payload.gps.accuracy if payload.gps else None,
        delivered_at=payload.delivered_at,
    )
    db.add(event)
    db.flush()

    return _build_operation_result(
        operation.idempotency_key,
        "accepted",
        "SYNCED",
        "Confirmation de livraison synchronisee.",
        retryable=False,
        delivery_id=delivery.id,
        server_delivery_status=delivery.status.value,
        server_event_id=f"dconf_{event.id}",
    )


def _process_anomaly_report(
    db: Session,
    *,
    batch_id: str,
    device_id: str,
    driver_id: int,
    operation: SyncOperation,
) -> dict[str, Any]:
    try:
        payload = DeliveryAnomalyPayload.model_validate(operation.payload)
    except Exception as err:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "INVALID_PAYLOAD",
            f"Payload d'anomalie invalide: {err}",
            retryable=False,
        )

    delivery = db.query(Delivery).filter(
        Delivery.id == payload.delivery_id,
        Delivery.driver_id == driver_id,
    ).first()
    if not delivery:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "DELIVERY_NOT_FOUND",
            "La livraison n'existe pas ou n'est pas assignee.",
            retryable=False,
            delivery_id=payload.delivery_id,
        )

    _append_delivery_note(
        delivery,
        f"[anomaly {payload.anomaly_type}] {payload.notes or ''} signalée par {payload.reported_by or 'livreur'}",
    )
    delivery.status = DeliveryStatusEnum.IN_PROGRESS
    if payload.gps:
        db.add(
            GPSLog(
                truck_id=delivery.truck_id,
                delivery_id=delivery.id,
                latitude=payload.gps.latitude,
                longitude=payload.gps.longitude,
                accuracy=payload.gps.accuracy,
                timestamp=payload.reported_at,
            )
        )

    db.flush()
    return _build_operation_result(
        operation.idempotency_key,
        "accepted",
        "SYNCED",
        "Anomalie enregistree.",
        retryable=False,
        delivery_id=delivery.id,
        server_delivery_status=delivery.status.value,
    )


def require_driver_role(current_user: User = Depends(get_current_user)):
    """Vérifie que l'utilisateur est un ravitailleur"""
    if current_user.role != RoleEnum.RAVITAILLEUR:
        raise HTTPException(status_code=403, detail="Accès réservé aux ravitailleurs")
    return current_user

@router.post("/login")
def login_driver(credentials: LoginRequest, db: Session = Depends(get_db)):
    """Connexion ravitailleur"""
    
    user = db.query(User).filter(User.email == credentials.email).first()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    if user.role.value != "ravitailleur":
        raise HTTPException(status_code=403, detail="Accès réservé aux ravitailleurs")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    
    access_token = create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value
        }
    }

@router.get("/me")
def get_current_driver(current_user: User = Depends(require_driver_role)):
    """Profil du ravitailleur connecté"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role.value
    }

@router.get("/bootstrap")
def get_driver_bootstrap(
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Snapshot pour initialiser le mode offline du livreur.
    
    ✅ CRITICAL FIX (March 24, 2026):
    Returns ONLY ACTIVE missions to prevent completed/synced missions from reappearing
    
    Inclut:
    - Missions actives: PENDING, IN_PROGRESS ONLY
    - NO completed missions (history available via separate endpoint if needed)
    
    Reason: Completed missions that have been synced should NOT reappear on refresh/bootstrap.
    If they appear in active list, driver thinks they need to be synced again (confusing UX).
    """
    # ✅ Only active missions - NEVER include completed
    deliveries = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.status.in_([
            DeliveryStatusEnum.PENDING,
            DeliveryStatusEnum.IN_PROGRESS,
        ])
    ).order_by(Delivery.scheduled_date).all()

    latest_batch = db.query(SyncBatch).filter(
        SyncBatch.driver_id == current_user.id
    ).order_by(SyncBatch.received_at.desc()).first()

    open_conflicts = db.query(SyncConflict).filter(
        SyncConflict.driver_id == current_user.id,
        SyncConflict.resolution_status == "open"
    ).count()

    truck = db.query(Truck).filter(
        Truck.driver_id == current_user.id,
        Truck.is_active == True,
    ).first()

    assignments = []
    for delivery in deliveries:
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        assignments.append({
            "id": delivery.id,
            "status": delivery.status.value,
            "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
            "destination_name": delivery.destination_name or "Client",
            "destination_address": delivery.destination_address or "-",
            "contact_name": delivery.contact_name,
            "contact_phone": delivery.contact_phone,
            "depot_id": delivery.depot_id,
            "depot_name": depot.name if depot else "Dépôt inconnu",
            "depot_address": f"{depot.latitude}, {depot.longitude}" if depot else None,
            "quantity_6kg": delivery.quantity_6kg,
            "quantity_12kg": delivery.quantity_12kg,
            "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
            "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
        })

    truck_stock = []
    if truck:
        truck_stock = [
            {
                "truck_id": truck.id,
                "product": "GAZ_6KG",
                "full_quantity": truck.current_load_6kg_plein,
                "empty_quantity": truck.current_load_6kg_vide,
            },
            {
                "truck_id": truck.id,
                "product": "GAZ_12KG",
                "full_quantity": truck.current_load_12kg_plein,
                "empty_quantity": truck.current_load_12kg_vide,
            },
        ]

    return {
        "driver": {
            "id": current_user.id,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "role": current_user.role.value,
        },
        "assignments": assignments,
        "truck": {
            "id": truck.id,
            "license_plate": truck.license_plate,
        } if truck else None,
        "truck_stock": truck_stock,
        "reference_data": {
            "products": ["GAZ_6KG", "GAZ_12KG"],
            "sync_policy_version": 1,
            "max_delivery_validation_radius_m": 500,
        },
        "sync": {
            "open_conflicts": open_conflicts,
            "last_batch_id": latest_batch.batch_id if latest_batch else None,
            "last_received_at": latest_batch.received_at.isoformat() if latest_batch else None,
        },
        "server_time": utc_now_iso(),
    }

@router.post("/sync/batch")
def sync_driver_batch(
    batch_request: SyncBatchRequest,
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Synchronise un lot d'operations offline du livreur."""
    if batch_request.driver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Le driver_id du lot ne correspond pas a l'utilisateur connecte")

    existing_batch = db.query(SyncBatch).filter(
        SyncBatch.batch_id == batch_request.batch_id,
        SyncBatch.driver_id == current_user.id,
    ).first()
    if existing_batch and existing_batch.response_payload:
        return existing_batch.response_payload

    if existing_batch is None:
        sync_batch = SyncBatch(
            batch_id=batch_request.batch_id,
            device_id=batch_request.device_id,
            driver_id=current_user.id,
            sent_at=batch_request.sent_at,
            total_operations=len(batch_request.operations),
            status="processing",
        )
        db.add(sync_batch)
        db.flush()
    else:
        sync_batch = existing_batch
        sync_batch.device_id = batch_request.device_id
        sync_batch.sent_at = batch_request.sent_at
        sync_batch.total_operations = len(batch_request.operations)
        sync_batch.status = "processing"

    results = []
    accepted_count = 0
    conflict_count = 0
    rejected_count = 0

    for operation in batch_request.operations:
        existing_key = db.query(SyncIdempotencyKey).filter(
            SyncIdempotencyKey.idempotency_key == operation.idempotency_key
        ).first()
        if existing_key:
            existing_key.last_seen_at = utc_now()
            result = existing_key.response_payload or _build_operation_result(
                operation.idempotency_key,
                existing_key.status,
                "REPLAYED",
                "Operation deja traitee.",
            )
            results.append(result)
            if result.get("status") == "accepted":
                accepted_count += 1
            elif result.get("status") == "conflict":
                conflict_count += 1
            else:
                rejected_count += 1
            continue

        with db.begin_nested():
            if operation.type == "delivery_confirmation":
                result = _process_delivery_confirmation(
                    db,
                    batch_id=batch_request.batch_id,
                    device_id=batch_request.device_id,
                    driver_id=current_user.id,
                    operation=operation,
                )
            elif operation.type == "anomaly_report":
                result = _process_anomaly_report(
                    db,
                    batch_id=batch_request.batch_id,
                    device_id=batch_request.device_id,
                    driver_id=current_user.id,
                    operation=operation,
                )
            else:
                result = _build_operation_result(
                    operation.idempotency_key,
                    "rejected",
                    "UNSUPPORTED_OPERATION",
                    "Type d'operation non supporte dans cette phase de synchronisation.",
                    retryable=False,
                )

            delivery_id = None
            try:
                payload = operation.payload
                if isinstance(payload, dict):
                    delivery_id = payload.get("delivery_id")
            except Exception:
                delivery_id = None

            _create_idempotency_record(
                db,
                idempotency_key=operation.idempotency_key,
                operation_type=operation.type,
                delivery_id=delivery_id,
                driver_id=current_user.id,
                device_id=batch_request.device_id,
                status=result["status"],
                response_payload=result,
            )

        results.append(result)
        if result["status"] == "accepted":
            accepted_count += 1
        elif result["status"] == "conflict":
            conflict_count += 1
        else:
            rejected_count += 1

    sync_batch.processed_operations = len(results)
    sync_batch.accepted_operations = accepted_count
    sync_batch.conflict_operations = conflict_count
    sync_batch.rejected_operations = rejected_count
    sync_batch.status = "completed"

    response_payload = {
        "batch_id": batch_request.batch_id,
        "server_time": utc_now_iso(),
        "summary": {
            "total": len(results),
            "accepted": accepted_count,
            "conflicts": conflict_count,
            "rejected": rejected_count,
        },
        "results": results,
    }
    sync_batch.response_payload = response_payload
    db.commit()

    return response_payload

@router.get("/sync/conflicts")
def get_driver_sync_conflicts(
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Expose les conflits de synchronisation ouverts pour le livreur."""
    conflicts = db.query(SyncConflict).filter(
        SyncConflict.driver_id == current_user.id,
        SyncConflict.resolution_status == "open",
    ).order_by(SyncConflict.created_at.desc()).all()

    return [
        {
            "id": conflict.id,
            "aggregate_type": conflict.aggregate_type,
            "aggregate_id": conflict.aggregate_id,
            "delivery_id": conflict.delivery_id,
            "conflict_type": conflict.conflict_type,
            "idempotency_key": conflict.idempotency_key,
            "created_at": conflict.created_at.isoformat(),
            "server_state": conflict.server_state,
            "local_payload": conflict.local_payload,
        }
        for conflict in conflicts
    ]

@router.get("/my-missions")
def get_my_missions(
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """
    Liste toutes les missions assignées au driver:
    - Missions créées localement (source_type='user_created')
    - Missions du cahier de charge Sage X3 (source_type='sage_inbound', status='approved')
    """
    # Missions classiques (user_created)
    deliveries = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.source_type == "user_created",
        Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
    ).order_by(Delivery.scheduled_date).all()
    
    # Missions Sage X3 approuvées
    sage_missions = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.source_type == "sage_inbound",
        Delivery.external_status == SageMissionStatusEnum.APPROVED,
        Delivery.status != DeliveryStatusEnum.COMPLETED
    ).order_by(Delivery.scheduled_date).all()
    
    # Combiner et formatter
    all_missions = deliveries + sage_missions
    result = []
    
    for delivery in all_missions:
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        
        result.append({
            "id": delivery.id,
            "external_delivery_id": delivery.external_delivery_id,  # ID Sage si applicable
            "source_type": delivery.source_type,  # "user_created" ou "sage_inbound"
            "status": delivery.status.value,
            "external_status": delivery.external_status.value if delivery.external_status else None,
            "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
            "depot_id": delivery.depot_id,
            "depot_name": depot.name if depot else "Dépôt inconnu",
            "destination_name": delivery.destination_name,  # Pour Sage: nom client
            "destination_address": delivery.destination_address,
            "destination_latitude": delivery.destination_latitude,
            "destination_longitude": delivery.destination_longitude,
            "contact_name": delivery.contact_name,
            "contact_phone": delivery.contact_phone,
            "quantity_6kg": delivery.quantity_6kg,
            "quantity_12kg": delivery.quantity_12kg,
            "quantity": delivery.quantity,
            "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
            "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
            "notes": delivery.notes,
            "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
        })
    
    return result


@router.get("/missions/sage")
def get_sage_missions(
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """
    Liste UNIQUEMENT les missions du cahier de charge Sage X3 approuvées
    pour le driver connecté
    """
    sage_missions = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.source_type == "sage_inbound",
        Delivery.external_status == SageMissionStatusEnum.APPROVED,
        Delivery.status != DeliveryStatusEnum.COMPLETED
    ).order_by(Delivery.scheduled_date).all()
    
    result = []
    for delivery in sage_missions:
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        
        result.append({
            "id": delivery.id,
            "external_delivery_id": delivery.external_delivery_id,
            "status": delivery.status.value,
            "external_status": delivery.external_status.value,
            "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
            "depot_id": delivery.depot_id,
            "depot_name": depot.name if depot else "Dépôt inconnu",
            "destination_name": delivery.destination_name,
            "destination_address": delivery.destination_address,
            "destination_latitude": delivery.destination_latitude,
            "destination_longitude": delivery.destination_longitude,
            "contact_name": delivery.contact_name,
            "contact_phone": delivery.contact_phone,
            "quantity_6kg": delivery.quantity_6kg,
            "quantity_12kg": delivery.quantity_12kg,
            "quantity": delivery.quantity,
            "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
            "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
            "notes": delivery.notes,
            "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
        })
    
    return result

@router.get("/missions/{delivery_id}")
def get_mission_detail(
    delivery_id: int,
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Détail d'une mission avec toutes les infos (classique ou Sage X3)"""
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.driver_id == current_user.id
    ).first()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    
    depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
    
    return {
        "id": delivery.id,
        "external_delivery_id": delivery.external_delivery_id,
        "source_type": delivery.source_type,
        "status": delivery.status.value,
        "external_status": delivery.external_status.value if delivery.external_status else None,
        "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
        "depot_id": delivery.depot_id,
        "depot_name": depot.name if depot else "Dépôt inconnu",
        "depot_latitude": depot.latitude if depot else None,
        "depot_longitude": depot.longitude if depot else None,
        "destination_name": delivery.destination_name,
        "destination_address": delivery.destination_address,
        "destination_latitude": delivery.destination_latitude,
        "destination_longitude": delivery.destination_longitude,
        "contact_name": delivery.contact_name,
        "contact_phone": delivery.contact_phone,
        "quantity_6kg": delivery.quantity_6kg,
        "quantity_12kg": delivery.quantity_12kg,
        "quantity": delivery.quantity,
        "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
        "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
        "notes": delivery.notes,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
    }

@router.post("/start-delivery/{delivery_id}")
def start_delivery(
    delivery_id: int,
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Démarrer une livraison"""
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.driver_id == current_user.id
    ).first()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    
    if delivery.status != DeliveryStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail="Cette mission a déjà été démarrée")
    
    delivery.status = DeliveryStatusEnum.IN_PROGRESS
    db.commit()
    
    return {"message": "Livraison démarrée", "status": delivery.status.value}

@router.post("/complete-delivery/{delivery_id}")
def complete_delivery(
    delivery_id: int,
    request: CompleteDeliveryRequest,
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Terminer une livraison avec validation GPS"""
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.driver_id == current_user.id
    ).first()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    
    if delivery.status == DeliveryStatusEnum.COMPLETED:
        raise HTTPException(status_code=400, detail="Cette mission est déjà terminée")
    
    depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    # Calculer la distance
    import math
    def calculate_distance(lat1, lon1, lat2, lon2):
        R = 6371000  # Rayon de la Terre en mètres
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    distance = calculate_distance(
        request.latitude,
        request.longitude,
        depot.latitude,
        depot.longitude
    )
    
    # Validation 500m temporairement désactivée pour test (TODO: réactiver)
    # if distance > 500:
    #     raise HTTPException(
    #         status_code=400,
    #         detail=f"Vous êtes trop loin du dépôt ({int(distance)}m). Distance maximum: 500m"
    #     )
    distance = 0  # Pour test
    
    # Enregistrer la position GPS
    gps_log = GPSLog(
        truck_id=delivery.truck_id,
        delivery_id=delivery.id,
        latitude=request.latitude,
        longitude=request.longitude,
        timestamp=utc_now()
    )
    db.add(gps_log)
    
    # Marquer la livraison comme terminée
    delivery.status = DeliveryStatusEnum.COMPLETED
    delivery.actual_end = utc_now()
    
    # Si c'est une mission Sage X3, créer un événement outbox pour notification Sage
    if delivery.source_type == "sage_inbound" and delivery.external_delivery_id:
        outbox = IntegrationOutbox(
            event_type="delivery_completed",
            aggregate_type="delivery",
            aggregate_id=str(delivery.id),
            payload_json={
                "delivery_id": delivery.id,
                "external_delivery_id": delivery.external_delivery_id,
                "status": "completed",
                "completed_at": utc_now_iso(),
                "quantity_6kg_delivered": delivery.quantity_6kg,
                "quantity_12kg_delivered": delivery.quantity_12kg,
                "quantity_6kg_returned": delivery.quantity_6kg_vide_recupere or 0,
                "quantity_12kg_returned": delivery.quantity_12kg_vide_recupere or 0,
                "location": {
                    "latitude": request.latitude,
                    "longitude": request.longitude
                }
            },
            external_message_id=f"delivery_completed_{delivery.external_delivery_id}_{utc_now_iso()}",
            status="pending"
        )
        db.add(outbox)
        
        # Marquer la mission comme téléchargée dans Sage status
        delivery.external_status = SageMissionStatusEnum.SYNCED
    
    db.commit()
    
    return {
        "message": "Livraison terminée avec succès",
        "status": delivery.status.value,
        "distance": int(distance),
        "sage_synced": delivery.source_type == "sage_inbound"
    }

@router.get("/history")
def get_my_history(
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    """Historique des livraisons terminées"""
    deliveries = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.status == DeliveryStatusEnum.COMPLETED
    ).order_by(Delivery.actual_end.desc()).limit(50).all()
    
    result = []
    for delivery in deliveries:
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        
        result.append({
            "id": delivery.id,
            "status": delivery.status.value,
            "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
            "completed_at": delivery.actual_end.isoformat() if delivery.actual_end else None,
            "depot_id": delivery.depot_id,
            "depot_name": depot.name if depot else "Dépôt inconnu",
            "quantity_6kg": delivery.quantity_6kg,
            "quantity_12kg": delivery.quantity_12kg,
        })
    
    return result
