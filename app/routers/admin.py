from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime, date, timedelta
from typing import Optional
from pydantic import BaseModel
import io
import csv
import math
from app.database import get_db
from app.models import User, Depot, Truck, Delivery, GPSLog, Stock, RoleEnum, DeliveryStatusEnum, SyncConflict, IntegrationOutbox, IntegrationHealthCheck, SageMissionStatusEnum
from app.schemas import (
    DepotCreate, DepotUpdate, DepotResponse,
    TruckCreate, TruckResponse,
    DeliveryCreate, DeliveryUpdate, DeliveryResponse,
    GPSLogResponse, UserResponse, SageMissionResponse, SageMissionApprovalResponse
)
from app.auth import require_role, hash_password
from app.services.outbox_worker import check_sage_x3_health, process_pending_outbox_events
from app.time_utils import utc_now, utc_now_iso
from app.websocket_manager import manager

router = APIRouter(prefix="/api/admin", tags=["admin"])

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
        phone=depot_data.phone,
        manager_id=depot_data.manager_id
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
    if depot_data.address:
        depot.address = depot_data.address
    if depot_data.phone:
        depot.phone = depot_data.phone
    
    db.commit()
    db.refresh(depot)
    return DepotResponse.from_orm(depot)


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
                "city": d.depot.city
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
        "status": delivery.status.value,
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
def create_delivery(
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
    manager.broadcast_to_all({
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
def update_delivery(
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
    manager.broadcast_to_all({
        "type": "delivery_updated",
        "delivery_id": delivery.id,
        "status": delivery.status
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
    query = db.query(Delivery).filter(Delivery.source_type == "sage_inbound")
    
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
        Delivery.source_type == "sage_inbound"
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
        Delivery.source_type == "sage_inbound"
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
        Delivery.source_type == "sage_inbound"
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