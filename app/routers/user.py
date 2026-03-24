import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User, Depot, Delivery, GPSLog, Preorder, Stock, Truck, RoleEnum, DeliveryStatusEnum, PreorderStatusEnum
from app.schemas import DepotResponse, PreorderCreate, PreorderResponse
from app.auth import require_role
from app.time_utils import utc_now

router = APIRouter(prefix="/api/user", tags=["user"])


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_km * (2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))

@router.get("/nearby-depots")
def get_nearby_depots(
    latitude: float,
    longitude: float,
    radius: float = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Obtenir les dépôts proches avec le stock"""
    from sqlalchemy import func
    
    # Formule de distance (approximation simple)
    depots = db.query(Depot).filter(
        Depot.is_active == True
    ).all()
    
    # Filtrer par rayon (distance approximée)
    nearby = []
    for depot in depots:
        distance = ((depot.latitude - latitude)**2 + (depot.longitude - longitude)**2)**0.5 * 111  # km
        if distance <= radius:
            nearby.append({
                "id": depot.id,
                "name": depot.name,
                "latitude": depot.latitude,
                "longitude": depot.longitude,
                "address": depot.address,
                "phone": depot.phone,
                "current_stock": float(depot.current_stock),
                "capacity": float(depot.capacity),
                "distance_km": round(distance, 2)
            })
    
    return sorted(nearby, key=lambda x: x["distance_km"])

@router.get("/recently-delivered-depots")
def get_recently_delivered_depots(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Obtenir les dépôts récemment livrés"""
    from sqlalchemy import desc
    from app.models import Delivery, DeliveryStatusEnum
    
    recently_delivered = db.query(Depot).join(
        Delivery, Delivery.destination_depot_id == Depot.id
    ).filter(
        Delivery.status == DeliveryStatusEnum.LIVREE
    ).order_by(
        desc(Delivery.actual_end)
    ).limit(10).all()
    
    return [{
        "id": d.id,
        "name": d.name,
        "latitude": d.latitude,
        "longitude": d.longitude,
        "address": d.address,
        "phone": d.phone,
        "current_stock": float(d.current_stock),
        "capacity": float(d.capacity)
    } for d in recently_delivered]

@router.get("/depot/{depot_id}")
def get_depot_details(
    depot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Obtenir les détails d'un dépôt"""
    depot = db.query(Depot).filter(Depot.id == depot_id, Depot.is_active == True).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    stock = db.query(Stock).filter(Stock.depot_id == depot_id).first()
    
    return {
        "id": depot.id,
        "name": depot.name,
        "latitude": depot.latitude,
        "longitude": depot.longitude,
        "address": depot.address,
        "phone": depot.phone,
        "current_stock": float(depot.current_stock),
        "capacity": float(depot.capacity),
        "is_low_stock": stock.is_low_stock if stock else False,
        "is_out_of_stock": stock.is_out_of_stock if stock else False
    }

@router.post("/preorder", response_model=PreorderResponse)
def create_preorder(
    preorder_data: PreorderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Faire une précommande"""
    depot = db.query(Depot).filter(Depot.id == preorder_data.depot_id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    # Créer la précommande
    new_preorder = Preorder(
        user_id=current_user.id,
        depot_id=preorder_data.depot_id,
        quantity=preorder_data.quantity,
        status=PreorderStatusEnum.ATTENTE
    )
    db.add(new_preorder)
    db.commit()
    db.refresh(new_preorder)
    
    return PreorderResponse.from_orm(new_preorder)

@router.get("/my-preorders", response_model=list[PreorderResponse])
def get_my_preorders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Voir mes précommandes"""
    preorders = db.query(Preorder).filter(
        Preorder.user_id == current_user.id
    ).order_by(Preorder.created_at.desc()).all()
    
    return [PreorderResponse.from_orm(p) for p in preorders]


@router.get("/delivery-near-alerts")
def get_delivery_near_alerts(
    threshold_km: float = 3.0,
    freshness_minutes: int = 45,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Retourner les livraisons proches d'un depot pour les precommandes actives du client."""
    active_preorders = db.query(Preorder).filter(
        Preorder.user_id == current_user.id,
        Preorder.status.in_([
            PreorderStatusEnum.ATTENTE,
            PreorderStatusEnum.CONFIRMEE,
        ]),
    ).order_by(Preorder.created_at.desc()).all()

    if not active_preorders:
        return {"alerts": [], "count": 0}

    recent_after = utc_now() - timedelta(minutes=freshness_minutes)
    preorder_ids_by_depot = {}
    for preorder in active_preorders:
        preorder_ids_by_depot.setdefault(preorder.depot_id, []).append(preorder.id)

    alerts = []
    for depot_id, preorder_ids in preorder_ids_by_depot.items():
        depot = db.query(Depot).filter(Depot.id == depot_id).first()
        if not depot or depot.latitude is None or depot.longitude is None:
            continue

        deliveries = db.query(Delivery).filter(
            Delivery.depot_id == depot.id,
            Delivery.driver_id.isnot(None),
            Delivery.status.in_([
                DeliveryStatusEnum.PENDING,
                DeliveryStatusEnum.IN_PROGRESS,
            ]),
        ).order_by(Delivery.scheduled_date.asc()).all()

        for delivery in deliveries:
            last_gps = db.query(GPSLog).filter(
                GPSLog.delivery_id == delivery.id,
                GPSLog.timestamp >= recent_after,
            ).order_by(GPSLog.timestamp.desc()).first()

            if not last_gps:
                last_gps = db.query(GPSLog).filter(
                    GPSLog.truck_id == delivery.truck_id,
                    GPSLog.timestamp >= recent_after,
                ).order_by(GPSLog.timestamp.desc()).first()

            if not last_gps:
                continue

            distance_km = _distance_km(
                last_gps.latitude,
                last_gps.longitude,
                depot.latitude,
                depot.longitude,
            )
            if distance_km > threshold_km:
                continue

            driver = db.query(User).filter(User.id == delivery.driver_id).first()
            truck = db.query(Truck).filter(Truck.id == delivery.truck_id).first()
            eta_minutes = max(1, round((distance_km / 30.0) * 60))
            alerts.append({
                "delivery_id": delivery.id,
                "depot_id": depot.id,
                "depot_name": depot.name,
                "distance_km": round(distance_km, 2),
                "eta_minutes": eta_minutes,
                "driver_name": driver.full_name if driver else None,
                "truck_plate": truck.license_plate if truck else None,
                "last_update": last_gps.timestamp.isoformat(),
                "preorder_ids": preorder_ids,
                "status": delivery.status.value,
            })

    alerts.sort(key=lambda item: (item["distance_km"], item["delivery_id"]))
    return {"alerts": alerts, "count": len(alerts)}

@router.get("/all-depots", response_model=list[DepotResponse])
def get_all_depots(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Obtenir tous les dépôts"""
    depots = db.query(Depot).filter(Depot.is_active == True).all()
    return [DepotResponse.from_orm(d) for d in depots]

@router.get("/satisfaction-history")
def get_satisfaction_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.USER))
):
    """Historique et satisfaction"""
    preorders = db.query(Preorder).filter(
        Preorder.user_id == current_user.id
    ).order_by(Preorder.created_at.desc()).limit(20).all()
    
    return [{
        "id": p.id,
        "depot_name": db.query(Depot).filter(Depot.id == p.depot_id).first().name,
        "quantity": float(p.quantity),
        "status": p.status,
        "created_at": p.created_at.isoformat(),
        "estimated_delivery": p.estimated_delivery.isoformat() if p.estimated_delivery else None
    } for p in preorders]