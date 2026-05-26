from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime, date, timedelta
from typing import Optional
from pydantic import BaseModel, Field
import io
import csv
import math
import logging
logger = logging.getLogger(__name__)

from app.database import get_db
from app.models import User, Depot, Truck, Delivery, GPSLog, Stock, RoleEnum, DeliveryStatusEnum, SyncConflict, IntegrationOutbox, IntegrationHealthCheck, SageMissionStatusEnum, DriverMapping, DriverMappingStatusEnum, DeliveryConfirmationEvent, SyncBatch
from app.schemas import (
    DepotCreate, DepotUpdate, DepotResponse,
    TruckCreate, TruckResponse,
    DriverMappingCreate, DriverMappingResponse,
    DeliveryCreate, DeliveryUpdate, DeliveryResponse,
    GPSLogResponse, UserResponse, SageMissionResponse, SageMissionApprovalResponse,
    SageSqlSyncScheduleResponse, SageSqlSyncScheduleUpdate
)
from app.auth import require_role, hash_password
from app.services.outbox_worker import check_sage_x3_health, process_pending_outbox_events
from app.services.sage_sql_service import check_sage_sql_connection, get_sage_sql_connection, corriger_livraison_sage
from app.services.sage_sync_scheduler import (
    calculate_next_run_time,
    get_sage_sql_daily_sync_config,
    update_sage_sql_daily_sync_config,
)
from app.time_utils import utc_now, utc_now_iso
from app.websocket_manager import manager
from app.config import settings
from import_locator_csv import import_depots_csv_text

router = APIRouter(prefix="/api/admin", tags=["admin"])

class DeliveryCorrectionPayload(BaseModel):
    quantity_6kg: int = Field(..., ge=0, description="Nouvelle quantité de 6kg")
    quantity_12kg: int = Field(..., ge=0, description="Nouvelle quantité de 12kg")
    comment: Optional[str] = Field(None, description="Commentaire de rectification par le logisticien")


def _resolve_driver_mapping_status(is_active: bool, explicit_status: Optional[str] = None) -> DriverMappingStatusEnum:
    normalized = (explicit_status or "").strip().lower()
    if normalized == DriverMappingStatusEnum.PENDING_APPROVAL.value:
        return DriverMappingStatusEnum.PENDING_APPROVAL
    if normalized == DriverMappingStatusEnum.INACTIVE.value:
        return DriverMappingStatusEnum.INACTIVE
    if normalized == DriverMappingStatusEnum.ACTIVE.value:
        return DriverMappingStatusEnum.ACTIVE
    return DriverMappingStatusEnum.ACTIVE if is_active else DriverMappingStatusEnum.INACTIVE

# --- DÉPÔTS ---

@router.get("/depots", response_model=list[DepotResponse])
def get_all_depots(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    depots = db.query(Depot).filter(Depot.is_active == True).all()
    return [DepotResponse.from_orm(d) for d in depots]

@router.post("/depots", response_model=DepotResponse)
def create_depot(depot_data: DepotCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    # Vérifier si le nom existe
    existing = db.query(Depot).filter(Depot.name == depot_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Dépôt déjà existant")
    
    cap_6kg = depot_data.capacity_6kg
    cap_12kg = depot_data.capacity_12kg
    if cap_6kg is None and cap_12kg is None and depot_data.capacity is not None:
        # fallback simple: half/half
        half = int(depot_data.capacity / 2)
        cap_6kg = half
        cap_12kg = half

    if cap_6kg is None:
        cap_6kg = 0
    if cap_12kg is None:
        cap_12kg = 0

    new_depot = Depot(
        name=depot_data.name,
        latitude=depot_data.latitude,
        longitude=depot_data.longitude,
        capacity_6kg=cap_6kg,
        capacity_12kg=cap_12kg,
        address=depot_data.address,
        city=depot_data.city,
        quartier=depot_data.quartier,
        plv_code=depot_data.plv_code,
        maps_url=depot_data.maps_url,
        phone=depot_data.phone,
        manager_id=depot_data.manager_id,
        site_code=depot_data.site_code
    )
    db.add(new_depot)
    db.commit()
    db.refresh(new_depot)
    
    return DepotResponse.from_orm(new_depot)

@router.put("/depots/{depot_id}", response_model=DepotResponse)
def update_depot(depot_id: int, depot_data: DepotUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    if depot_data.name:
        depot.name = depot_data.name
    if depot_data.latitude is not None:
        depot.latitude = depot_data.latitude
    if depot_data.longitude is not None:
        depot.longitude = depot_data.longitude
    if depot_data.capacity_6kg is not None:
        depot.capacity_6kg = depot_data.capacity_6kg
    if depot_data.capacity_12kg is not None:
        depot.capacity_12kg = depot_data.capacity_12kg
    if depot_data.city:
        depot.city = depot_data.city
    if depot_data.quartier is not None:
        depot.quartier = depot_data.quartier
    if depot_data.address:
        depot.address = depot_data.address
    if depot_data.plv_code is not None:
        depot.plv_code = depot_data.plv_code
    if depot_data.maps_url is not None:
        depot.maps_url = depot_data.maps_url
    if depot_data.phone:
        depot.phone = depot_data.phone
    if depot_data.site_code is not None:
        depot.site_code = depot_data.site_code

    db.commit()
    db.refresh(depot)
    return DepotResponse.from_orm(depot)


@router.post("/depots/import-csv")
async def import_depots_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    filename = (file.filename or '').lower()
    if not filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Veuillez importer un fichier CSV.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier CSV est vide.")

    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('latin-1')

    try:
        created, updated, skipped, detected_format = import_depots_csv_text(text)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Import CSV impossible: {exc}",
        ) from exc

    return {
        "message": "Import terminé",
        "format": detected_format,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "filename": file.filename,
    }


class DepotManagerUpdate(BaseModel):
    """Payload pour mise à jour du gestionnaire d'un dépôt.

    Tous les champs sont optionnels afin de permettre des mises à jour partielles
    (email seul, nom seul, mot de passe seul).
    """

    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None


@router.get("/depots/{depot_id}/manager", response_model=UserResponse)
def get_depot_manager(
    depot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Récupérer l'utilisateur gestionnaire associé à un dépôt."""
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot or not depot.manager_id:
        raise HTTPException(status_code=404, detail="Gestionnaire introuvable pour ce dépôt")

    user = db.query(User).filter(User.id == depot.manager_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Gestionnaire introuvable")

    return UserResponse.from_orm(user)


@router.put("/depots/{depot_id}/manager", response_model=UserResponse)
def update_depot_manager(
    depot_id: int,
    data: DepotManagerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Mettre à jour les infos du gestionnaire (email, nom, mot de passe)."""
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot or not depot.manager_id:
        raise HTTPException(status_code=404, detail="Dépôt ou gestionnaire introuvable")

    user = db.query(User).filter(User.id == depot.manager_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Gestionnaire introuvable")

    # Mettre à jour l'email si fourni (et non utilisé par un autre user)
    if data.email:
        existing = db.query(User).filter(User.email == data.email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
        user.email = data.email

    # Mettre à jour le nom complet si fourni
    if data.full_name:
        user.full_name = data.full_name

    # Mettre à jour le mot de passe si fourni
    if data.password:
        user.hashed_password = hash_password(data.password)

    db.commit()
    db.refresh(user)

    return UserResponse.from_orm(user)


@router.get("/integration/sage-schedule", response_model=SageSqlSyncScheduleResponse)
def get_sage_sql_schedule(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    config = get_sage_sql_daily_sync_config(db)
    next_run = calculate_next_run_time(config.run_time) if config.enabled else None
    return SageSqlSyncScheduleResponse(
        enabled=config.enabled,
        run_time=config.run_time,
        next_run_at=next_run,
        description=config.description,
    )


@router.get("/integration/sage-sql-health")
def get_sage_sql_health(
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    return check_sage_sql_connection()


@router.get("/integration/sage-schedule-status")
def get_sage_schedule_status(
    request: Request,
    db: Session = Depends(get_db),
):
    from app.services.sage_sync_scheduler import SAGE_SQL_SYNC_STATUS
    config = get_sage_sql_daily_sync_config(db)
    
    task = getattr(request.app.state, "sage_sql_sync_task", None)
    task_status = "unknown"
    if task is None:
        task_status = "not_started"
    elif task.cancelled():
        task_status = "cancelled"
    elif task.done():
        exception = task.exception() if not task.cancelled() else None
        task_status = f"done_with_error: {exception}" if exception else "done"
    else:
        task_status = "running"
        
    now = datetime.now()
    utcnow = datetime.utcnow()
    
    next_run = calculate_next_run_time(config.run_time) if config.enabled else None
    
    return {
        "status": "ok",
        "task_status": task_status,
        "config": {
            "enabled": config.enabled,
            "run_time": config.run_time,
            "description": config.description,
        },
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "utc_time": utcnow.strftime("%Y-%m-%d %H:%M:%S"),
        "next_run_at": next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else None,
        "sync_execution_status": SAGE_SQL_SYNC_STATUS
    }


@router.put("/integration/sage-schedule", response_model=SageSqlSyncScheduleResponse)
def update_sage_sql_schedule(
    schedule_data: SageSqlSyncScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    if schedule_data.run_time is None and schedule_data.enabled is None:
        raise HTTPException(status_code=400, detail="Au moins un champ doit être fourni")

    config = update_sage_sql_daily_sync_config(
        db,
        run_time=schedule_data.run_time,
        enabled=schedule_data.enabled,
    )
    next_run = calculate_next_run_time(config.run_time) if config.enabled else None
    return SageSqlSyncScheduleResponse(
        enabled=config.enabled,
        run_time=config.run_time,
        next_run_at=next_run,
        description=config.description,
    )


# --- SUPPRESSION DÉPÔT ---
@router.delete("/depots/delete/{depot_id}", status_code=204)
def delete_depot(depot_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    db.delete(depot)
    db.commit()
    return None

# --- CAMIONS ---

@router.get("/trucks", response_model=list[TruckResponse])
def get_all_trucks(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    trucks = db.query(Truck).filter(Truck.is_active == True).all()
    return [TruckResponse.from_orm(t) for t in trucks]

@router.post("/trucks", response_model=TruckResponse)
def create_truck(truck_data: TruckCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    # Vérifier si le chauffeur existe
    driver = db.query(User).filter(User.id == truck_data.driver_id, User.role == RoleEnum.RAVITAILLEUR).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Chauffeur introuvable")
    
    # Vérifier si la plaque existe
    existing = db.query(Truck).filter(Truck.license_plate == truck_data.license_plate).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plaque immatriculation déjà existante")
    
    new_truck = Truck(
        license_plate=truck_data.license_plate,
        driver_id=truck_data.driver_id,
        capacity_6kg=truck_data.capacity_6kg,
        capacity_12kg=truck_data.capacity_12kg
    )
    db.add(new_truck)
    db.commit()
    db.refresh(new_truck)
    return TruckResponse.from_orm(new_truck)


@router.get("/driver-mappings", response_model=list[DriverMappingResponse])
def get_driver_mappings(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    mappings = db.query(DriverMapping).order_by(DriverMapping.updated_at.desc()).all()
    return [DriverMappingResponse.from_orm(item) for item in mappings]


@router.post("/driver-mappings", response_model=DriverMappingResponse)
def upsert_driver_mapping(mapping_data: DriverMappingCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    user = db.query(User).filter(
        User.id == mapping_data.user_id,
        User.role == RoleEnum.RAVITAILLEUR,
        User.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Livreur introuvable pour ce mapping")

    resolved_status = _resolve_driver_mapping_status(mapping_data.is_active, mapping_data.status)
    mapping = db.query(DriverMapping).filter(
        func.upper(DriverMapping.sage_driver_code) == mapping_data.sage_driver_code.strip().upper(),
        func.upper(DriverMapping.truck_code) == mapping_data.truck_code.strip().upper(),
    ).first()

    if mapping is None:
        mapping = DriverMapping(
            user_id=mapping_data.user_id,
            sage_driver_code=mapping_data.sage_driver_code.strip().upper(),
            truck_code=mapping_data.truck_code.strip().upper(),
            is_active=resolved_status == DriverMappingStatusEnum.ACTIVE,
            status=resolved_status,
            auto_created=False,
        )
        db.add(mapping)
    else:
        mapping.user_id = mapping_data.user_id
        mapping.sage_driver_code = mapping_data.sage_driver_code.strip().upper()
        mapping.truck_code = mapping_data.truck_code.strip().upper()
        mapping.is_active = resolved_status == DriverMappingStatusEnum.ACTIVE
        mapping.status = resolved_status

        if resolved_status != DriverMappingStatusEnum.PENDING_APPROVAL:
            mapping.auto_created = False

    db.commit()
    db.refresh(mapping)
    return DriverMappingResponse.from_orm(mapping)


@router.post("/driver-mappings/{mapping_id}/approve", response_model=DriverMappingResponse)
def approve_driver_mapping(mapping_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    mapping = db.query(DriverMapping).filter(DriverMapping.id == mapping_id).first()
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping introuvable")

    mapping.status = DriverMappingStatusEnum.ACTIVE
    mapping.is_active = True
    db.commit()
    db.refresh(mapping)
    return DriverMappingResponse.from_orm(mapping)

# --- LIVRAISONS ---
@router.delete("/deliveries/clear", status_code=204)
def clear_all_deliveries(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    db.query(Delivery).delete()
    db.commit()
    return None

@router.get("/deliveries")
def get_all_deliveries(
    status: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    query = db.query(Delivery)
    # Si un statut est fourni, le convertir en enum pour filtrer correctement
    if status:
        try:
            status_enum = DeliveryStatusEnum(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Statut de livraison invalide")
        query = query.filter(Delivery.status == status_enum)
    deliveries = query.all()
    
    # Enrichir avec truck et depot
    result = []
    for d in deliveries:
        delivery_dict = {
            "id": d.id,
            "truck_id": d.truck_id,
            "depot_id": d.depot_id,
            "destination_name": d.destination_name,
            "destination_address": d.destination_address,
            "destination_latitude": d.destination_latitude,
            "destination_longitude": d.destination_longitude,
            "contact_name": d.contact_name,
            "contact_phone": d.contact_phone,
            "driver_id": d.driver_id,
            "quantity_6kg": d.quantity_6kg,
            "quantity_12kg": d.quantity_12kg,
            "echange_effectue": d.echange_effectue,
            "quantity_6kg_vide_recupere": d.quantity_6kg_vide_recupere,
            "quantity_12kg_vide_recupere": d.quantity_12kg_vide_recupere,
            "status": d.status,
            "scheduled_date": d.scheduled_date,
            "actual_start": d.actual_start,
            "actual_end": d.actual_end,
            "start_latitude": d.start_latitude,
            "start_longitude": d.start_longitude,
            "end_latitude": d.end_latitude,
            "end_longitude": d.end_longitude,
            "notes": d.notes,
            "created_at": d.created_at,
            "truck": {
                "id": d.truck.id,
                "plate_number": d.truck.license_plate,
                "driver": {"full_name": d.truck.driver.full_name} if d.truck.driver else None
            } if d.truck else None,
            "depot": {
                "id": d.depot.id,
                "name": d.depot.name,
                "city": d.depot.city,
                "quartier": d.depot.quartier,
                "plv_code": d.depot.plv_code,
                "maps_url": d.depot.maps_url,
            } if d.depot else None
        }
        result.append(delivery_dict)
    
    return result


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Distance in meters between two points
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@router.get("/deliveries/{delivery_id}/details")
def get_delivery_details(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")

    events = db.query(DeliveryConfirmationEvent).filter(DeliveryConfirmationEvent.delivery_id == delivery_id).order_by(DeliveryConfirmationEvent.delivered_at.desc()).all()
    signature_event = None
    if events:
        signature_event = events[0]

    gps_logs = db.query(GPSLog).filter(GPSLog.delivery_id == delivery_id).order_by(GPSLog.timestamp.asc()).all()
    total_distance = 0.0
    if len(gps_logs) > 1:
        for i in range(1, len(gps_logs)):
            prev = gps_logs[i - 1]
            curr = gps_logs[i]
            total_distance += _haversine_distance(prev.latitude, prev.longitude, curr.latitude, curr.longitude)

    if delivery.start_latitude is not None and delivery.start_longitude is not None and delivery.end_latitude is not None and delivery.end_longitude is not None:
        linear_distance = _haversine_distance(delivery.start_latitude, delivery.start_longitude, delivery.end_latitude, delivery.end_longitude)
    else:
        linear_distance = None

    duration_seconds = None
    if delivery.actual_start and delivery.actual_end:
        duration_seconds = (delivery.actual_end - delivery.actual_start).total_seconds()

    last_sync = db.query(SyncBatch).filter(SyncBatch.driver_id == delivery.driver_id).order_by(SyncBatch.received_at.desc()).first()

    return {
        "delivery_id": delivery.id,
        "status": delivery.status,
        "quantity_6kg": delivery.quantity_6kg,
        "quantity_12kg": delivery.quantity_12kg,
        "scheduled_date": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
        "actual_start": delivery.actual_start.isoformat() if delivery.actual_start else None,
        "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
        "duration_seconds": duration_seconds,
        "distance_linear_m": linear_distance,
        "distance_path_m": total_distance,
        "signature": {
            "confirmation_id": signature_event.confirmation_id if signature_event else None,
            "driver_id": signature_event.driver_id if signature_event else None,
            "delivered_at": signature_event.delivered_at.isoformat() if signature_event else None,
            "signature_base64": signature_event.signature if signature_event else None,
            "confirmation_mode": signature_event.confirmation_mode if signature_event else None,
            "gps_latitude": signature_event.gps_latitude if signature_event else None,
            "gps_longitude": signature_event.gps_longitude if signature_event else None,
        } if signature_event else None,
        "gps_logs": [
            {
                "timestamp": log.timestamp.isoformat(),
                "latitude": log.latitude,
                "longitude": log.longitude,
                "accuracy": log.accuracy,
            }
            for log in gps_logs
        ],
        "last_sync_batch": {
            "batch_id": last_sync.batch_id,
            "device_id": last_sync.device_id,
            "received_at": last_sync.received_at.isoformat() if last_sync.received_at else None,
            "status": last_sync.status,
            "total_operations": last_sync.total_operations,
            "accepted_operations": last_sync.accepted_operations,
            "conflict_operations": last_sync.conflict_operations,
            "rejected_operations": last_sync.rejected_operations,
        } if last_sync else None,
    }


@router.post("/deliveries", response_model=DeliveryResponse)
async def create_delivery(
    delivery_data: DeliveryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    # Vérifications
    truck = db.query(Truck).filter(Truck.id == delivery_data.truck_id).first()
    depot = db.query(Depot).filter(Depot.id == delivery_data.depot_id).first()
    
    if not truck:
        raise HTTPException(status_code=404, detail="Camion introuvable")
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    # Récupérer le chauffeur du camion automatiquement
    driver_id = truck.driver_id
    if driver_id is None:
        raise HTTPException(status_code=400, detail="Le camion sélectionné n'est pas affecté à un ravitailleur. Assignez un chauffeur avant de créer la mission.")

    new_delivery = Delivery(
        truck_id=delivery_data.truck_id,
        depot_id=delivery_data.depot_id,
        destination_name=delivery_data.destination_name,
        destination_address=delivery_data.destination_address,
        destination_latitude=delivery_data.destination_latitude,
        destination_longitude=delivery_data.destination_longitude,
        contact_name=delivery_data.contact_name,
        contact_phone=delivery_data.contact_phone,
        driver_id=driver_id,
        quantity_6kg=delivery_data.quantity_6kg,
        quantity_12kg=delivery_data.quantity_12kg,
        quantity=delivery_data.quantity_6kg + delivery_data.quantity_12kg,
        scheduled_date=delivery_data.scheduled_date,
        notes=delivery_data.notes,
        status=DeliveryStatusEnum.PENDING
    )
    db.add(new_delivery)
    db.commit()
    db.refresh(new_delivery)
    
    # Broadcast
    await manager.broadcast_to_all({
        "type": "delivery_created",
        "delivery_id": new_delivery.id,
        "truck_id": new_delivery.truck_id,
        "driver_id": new_delivery.driver_id
    })
    
    return DeliveryResponse.from_orm(new_delivery)

@router.get("/deliveries/{delivery_id}/debug")
def debug_delivery_assignment(delivery_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    try:
        delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not delivery:
            raise HTTPException(status_code=404, detail="Livraison introuvable")
        truck = db.query(Truck).filter(Truck.id == delivery.truck_id).first() if delivery.truck_id else None
        driver = db.query(User).filter(User.id == delivery.driver_id).first() if delivery.driver_id else None
        return {
            "delivery_id": delivery.id,
            "status": delivery.status.value,
            "driver_id": delivery.driver_id,
            "driver_email": driver.email if driver else None,
            "truck_id": delivery.truck_id,
            "truck_driver_id": truck.driver_id if truck else None,
            "truck_license_plate": truck.license_plate if truck else None,
            "scheduled_date": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
            "depot_id": delivery.depot_id,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"debug error: {type(e).__name__}: {e}")

@router.put("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_delivery(
    delivery_id: int,
    delivery_data: DeliveryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")
    
    if delivery_data.status:
        delivery.status = delivery_data.status
    if delivery_data.actual_start:
        delivery.actual_start = delivery_data.actual_start
    if delivery_data.actual_end:
        delivery.actual_end = delivery_data.actual_end
    
    db.commit()
    db.refresh(delivery)
    
    # Broadcast changement
    await manager.broadcast_to_all({
        "type": "delivery_updated",
        "delivery_id": delivery.id,
        "status": delivery.status
    })
    
    return DeliveryResponse.from_orm(delivery)


@router.post("/deliveries/{delivery_id}/correct", response_model=DeliveryResponse)
async def correct_delivery_quantities(
    delivery_id: int,
    payload: DeliveryCorrectionPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN, RoleEnum.RAVITAILLEUR))
):
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")

    # Stocker les anciennes valeurs pour le commentaire d'historique
    old_6kg = delivery.quantity_6kg or 0
    old_12kg = delivery.quantity_12kg or 0
    
    # Mettre à jour les quantités locales de la livraison
    delivery.quantity_6kg = payload.quantity_6kg
    delivery.quantity_12kg = payload.quantity_12kg
    
    # Mettre à jour les quantités livrées/collectées globales
    confirmed_quantity = payload.quantity_6kg + payload.quantity_12kg
    if delivery.program_type == "COLLECTION":
        delivery.collected_quantity_total = confirmed_quantity
        delivery.delivered_quantity_total = 0
    else:
        delivery.delivered_quantity_total = confirmed_quantity
        delivery.collected_quantity_total = 0

    # Mettre à jour les lignes de programme associées
    if delivery.program_line:
        if delivery.program_line.product_code == "GAZ_6KG":
            delivery.program_line.quantity_delivered = payload.quantity_6kg if delivery.program_type == "DELIVERY" else 0
            delivery.program_line.quantity_collected = payload.quantity_6kg if delivery.program_type == "COLLECTION" else 0
        else:
            delivery.program_line.quantity_delivered = payload.quantity_12kg if delivery.program_type == "DELIVERY" else 0
            delivery.program_line.quantity_collected = payload.quantity_12kg if delivery.program_type == "COLLECTION" else 0

    # Ajouter le commentaire de rectification dédié
    rectification_tag = f"[RECTIFICATION LOGISTIQUE] Rectifié par {current_user.username} le {datetime.now().strftime('%d/%m/%Y %H:%M')}. "
    rectification_details = f"Anciennes Qtes: 6kg={old_6kg}, 12kg={old_12kg} -> Nouvelles Qtes: 6kg={payload.quantity_6kg}, 12kg={payload.quantity_12kg}. "
    user_note = f"Commentaire: {payload.comment}" if payload.comment else "Aucun commentaire supplémentaire."
    
    full_rectification_note = f"{rectification_tag}{rectification_details}{user_note}"
    
    if delivery.notes:
        delivery.notes = f"{delivery.notes}\n\n{full_rectification_note}"
    else:
        delivery.notes = full_rectification_note

    # Enregistrer la modification en base de données
    db.commit()
    db.refresh(delivery)

    # Si c'est un programme connecté à Sage X3, propager la rectification sur Sage X3!
    if delivery.program and delivery.program.source_system == "sage_x3" and delivery.program.program_code:
        client_code = delivery.program_line.client_code if delivery.program_line else ""
        if client_code:
            logger.info(f"[RECTIFICATION SAGE] Écriture des corrections sur Sage: {delivery.program.program_code}/{client_code}")
            sage_result = corriger_livraison_sage(
                num_programme=delivery.program.program_code,
                client_code=client_code,
                qty_6kg=payload.quantity_6kg,
                qty_12kg=payload.quantity_12kg,
                notes=delivery.notes,
                product_code=delivery.program_line.product_code if delivery.program_line else None,
            )
            if sage_result["status"] != "OK":
                logger.error(f"[RECTIFICATION SAGE] ❌ Échec écriture Sage: {sage_result['detail']}")
            else:
                logger.info(f"[RECTIFICATION SAGE] ✅ Écriture Sage réussie.")

    # Diffuser la mise à jour via WebSocket
    await manager.broadcast_to_all({
        "type": "delivery_updated",
        "delivery_id": delivery.id,
        "status": delivery.status,
        "quantity_6kg": delivery.quantity_6kg,
        "quantity_12kg": delivery.quantity_12kg,
        "notes": delivery.notes
    })

    return DeliveryResponse.from_orm(delivery)


@router.get("/stats/deliveries-by-truck")
def get_deliveries_by_truck(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Statistiques simples : nombre de livraisons par camion.

    Retourne une liste de {"truck": "PLAQUE", "deliveries": nombre} pour alimenter
    le graphe de la page Rapport global.
    """
    rows = (
        db.query(Truck.license_plate, func.count(Delivery.id))
        .join(Delivery, Delivery.truck_id == Truck.id)
        .group_by(Truck.id, Truck.license_plate)
        .all()
    )
    return [
        {"truck": license_plate, "deliveries": int(count)}
        for (license_plate, count) in rows
    ]

# --- DASHBOARD ---

@router.get("/dashboard/overview")
def get_dashboard_overview(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    total_depots = db.query(func.count(Depot.id)).scalar()
    active_trucks = db.query(func.count(Truck.id)).filter(Truck.is_active == True).scalar()
    in_progress_deliveries = db.query(func.count(Delivery.id)).filter(Delivery.status == DeliveryStatusEnum.IN_PROGRESS).scalar()
    
    # Zones en tension - calcul avec bouteilles 6kg et 12kg
    low_stock_depots = db.query(Depot).filter(
        or_(
            Depot.stock_6kg_plein < (Depot.capacity_6kg * 0.2),
            Depot.stock_12kg_plein < (Depot.capacity_12kg * 0.2)
        )
    ).all()
    
    # Calculer totaux de stock
    total_stock_6kg = db.query(func.sum(Depot.stock_6kg_plein)).scalar() or 0
    total_stock_12kg = db.query(func.sum(Depot.stock_12kg_plein)).scalar() or 0
    
    return {
        "total_depots": total_depots,
        "active_trucks": active_trucks,
        "in_progress_deliveries": in_progress_deliveries,
        "low_stock_depots": len(low_stock_depots),
        "total_stock_6kg": int(total_stock_6kg),
        "total_stock_12kg": int(total_stock_12kg),
        "critical_areas": [
            {
                "depot_id": d.id, 
                "name": d.name,
                "stock_6kg_plein": d.stock_6kg_plein,
                "stock_12kg_plein": d.stock_12kg_plein,
                "capacity_6kg": d.capacity_6kg,
                "capacity_12kg": d.capacity_12kg
            } for d in low_stock_depots
        ]
    }


@router.get("/global-report")
def generate_global_report(
    format: str = "csv",
    date: str | None = None,
    week: str | None = None,
    month: str | None = None,
    year: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    truck_id: Optional[int] = None,
    depot_id: Optional[int] = None,
    driver_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Export global détaillé de toutes les livraisons.

    Le front consomme la réponse comme un blob (CSV ouvrable dans Excel).
    Tous les filtres sont optionnels.
    """
    # Base query avec jointures pour récupérer les infos liées
    q = (
        db.query(Delivery)
        .outerjoin(Truck, Delivery.truck_id == Truck.id)
        .outerjoin(Depot, Delivery.depot_id == Depot.id)
        .outerjoin(User, Delivery.driver_id == User.id)
    )

    # Fenêtre temporelle basée sur date / semaine / mois / année
    start_dt: datetime | None = None
    end_dt: datetime | None = None

    if date:
        d = datetime.fromisoformat(date).date()
        start_dt = datetime.combine(d, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)
    elif week:
        # Format attendu: YYYY-Www (ex: 2024-W05)
        try:
            year_str, week_str = week.split("-W")
            y = int(year_str)
            w = int(week_str)
            first_day = date.fromisocalendar(y, w, 1)  # Lundi
            start_dt = datetime.combine(first_day, datetime.min.time())
            end_dt = start_dt + timedelta(days=7)
        except Exception:
            raise HTTPException(status_code=400, detail="Paramètre 'week' invalide")
    elif month:
        # Format attendu: YYYY-MM
        try:
            y, m = map(int, month.split("-"))
            first_day = date(y, m, 1)
            if m == 12:
                next_month = date(y + 1, 1, 1)
            else:
                next_month = date(y, m + 1, 1)
            start_dt = datetime.combine(first_day, datetime.min.time())
            end_dt = datetime.combine(next_month, datetime.min.time())
        except Exception:
            raise HTTPException(status_code=400, detail="Paramètre 'month' invalide")
    elif year:
        try:
            y = int(year)
            first_day = date(y, 1, 1)
            next_year = date(y + 1, 1, 1)
            start_dt = datetime.combine(first_day, datetime.min.time())
            end_dt = datetime.combine(next_year, datetime.min.time())
        except Exception:
            raise HTTPException(status_code=400, detail="Paramètre 'year' invalide")

    # Plage explicite from/to (format YYYY-MM-DD) – vient compléter/affiner
    if from_:
        d_from = datetime.fromisoformat(from_).date()
        from_dt = datetime.combine(d_from, datetime.min.time())
        if start_dt is None or from_dt > start_dt:
            start_dt = from_dt
    if to:
        d_to = datetime.fromisoformat(to).date()
        to_dt = datetime.combine(d_to, datetime.min.time()) + timedelta(days=1)
        if end_dt is None or to_dt < end_dt:
            end_dt = to_dt

    if start_dt is not None:
        q = q.filter(Delivery.scheduled_date >= start_dt)
    if end_dt is not None:
        q = q.filter(Delivery.scheduled_date < end_dt)

    # Filtres simples
    if truck_id is not None:
        q = q.filter(Delivery.truck_id == truck_id)
    if depot_id is not None:
        q = q.filter(Delivery.depot_id == depot_id)
    if driver_id is not None:
        q = q.filter(Delivery.driver_id == driver_id)

    if status:
        # Le front envoie des statuts "en_mission", "disponible", "maintenance".
        # On les mappe grossièrement sur les statuts de Delivery.
        if status == "en_mission":
            q = q.filter(Delivery.status == DeliveryStatusEnum.IN_PROGRESS)
        elif status == "disponible":
            # Livraisons non terminées ou terminées - on ne filtre pas plus
            pass
        elif status == "maintenance":
            # Pas de notion directe, pas de filtre spécifique
            pass

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Delivery.destination_name.ilike(like),
                Delivery.destination_address.ilike(like),
                Truck.license_plate.ilike(like),
                Depot.name.ilike(like),
                User.full_name.ilike(like),
            )
        )

    deliveries = q.order_by(Delivery.created_at.desc()).all()

    # Si format=json, retourner directement les données détaillées pour affichage dans le dashboard
    if format == "json":
        result = []
        for d in deliveries:
            truck = d.truck
            depot = d.depot
            driver = d.driver
            result.append({
                "id": d.id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "scheduled_date": d.scheduled_date.isoformat() if d.scheduled_date else None,
                "actual_start": d.actual_start.isoformat() if d.actual_start else None,
                "actual_end": d.actual_end.isoformat() if d.actual_end else None,
                "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                "truck_plate": truck.license_plate if truck else None,
                "driver_name": driver.full_name if driver else None,
                "depot_name": depot.name if depot else None,
                "destination_name": d.destination_name,
                "destination_address": d.destination_address,
                "destination_latitude": d.destination_latitude,
                "destination_longitude": d.destination_longitude,
                "contact_name": d.contact_name,
                "contact_phone": d.contact_phone,
                "quantity_6kg": d.quantity_6kg,
                "quantity_12kg": d.quantity_12kg,
                "quantity_total": d.quantity,
                "echange_effectue": d.echange_effectue,
                "quantity_6kg_vide_recupere": d.quantity_6kg_vide_recupere,
                "quantity_12kg_vide_recupere": d.quantity_12kg_vide_recupere,
                "notes": d.notes,
            })
        return result

    # Colonnes communes pour tous les formats d'export
    headers = [
        "id",
        "date_creation",
        "date_planifiee",
        "debut_effectif",
        "fin_effective",
        "statut",
        "camion",
        "chauffeur",
        "depot_depart",
        "destination_nom",
        "destination_adresse",
        "lat_destination",
        "lon_destination",
        "contact_nom",
        "contact_tel",
        "qte_6kg",
        "qte_12kg",
        "qte_totale",
        "echange_effectue",
        "qte_6kg_vide_recup",
        "qte_12kg_vide_recup",
        "notes",
    ]

    rows = []
    for d in deliveries:
        truck = d.truck
        depot = d.depot
        driver = d.driver
        rows.append([
            d.id,
            d.created_at.isoformat() if d.created_at else "",
            d.scheduled_date.isoformat() if d.scheduled_date else "",
            d.actual_start.isoformat() if d.actual_start else "",
            d.actual_end.isoformat() if d.actual_end else "",
            d.status.value if hasattr(d.status, "value") else str(d.status),
            truck.license_plate if truck else "",
            driver.full_name if driver else "",
            depot.name if depot else "",
            d.destination_name or "",
            d.destination_address or "",
            d.destination_latitude if d.destination_latitude is not None else "",
            d.destination_longitude if d.destination_longitude is not None else "",
            d.contact_name or "",
            d.contact_phone or "",
            d.quantity_6kg or 0,
            d.quantity_12kg or 0,
            d.quantity or 0,
            "oui" if d.echange_effectue else "non",
            d.quantity_6kg_vide_recupere or 0,
            d.quantity_12kg_vide_recupere or 0,
            (d.notes or "").replace("\n", " "),
        ])

    # Excel (XLSX)
    if format == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            raise HTTPException(status_code=500, detail="Bibliothèque openpyxl manquante côté serveur")

        wb = Workbook()
        ws = wb.active
        ws.title = "Livraisons"

        ws.append(headers)
        for row in rows:
            ws.append(row)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=rapport_global.xlsx",
            },
        )

    # PDF
    if format == "pdf":
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.pdfgen import canvas
        except ImportError:
            raise HTTPException(status_code=500, detail="Bibliothèque reportlab manquante côté serveur")

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=landscape(A4))
        width, height = landscape(A4)

        title = "Rapport global des livraisons"
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, height - 40, title)
        c.setFont("Helvetica", 8)
        c.drawString(40, height - 55, datetime.now().strftime("Généré le %d/%m/%Y %H:%M"))

        # En-têtes
        x_start = 40
        y = height - 80
        col_widths = [40, 70, 70, 60, 60, 60, 70, 70, 80, 90]
        header_labels = [
            "ID",
            "Création",
            "Planifiée",
            "Début",
            "Fin",
            "Statut",
            "Camion",
            "Chauffeur",
            "Dépôt",
            "Destination",
        ]

        c.setFont("Helvetica-Bold", 7)
        x = x_start
        for i, label in enumerate(header_labels):
            c.drawString(x, y, label)
            x += col_widths[i]

        # Lignes
        c.setFont("Helvetica", 7)
        y -= 12
        for row in rows:
            if y < 40:
                c.showPage()
                c.setFont("Helvetica-Bold", 7)
                y = height - 40
                x = x_start
                for i, label in enumerate(header_labels):
                    c.drawString(x, y, label)
                    x += col_widths[i]
                c.setFont("Helvetica", 7)
                y -= 12

            x = x_start
            # On ne met que les 10 premières colonnes dans le PDF pour garder une largeur raisonnable
            for i, value in enumerate(row[:10]):
                text = str(value)[:40]
                c.drawString(x, y, text)
                x += col_widths[i]
            y -= 10

        c.showPage()
        c.save()
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=rapport_global.pdf",
            },
        )

    # CSV par défaut (ou format inconnu)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

    contents = output.getvalue().encode("utf-8-sig")  # BOM pour Excel
    output.close()

    return StreamingResponse(
        io.BytesIO(contents),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=rapport_global.csv",
        },
    )

@router.get("/gps-tracking", response_model=list[GPSLogResponse])
def get_all_gps_tracking(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    """Get latest GPS position for all trucks"""
    from sqlalchemy import func
    
    # Subquery to get latest timestamp per truck
    subq = db.query(
        GPSLog.truck_id,
        func.max(GPSLog.timestamp).label('max_timestamp')
    ).group_by(GPSLog.truck_id).subquery()
    
    # Get latest GPS logs for each truck
    latest_logs = db.query(GPSLog).join(
        subq,
        (GPSLog.truck_id == subq.c.truck_id) & (GPSLog.timestamp == subq.c.max_timestamp)
    ).all()
    
    return [GPSLogResponse.from_orm(log) for log in latest_logs]

@router.get("/gps-tracking/{truck_id}")
def get_truck_location(truck_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    latest_log = db.query(GPSLog).filter(GPSLog.truck_id == truck_id).order_by(GPSLog.timestamp.desc()).first()
    if not latest_log:
        raise HTTPException(status_code=404, detail="Pas de localisation disponible")
    return GPSLogResponse.from_orm(latest_log)

@router.get("/gps-history/{delivery_id}")
def get_delivery_gps_history(delivery_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    logs = db.query(GPSLog).filter(GPSLog.delivery_id == delivery_id).order_by(GPSLog.timestamp).all()
    return [GPSLogResponse.from_orm(log) for log in logs]

@router.post("/deliveries/{delivery_id}/validate-sage")
def validate_delivery_on_sage(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Envoyer une livraison complétée à Sage X3 avec les quantités livrées (6kg/12kg)."""
    from app.services.sage_sql_service import valider_programme_sage, get_sage_sql_connection

    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")

    if delivery.status != DeliveryStatusEnum.COMPLETED:
        raise HTTPException(status_code=400, detail=f"La livraison doit être complétée (status actuel: {delivery.status})")

    # Récupérer la livraison avec ses détails
    program_line = db.query(type(delivery)).filter(type(delivery).id == delivery_id).first()

    try:
        # Écrire dans Sage via IntegrationOutbox
        outbox_event = IntegrationOutbox(
            event_type="delivery_completed",
            direction="outbound",
            system_name="sage_x3",
            aggregate_type="delivery",
            aggregate_id=str(delivery.id),
            external_message_id=f"delivery:{delivery.id}:{utc_now_iso()}",
            status="pending",
            payload_json={
                "delivery_id": delivery.id,
                "truck_id": delivery.truck_id,
                "driver_id": delivery.driver_id,
                "depot_id": delivery.depot_id,
                "destination_name": delivery.destination_name,
                "quantity_6kg": delivery.quantity_6kg,
                "quantity_12kg": delivery.quantity_12kg,
                "status": delivery.status,
                "actual_start": delivery.actual_start.isoformat() if delivery.actual_start else None,
                "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
                "notes": delivery.notes,
                "completed_at": utc_now_iso(),
            },
            response_json={"received_at": utc_now_iso()},
            sent_at=utc_now(),
        )

        db.add(outbox_event)
        db.commit()
        db.refresh(outbox_event)

        return {
            "success": True,
            "message": "Livraison validée et envoyée à Sage X3",
            "delivery_id": delivery.id,
            "outbox_id": outbox_event.id,
            "status": outbox_event.status,
            "payload": outbox_event.payload_json,
        }
    except Exception as e:
        logger.error(f"Erreur validation livraison Sage: {e}")
        return {
            "success": False,
            "message": f"Erreur lors de la validation: {str(e)}",
            "delivery_id": delivery.id,
        }


class ArticleLineWrite(BaseModel):
    """Données d'article à écrire dans Sage X3."""
    article_code: str = Field(..., description="Code article (G06BI, G1250, G0275, etc.)")
    quantity: float = Field(..., ge=0, description="Quantité collectée")
    unit_price: float = Field(default=0, description="Prix unitaire")
    comment: str = Field(default="", description="Commentaire (optionnel)")


class DeliveryArticleValidation(BaseModel):
    """Validation d'une livraison avec articles collectés."""
    program_code: str = Field(..., description="Code programme Sage (ex: PCOL-CA001-190526-1746)")
    client_code: str = Field(..., description="Code client")
    articles: list[ArticleLineWrite] = Field(..., description="Articles collectés")


@router.post("/deliveries/write-sage-articles")
def write_delivery_articles_to_sage(
    payload: DeliveryArticleValidation,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Écrire les articles collectés dans Sage X3 pour une livraison complétée.

    - Article 1 → UPDATE ligne existante
    - Article 2+ → INSERT nouvelles lignes (dupliquées)
    """
    from app.services.sage_sql_service import get_sage_sql_connection
    from app.config import settings

    if not payload.articles:
        raise HTTPException(status_code=400, detail="Au moins un article doit être fourni")

    try:
        conn = get_sage_sql_connection()
        cursor = conn.cursor()
        schema = settings.SAGE_SQL_SCHEMA

        # Récupérer la première ligne existante du client pour ce programme
        cursor.execute(
            f"""
            SELECT TOP 1 YLIGNE_0, YBPC_0, YPLV_0, YQUARTIER_0, MDL_0, YDATE_0, SOHNUM_0, SOPLIN_0, YNUMFICHE_0
            FROM [{schema}].[YPRGCOLLD]
            WHERE YPROGCOLL_0 = %s AND YBPC_0 = %s
            ORDER BY YLIGNE_0
            """,
            (payload.program_code, payload.client_code)
        )

        result = cursor.fetchone()
        if not result:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Client {payload.client_code} non trouvé dans ce programme")

        first_line = result[0]
        client_plv = result[2]
        client_zone = result[3]
        delivery_mode = result[4]
        delivery_date = result[5]
        soh_num = result[6]  # Numéro commande Sage
        sop_lin = result[7]  # Ligne commande Sage
        num_fiche = result[8]  # Numéro de fiche

        # Récupérer le max numéro de ligne pour les insertions futures
        cursor.execute(
            f"SELECT ISNULL(MAX(YLIGNE_0), 0) FROM [{schema}].[YPRGCOLLD] WHERE YPROGCOLL_0 = %s",
            (payload.program_code,)
        )
        max_line = int(cursor.fetchone()[0])

        results = []

        # ── ARTICLE 1 — UPDATE ligne existante ──────────────────────
        if len(payload.articles) > 0:
            article = payload.articles[0]
            amount = article.quantity * article.unit_price

            cursor.execute(
                f"""
                UPDATE [{schema}].[YPRGCOLLD]
                SET YITMREF_0 = %s,
                    YQTY_0 = %s,
                    YSMREMB_0 = %s,
                    YDES_0 = %s,
                    UPDDATTIM_0 = GETDATE(),
                    UPDUSR_0 = 'SODIGAZ_APP'
                WHERE YPROGCOLL_0 = %s AND YBPC_0 = %s AND YLIGNE_0 = %s
                """,
                (article.article_code, article.quantity, amount, article.comment,
                 payload.program_code, payload.client_code, first_line)
            )
            rows_affected = cursor.rowcount
            results.append({
                "article": article.article_code,
                "quantity": article.quantity,
                "amount": amount,
                "action": "UPDATE",
                "line": first_line,
                "rows_affected": rows_affected,
            })

        # ── ARTICLES 2+ — INSERT lignes dupliquées ──────────────────────
        for i in range(1, len(payload.articles)):
            article = payload.articles[i]
            max_line += 1
            amount = article.quantity * article.unit_price

            cursor.execute(
                f"""
                INSERT INTO [{schema}].[YPRGCOLLD]
                (YPROGCOLL_0, YLIGNE_0, YBPC_0, YPLV_0, YQUARTIER_0,
                 YITMREF_0, YQTY_0, YSMREMB_0, YDES_0, MDL_0, YDATE_0, SOHNUM_0, SOPLIN_0, YNUMFICHE_0,
                 CREDATTIM_0, UPDDATTIM_0, AUUID_0, CREUSR_0, UPDUSR_0, UPDTICK_0)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        GETDATE(), GETDATE(), NEWID(), 'SODIGAZ_APP', 'SODIGAZ_APP', 1)
                """,
                (payload.program_code, max_line, payload.client_code, client_plv, client_zone,
                 article.article_code, article.quantity, amount, article.comment,
                 delivery_mode, delivery_date, soh_num, sop_lin, num_fiche)
            )
            rows_affected = cursor.rowcount
            results.append({
                "article": article.article_code,
                "quantity": article.quantity,
                "amount": amount,
                "action": "INSERT",
                "line": max_line,
                "rows_affected": rows_affected,
            })

        conn.commit()
        conn.close()

        # Créer un événement IntegrationOutbox pour archivage
        outbox_event = IntegrationOutbox(
            event_type="delivery_articles_written",
            direction="outbound",
            system_name="sage_x3",
            aggregate_type="delivery_line",
            aggregate_id=f"{payload.program_code}:{payload.client_code}",
            external_message_id=f"articles:{payload.program_code}:{payload.client_code}:{utc_now_iso()}",
            status="sent",
            payload_json={
                "program_code": payload.program_code,
                "client_code": payload.client_code,
                "articles_written": results,
                "written_at": utc_now_iso(),
            },
            response_json={"completed_at": utc_now_iso()},
            sent_at=utc_now(),
        )
        db.add(outbox_event)
        db.commit()

        return {
            "success": True,
            "message": f"✅ {len(results)} article(s) écrit(s) dans Sage X3",
            "program_code": payload.program_code,
            "client_code": payload.client_code,
            "articles_written": results,
            "total_amount": sum(r["amount"] for r in results),
        }

    except Exception as e:
        logger.error(f"Erreur écriture articles Sage: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur Sage: {str(e)}")

# --- CHAUFFEURS ---

@router.get("/drivers", response_model=list[UserResponse])
def get_all_drivers(db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    drivers = db.query(User).filter(User.role == RoleEnum.RAVITAILLEUR).all()
    return [UserResponse.from_orm(d) for d in drivers]

@router.post("/drivers", response_model=UserResponse)
def create_driver(user_data: dict, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    existing = db.query(User).filter(User.username == user_data["username"]).first()
    if existing:
        raise HTTPException(status_code=400, detail="Utilisateur déjà existant")
    
    # Vérifier l'email
    if "email" in user_data:
        existing_email = db.query(User).filter(User.email == user_data["email"]).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
    
    new_driver = User(
        email=user_data.get("email", f"{user_data['username']}@sodigaz.bf"),
        username=user_data["username"],
        full_name=user_data["full_name"],
        phone=user_data.get("phone", ""),
        hashed_password=hash_password(user_data["password"]),
        role=RoleEnum.RAVITAILLEUR,
        is_active=True
    )
    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)
    return UserResponse.from_orm(new_driver)

@router.put("/drivers/{driver_id}", response_model=UserResponse)
def update_driver(driver_id: int, user_data: dict, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    driver = db.query(User).filter(User.id == driver_id, User.role == RoleEnum.RAVITAILLEUR).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Chauffeur introuvable")
    
    # Vérifier l'unicité du username si modifié
    if "username" in user_data and user_data["username"] != driver.username:
        existing = db.query(User).filter(User.username == user_data["username"]).first()
        if existing:
            raise HTTPException(status_code=400, detail="Nom d'utilisateur déjà utilisé")
        driver.username = user_data["username"]
    
    # Vérifier l'unicité de l'email si modifié
    if "email" in user_data and user_data["email"] != driver.email:
        existing_email = db.query(User).filter(User.email == user_data["email"]).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
        driver.email = user_data["email"]
    
    # Mettre à jour les autres champs
    if "full_name" in user_data:
        driver.full_name = user_data["full_name"]
    if "phone" in user_data:
        driver.phone = user_data["phone"]
    
    # Mettre à jour le mot de passe si fourni
    if "password" in user_data and user_data["password"]:
        driver.hashed_password = hash_password(user_data["password"])
    
    db.commit()
    db.refresh(driver)
    return UserResponse.from_orm(driver)

@router.delete("/drivers/{driver_id}", status_code=204)
def delete_driver(driver_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(RoleEnum.ADMIN))):
    driver = db.query(User).filter(User.id == driver_id, User.role == RoleEnum.RAVITAILLEUR).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Chauffeur introuvable")
    
    # Vérifier si le chauffeur n'a pas de camion assigné
    truck = db.query(Truck).filter(Truck.driver_id == driver_id).first()
    if truck:
        raise HTTPException(status_code=400, detail="Impossible de supprimer un chauffeur qui a un camion assigné")
    
    db.delete(driver)
    db.commit()
    return None


class SyncConflictResolutionRequest(BaseModel):
    resolution_status: str = "resolved"


class OutboxProcessRequest(BaseModel):
    limit: int = 50


@router.get("/sync-conflicts")
def get_sync_conflicts(
    resolution_status: str = "open",
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    query = db.query(SyncConflict).order_by(SyncConflict.created_at.desc())
    if resolution_status != "all":
        query = query.filter(SyncConflict.resolution_status == resolution_status)

    conflicts = query.limit(limit).all()
    return [
        {
            "id": conflict.id,
            "aggregate_type": conflict.aggregate_type,
            "aggregate_id": conflict.aggregate_id,
            "delivery_id": conflict.delivery_id,
            "batch_id": conflict.batch_id,
            "driver_id": conflict.driver_id,
            "device_id": conflict.device_id,
            "idempotency_key": conflict.idempotency_key,
            "conflict_type": conflict.conflict_type,
            "local_payload": conflict.local_payload,
            "server_state": conflict.server_state,
            "resolution_status": conflict.resolution_status,
            "created_at": conflict.created_at.isoformat(),
            "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
            "resolved_by": conflict.resolved_by,
        }
        for conflict in conflicts
    ]


@router.put("/sync-conflicts/{conflict_id}/resolve")
def resolve_sync_conflict(
    conflict_id: int,
    payload: SyncConflictResolutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    conflict = db.query(SyncConflict).filter(SyncConflict.id == conflict_id).first()
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflit introuvable")

    conflict.resolution_status = payload.resolution_status
    conflict.resolved_at = utc_now()
    conflict.resolved_by = current_user.id
    db.commit()
    db.refresh(conflict)

    return {
        "id": conflict.id,
        "resolution_status": conflict.resolution_status,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        "resolved_by": conflict.resolved_by,
    }


@router.get("/integration-outbox")
def get_integration_outbox(
    status: str = "all",
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    query = db.query(IntegrationOutbox).order_by(IntegrationOutbox.created_at.desc())
    if status != "all":
        query = query.filter(IntegrationOutbox.status == status)

    events = query.limit(limit).all()
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "message_id": event.external_message_id,
            "status": event.status,
            "retry_count": event.retry_count,
            "error_message": event.error_message,
            "created_at": event.created_at.isoformat(),
            "sent_at": event.sent_at.isoformat() if event.sent_at else None,
        }
        for event in events
    ]


@router.post("/integration-outbox/process")
def process_integration_outbox(
    payload: OutboxProcessRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    return process_pending_outbox_events(db, limit=payload.limit)


def _serialize_integration_health_check(check: IntegrationHealthCheck) -> dict:
    return {
        "id": check.id,
        "system_name": check.system_name,
        "mode": check.mode,
        "status": check.status,
        "detail": check.detail,
        "base_url": check.base_url,
        "health_url": check.health_url,
        "status_code": check.status_code,
        "response": check.response_json,
        "checked_by": check.checked_by,
        "checked_at": check.created_at.isoformat() if check.created_at else None,
    }


def _build_integration_outbox_health_payload(db: Session, latest_check: Optional[IntegrationHealthCheck] = None) -> dict:
    pending_count = db.query(func.count(IntegrationOutbox.id)).filter(
        IntegrationOutbox.status.in_(["pending", "failed_retryable"])
    ).scalar() or 0

    sent_count = db.query(func.count(IntegrationOutbox.id)).filter(
        IntegrationOutbox.status == "sent"
    ).scalar() or 0

    failed_count = db.query(func.count(IntegrationOutbox.id)).filter(
        IntegrationOutbox.status == "failed_dead_letter"
    ).scalar() or 0

    recent_errors = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.status.in_(["failed_retryable", "failed_dead_letter"]),
        IntegrationOutbox.error_message.isnot(None)
    ).order_by(
        IntegrationOutbox.last_attempt_at.desc().nullslast(),
        IntegrationOutbox.created_at.desc(),
    ).limit(10).all()

    if latest_check is None:
        latest_check = db.query(IntegrationHealthCheck).filter(
            IntegrationHealthCheck.system_name == "sage_x3"
        ).order_by(IntegrationHealthCheck.created_at.desc()).first()

    recent_checks = db.query(IntegrationHealthCheck).filter(
        IntegrationHealthCheck.system_name == "sage_x3"
    ).order_by(IntegrationHealthCheck.created_at.desc()).limit(10).all()

    health = check_sage_x3_health()
    health["probed_at"] = utc_now_iso()
    health["last_checked_at"] = latest_check.created_at.isoformat() if latest_check and latest_check.created_at else None
    health["last_check"] = _serialize_integration_health_check(latest_check) if latest_check else None
    health["recent_checks"] = [_serialize_integration_health_check(check) for check in recent_checks]
    health["outbox"] = {
        "pending": pending_count,
        "sent": sent_count,
        "failed_dead_letter": failed_count,
    }
    health["recent_errors"] = [
        {
            "id": event.id,
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "message_id": event.external_message_id,
            "status": event.status,
            "retry_count": event.retry_count,
            "error_message": event.error_message,
            "last_attempt_at": event.last_attempt_at.isoformat() if event.last_attempt_at else None,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in recent_errors
    ]
    return health


@router.get("/integration-outbox/health")
def get_integration_outbox_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    return _build_integration_outbox_health_payload(db)


@router.post("/integration-outbox/health/check")
def check_integration_outbox_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    health = check_sage_x3_health()
    health_check = IntegrationHealthCheck(
        system_name="sage_x3",
        mode=health.get("mode") or "unknown",
        status=health.get("status") or "unknown",
        detail=health.get("detail"),
        base_url=health.get("base_url"),
        health_url=health.get("health_url"),
        status_code=health.get("status_code"),
        response_json=health.get("response"),
        checked_by=current_user.id,
    )
    db.add(health_check)
    db.commit()
    db.refresh(health_check)
    return _build_integration_outbox_health_payload(db, latest_check=health_check)


# --- SAGE X3 MISSIONS ---

@router.get("/sage-missions", response_model=list[SageMissionResponse])
def get_sage_missions(
    status: Optional[str] = "pending_approval",  # pending_approval, approved, rejected, synced, all
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """
    Lister les missions reçues de Sage X3 (cahier de charge).
    Utilise la table Delivery avec source_type='sage_inbound'
    """
    query = db.query(Delivery).filter(Delivery.source_type.in_(["sage_inbound", "sage_program"]))
    
    if status != "all":
        query = query.filter(Delivery.external_status == status)
    
    missions = query.order_by(Delivery.created_at.desc()).limit(limit).all()
    return [SageMissionResponse.from_orm(m) for m in missions]


@router.get("/sage-missions/{mission_id}", response_model=SageMissionResponse)
def get_sage_mission_detail(
    mission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """Détail d'une mission Sage"""
    mission = db.query(Delivery).filter(
        Delivery.id == mission_id,
        Delivery.source_type.in_(["sage_inbound", "sage_program"])
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    
    return SageMissionResponse.from_orm(mission)


@router.post("/sage-missions/{mission_id}/approve", response_model=SageMissionApprovalResponse)
def approve_sage_mission(
    mission_id: int,
    truck_id: Optional[int] = None,  # Optionnel si fourni lors de l'inbound
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """
    Approuver une mission Sage X3:
    1. Marquer comme 'approved'
    2. Si truck_id fourni, assigner le camion
    3. Envoyer confirmation à Sage X3 via IntegrationOutbox
    """
    mission = db.query(Delivery).filter(
        Delivery.id == mission_id,
        Delivery.source_type.in_(["sage_inbound", "sage_program"])
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    
    if mission.external_status != SageMissionStatusEnum.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Mission déjà {mission.external_status}, impossible d'approuver"
        )
    
    # Assigner le camion si fourni
    if truck_id:
        truck = db.query(Truck).filter(Truck.id == truck_id, Truck.is_active == True).first()
        if not truck:
            raise HTTPException(status_code=404, detail="Camion introuvable")
        mission.truck_id = truck_id
        mission.driver_id = truck.driver_id
    
    # Marquer comme approuvée
    mission.external_status = SageMissionStatusEnum.APPROVED
    mission.external_sync_at = utc_now()
    
    # Créer un event d'approbation pour Sage
    outbox_event = IntegrationOutbox(
        event_type="mission_approved",
        aggregate_type="delivery",
        aggregate_id=mission.id,
        payload_json={
            "delivery_id": mission.id,
            "external_delivery_id": mission.external_delivery_id,
            "truck_id": mission.truck_id,
            "driver_id": mission.driver_id,
            "status": "approved"
        },
        external_message_id=f"mission_approved_{mission.external_delivery_id}_{utc_now_iso()}"
    )
    
    db.add(outbox_event)
    db.commit()
    db.refresh(mission)
    
    return SageMissionApprovalResponse(
        success=True,
        message=f"Mission {mission_id} approuvée avec succès",
        mission_id=mission_id,
        delivery_id=mission.id
    )


@router.post("/sage-missions/{mission_id}/reject", response_model=SageMissionApprovalResponse)
def reject_sage_mission(
    mission_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """
    Rejeter une mission Sage X3:
    1. Marquer comme 'rejected'
    2. Stocker la raison du rejet
    3. Envoyer rejet à Sage X3 via IntegrationOutbox
    """
    mission = db.query(Delivery).filter(
        Delivery.id == mission_id,
        Delivery.source_type.in_(["sage_inbound", "sage_program"])
    ).first()
    
    if not mission:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    
    if mission.external_status != SageMissionStatusEnum.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Mission déjà {mission.external_status}, impossible de rejeter"
        )
    
    # Marquer comme rejetée
    mission.external_status = SageMissionStatusEnum.REJECTED
    mission.external_error = reason or "Rejet par l'administrateur"
    mission.external_sync_at = utc_now()
    
    # Créer un event de rejet pour Sage
    outbox_event = IntegrationOutbox(
        event_type="mission_rejected",
        aggregate_type="delivery",
        aggregate_id=mission.id,
        payload_json={
            "delivery_id": mission.id,
            "external_delivery_id": mission.external_delivery_id,
            "status": "rejected",
            "reason": reason or "Rejet par l'administrateur"
        },
        external_message_id=f"mission_rejected_{mission.external_delivery_id}_{utc_now_iso()}"
    )
    
    db.add(outbox_event)
    db.commit()
    db.refresh(mission)

    return SageMissionApprovalResponse(
        success=True,
        message=f"Mission {mission_id} rejetée",
        mission_id=mission_id,
        delivery_id=mission.id
    )


# --- SYNCHRONISATION CHAUFFEURS SAGE ---

class SageDriverSyncResponse(BaseModel):
    success: bool
    message: str
    sage_codes_found: int
    drivers_created: int
    drivers_reactivated: int
    drivers_existing: int
    drivers: list[dict] = []

@router.get("/sync-sage-drivers", response_model=SageDriverSyncResponse)
def sync_sage_drivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """
    Lit tous les codes YLIV uniques depuis Sage SQL et crée/réactive les chauffeurs.
    Crée automatiquement les mappages chauffeur/camion si besoin.
    """
    from app.services.sage_sql_service import get_sage_sql_connection

    try:
        # 1. Lire les codes YLIV uniques depuis Sage
        conn = get_sage_sql_connection()
        cursor = conn.cursor()
        schema = settings.SAGE_SQL_SCHEMA

        cursor.execute(f"""
            SELECT DISTINCT UPPER(YLIV_0) as yliv
            FROM [{schema}].[YPRGCOLL]
            WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
            ORDER BY yliv
        """)

        sage_codes = [row[0].strip() for row in cursor.fetchall()]
        conn.close()

        if not sage_codes:
            return SageDriverSyncResponse(
                success=False,
                message="Aucun code chauffeur trouvé dans Sage SQL",
                sage_codes_found=0,
                drivers_created=0,
                drivers_reactivated=0,
                drivers_existing=0,
                drivers=[]
            )

        # 2. Créer/réactiver les chauffeurs
        created_count = 0
        reactivated_count = 0
        existing_count = 0
        driver_results = []

        for sage_code in sage_codes:
            normalized = sage_code.lower()
            email = f"{normalized}@sodigaz-app.local"
            username = normalized
            password = f"Code{sage_code.upper()}@2026"

            # Chercher chauffeur existant
            existing_driver = db.query(User).filter(
                func.upper(User.email) == email.upper()
            ).first()

            if existing_driver:
                if existing_driver.role == RoleEnum.RAVITAILLEUR and existing_driver.is_active:
                    existing_count += 1
                    driver_results.append({
                        "sage_code": sage_code,
                        "user_id": existing_driver.id,
                        "email": existing_driver.email,
                        "status": "existing",
                        "message": f"Chauffeur existe déjà (ID: {existing_driver.id})"
                    })
                elif not existing_driver.is_active:
                    existing_driver.is_active = True
                    db.flush()
                    reactivated_count += 1
                    driver_results.append({
                        "sage_code": sage_code,
                        "user_id": existing_driver.id,
                        "email": existing_driver.email,
                        "status": "reactivated",
                        "message": f"Chauffeur réactivé (ID: {existing_driver.id})"
                    })
            else:
                # Créer le chauffeur
                driver = User(
                    email=email,
                    username=username,
                    hashed_password=hash_password(password),
                    full_name=f"Chauffeur {sage_code}",
                    phone=None,
                    role=RoleEnum.RAVITAILLEUR,
                    is_active=True,
                )
                db.add(driver)
                db.flush()
                created_count += 1
                driver_results.append({
                    "sage_code": sage_code,
                    "user_id": driver.id,
                    "email": email,
                    "password": password,
                    "status": "created",
                    "message": f"Chauffeur créé (ID: {driver.id})"
                })

        db.commit()

        return SageDriverSyncResponse(
            success=True,
            message=f"Synchronisation réussie: {created_count} créés, {reactivated_count} réactivés, {existing_count} existants",
            sage_codes_found=len(sage_codes),
            drivers_created=created_count,
            drivers_reactivated=reactivated_count,
            drivers_existing=existing_count,
            drivers=driver_results
        )

    except Exception as e:
        db.rollback()
        import traceback
        error_detail = f"{str(e)}\n{traceback.format_exc()}"
        return SageDriverSyncResponse(
            success=False,
            message=f"Erreur lors de la synchronisation: {str(e)}",
            sage_codes_found=0,
            drivers_created=0,
            drivers_reactivated=0,
            drivers_existing=0,
            drivers=[]
        )


class DriverMappingSuggestion(BaseModel):
    sage_driver_code: str
    truck_code: str
    user_id: int
    user_email: str
    auto_created: bool


class SageMappingSyncResponse(BaseModel):
    success: bool
    message: str
    mappings_created: int
    mappings_activated: int
    suggestions: list[DriverMappingSuggestion] = []


@router.post("/sync-sage-mappings", response_model=SageMappingSyncResponse)
def sync_sage_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN))
):
    """
    Crée automatiquement les mappages chauffeur/camion pour tous les programmes Sage
    en utilisant les codes chauffeur (YLIV) lus depuis Sage SQL.
    """
    from app.services.sage_sql_service import get_sage_sql_connection

    try:
        conn = get_sage_sql_connection()
        cursor = conn.cursor()
        schema = settings.SAGE_SQL_SCHEMA

        # Lire tous les mappages uniques driver/truck depuis Sage
        cursor.execute(f"""
            SELECT DISTINCT
                UPPER(YLIV_0) as sage_driver_code,
                UPPER(YMATCAM_0) as truck_code
            FROM [{schema}].[YPRGCOLL]
            WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
            AND YMATCAM_0 IS NOT NULL AND YMATCAM_0 != ''
            ORDER BY sage_driver_code, truck_code
        """)

        programs = cursor.fetchall()
        conn.close()

        mappings_created = 0
        mappings_activated = 0
        suggestions = []

        for sage_code, truck_code in programs:
            sage_code = sage_code.strip()
            truck_code = truck_code.strip()
            program_code = "mapped_from_sage"

            # Chercher si le mapping existe
            existing_mapping = db.query(DriverMapping).filter(
                func.upper(DriverMapping.sage_driver_code) == sage_code.upper(),
                func.upper(DriverMapping.truck_code) == truck_code.upper(),
            ).first()

            if existing_mapping:
                if not existing_mapping.is_active or existing_mapping.status == DriverMappingStatusEnum.INACTIVE:
                    existing_mapping.is_active = True
                    existing_mapping.status = DriverMappingStatusEnum.ACTIVE
                    mappings_activated += 1
            else:
                # Chercher ou créer le chauffeur
                normalized_code = sage_code.lower()
                email = f"{normalized_code}@sodigaz-app.local"

                driver = db.query(User).filter(
                    func.upper(User.email) == email.upper(),
                    User.role == RoleEnum.RAVITAILLEUR,
                    User.is_active == True,
                ).first()

                if driver:
                    # Chercher ou créer le camion
                    truck = db.query(Truck).filter(
                        func.upper(Truck.license_plate) == truck_code.upper(),
                        Truck.is_active == True,
                    ).first()

                    if not truck:
                        truck = Truck(license_plate=truck_code, is_active=True)
                        db.add(truck)
                        db.flush()

                    # Créer le mapping
                    new_mapping = DriverMapping(
                        user_id=driver.id,
                        sage_driver_code=sage_code,
                        truck_code=truck_code,
                        is_active=True,
                        status=DriverMappingStatusEnum.ACTIVE,
                        auto_created=True,
                        source_program_code=program_code,
                    )
                    db.add(new_mapping)
                    mappings_created += 1

                    suggestions.append(DriverMappingSuggestion(
                        sage_driver_code=sage_code,
                        truck_code=truck_code,
                        user_id=driver.id,
                        user_email=driver.email,
                        auto_created=True,
                    ))

        db.commit()

        return SageMappingSyncResponse(
            success=True,
            message=f"Synchronisation des mappages: {mappings_created} créés, {mappings_activated} activés",
            mappings_created=mappings_created,
            mappings_activated=mappings_activated,
            suggestions=suggestions,
        )

    except Exception as e:
        db.rollback()
        import traceback
        return SageMappingSyncResponse(
            success=False,
            message=f"Erreur lors du sync des mappages: {str(e)}",
            mappings_created=0,
            mappings_activated=0,
            suggestions=[],
        )


# ===========================================================================
# SEED DE DÉMO — Injection de livraisons pour la présentation
# ===========================================================================

import random

class SeedDemoRequest(BaseModel):
    max_days_ago: int = 14
    min_deliveries: int = 1
    max_deliveries: int = 3

@router.post("/seed-demo-deliveries")
def seed_demo_deliveries(
    body: SeedDemoRequest = SeedDemoRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    """Injecte des livraisons COMPLETED fictives pour chaque dépôt actif (démo/présentation)."""
    depots = db.query(Depot).filter(Depot.is_active == True).all()
    trucks = db.query(Truck).all()
    if not trucks:
        raise HTTPException(status_code=400, detail="Aucun camion trouvé. Créez au moins 1 camion.")

    created = 0
    now = utc_now()

    for depot in depots:
        count = random.randint(body.min_deliveries, body.max_deliveries)
        for _ in range(count):
            days_ago = random.randint(0, body.max_days_ago)
            hours_ago = random.randint(0, 23)
            delivery_time = now - timedelta(days=days_ago, hours=hours_ago)
            truck = random.choice(trucks)

            delivery = Delivery(
                truck_id=truck.id,
                depot_id=depot.id,
                destination_name=depot.name,
                destination_address=depot.address or "",
                destination_latitude=depot.latitude,
                destination_longitude=depot.longitude,
                contact_name="Démo",
                contact_phone=depot.phone or "-",
                quantity_6kg=random.randint(5, 30),
                quantity_12kg=random.randint(2, 15),
                status=DeliveryStatusEnum.COMPLETED,
                source_type="demo_seed",
                scheduled_date=delivery_time,
                actual_start=delivery_time - timedelta(minutes=random.randint(20, 90)),
                actual_end=delivery_time,
                created_at=delivery_time - timedelta(hours=1),
            )
            db.add(delivery)
            created += 1

    db.commit()
    return {"success": True, "message": f"{created} livraisons de démo créées pour {len(depots)} dépôts."}


# ===========================================================================
# SEED SAGE — Injection d'un programme Sage de démo pour test chauffeur
# ===========================================================================

class SeedSageProgramRequest(BaseModel):
    driver_id: int
    truck_id: int
    depot_id: int = 1
    nb_lines: int = 3
    program_type: str = "PRES"

@router.post("/seed-sage-program")
def seed_sage_program(
    body: SeedSageProgramRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    """Injecte un programme Sage X3 de démo et projette les missions chauffeur."""
    from app.schemas import SageProgramInbound, ProgramLineInbound
    from app.routers.integration import upsert_sage_program

    requested_program_type = (body.program_type or "PRES").strip().upper()
    is_collection = requested_program_type in {"PCOL", "COLLECTION"}
    if requested_program_type not in {"PRES", "DELIVERY", "PCOL", "COLLECTION"}:
        raise HTTPException(
            status_code=400,
            detail="program_type invalide. Valeurs supportées: PRES, DELIVERY, PCOL, COLLECTION.",
        )
    normalized_program_type = "COLLECTION" if is_collection else "DELIVERY"

    driver = db.query(User).filter(User.id == body.driver_id).first()
    if not driver or driver.role != RoleEnum.RAVITAILLEUR:
        raise HTTPException(status_code=400, detail=f"Chauffeur id={body.driver_id} introuvable ou pas ravitailleur.")
    truck = db.query(Truck).filter(Truck.id == body.truck_id).first()
    if not truck:
        raise HTTPException(status_code=400, detail=f"Camion id={body.truck_id} introuvable.")
    depot = db.query(Depot).filter(Depot.id == body.depot_id).first()
    if not depot:
        raise HTTPException(status_code=400, detail=f"Dépôt id={body.depot_id} introuvable.")

    timestamp = utc_now().strftime("%Y%m%d%H%M%S")
    program_prefix = "PCOL" if is_collection else "PRES"
    program_code = f"DEMO-{program_prefix}-{timestamp}"

    demo_clients = [
        ("CLI-DEMO-001", "Boutique Centrale", "Av. Kwame Nkrumah, Ouagadougou", 12.3714, -1.5197),
        ("CLI-DEMO-002", "Station Koudougou", "Route N1, Koudougou", 12.2533, -1.5146),
        ("CLI-DEMO-003", "Dépôt Bobo-Dioulasso", "Secteur 25, Bobo-Dioulasso", 11.1771, -4.2979),
        ("CLI-DEMO-004", "Revendeur ZAD", "Zone d'Activités Diverses, Ouaga", 12.3500, -1.5300),
        ("CLI-DEMO-005", "Dépôt Banfora", "Centre-ville, Banfora", 10.6333, -4.7667),
    ]

    lines = []
    for i in range(min(body.nb_lines, len(demo_clients))):
        c = demo_clients[i]
        products = [("GAZ_6KG", "Bouteille 6kg", "B06", random.randint(5, 20)),
                     ("GAZ_12KG", "Bouteille 12kg", "B12", random.randint(3, 12))]
        product = random.choice(products)
        lines.append(ProgramLineInbound(
            external_line_id=f"DEMO-L-{timestamp}-{i+1:02d}",
            line_code=f"LINE-{i+1:03d}",
            client_code=c[0],
            client_name=c[1],
            destination_address=c[2],
            destination_latitude=c[3],
            destination_longitude=c[4],
            contact_name=f"Resp. {c[1]}",
            contact_phone=f"+2267{random.randint(1000000, 9999999)}",
            product_code=product[0],
            product_label=product[1],
            article=product[2],
            zone="BF-DEMO",
            quantity_planned=product[3],
            delivery_mode="PCOL" if is_collection else "PRES",
            collection_sheet=f"FICHE-DEMO-{i+1:02d}" if is_collection else None,
            comment=(
                f"Ligne démo #{i+1} pour présentation Sage X3 - collecte de bouteilles vides"
                if is_collection
                else f"Ligne démo #{i+1} pour présentation Sage X3 - livraison avec encaissement"
            ),
        ))

    # ✅ Générer les codes Sage automatiquement pour le mapping
    sage_driver_code = f"{driver.id:06d}"  # Ex: "000003" pour Driver #3
    sage_truck_code = truck.license_plate or f"TRUCK-{truck.id:03d}"  # Ex: "CA092"

    payload = SageProgramInbound(
        program_code=program_code,
        program_type=normalized_program_type,
        site=depot.site_code,  # ✅ Use actual depot's site code
        date=date.today(),
        time="08:30",
        depot_id=body.depot_id,
        truck_id=body.truck_id,
        driver_id=body.driver_id,
        sage_driver_code=sage_driver_code,  # ← YLIV (Livraison)
        truck_code=sage_truck_code,         # ← YMATCAM
        transporter="SODIGAZ DEMO",
        status="active",
        source_updated_at=utc_now(),
        sync_version=1,
        lines=lines,
    )

    # Simuler un request avec le bon header Sage pour passer la validation
    from unittest.mock import MagicMock
    fake_request = MagicMock()
    fake_request.headers = {"X-Sage-X3-Token": "test-token-123"}

    result = upsert_sage_program(payload=payload, request=fake_request, db=db)

    return {
        "success": True,
        "program_code": program_code,
        "requested_program_type": requested_program_type,
        "normalized_program_type": normalized_program_type,
        "driver": driver.full_name,
        "truck_id": body.truck_id,
        "lines_count": len(lines),
        "message": f"Programme Sage '{program_code}' ({requested_program_type}) créé avec {len(lines)} lignes pour {driver.full_name}. Le chauffeur peut maintenant voir ses missions dans l'app.",
        "detail": result,
    }