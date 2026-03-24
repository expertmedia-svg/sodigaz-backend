from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import GPSLog, Delivery, Truck, User, Depot, DeliveryStatusEnum, RoleEnum
from app.auth import get_current_user
from pydantic import BaseModel
from typing import List, Optional
from app.time_utils import utc_now
import math

router = APIRouter()

class GPSPosition(BaseModel):
    latitude: float
    longitude: float

class ActiveDeliveryTracking(BaseModel):
    delivery_id: int
    driver_name: str
    truck_plate: str
    status: str
    destination_depot: str
    depot_latitude: float
    depot_longitude: float
    current_latitude: Optional[float]
    current_longitude: Optional[float]
    distance_to_depot: Optional[float]
    quantity_6kg: int
    quantity_12kg: int
    last_update: Optional[str]

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcule la distance en mètres entre deux coordonnées GPS"""
    R = 6371000  # Rayon de la Terre en mètres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

@router.get("/depot/{depot_id}/active-deliveries", response_model=List[ActiveDeliveryTracking])
def get_depot_active_deliveries(
    depot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupère toutes les livraisons actives vers un dépôt avec position GPS"""
    
    # Vérifier que l'utilisateur est un dépôt
    if current_user.role != RoleEnum.DEPOT:
        raise HTTPException(status_code=403, detail="Accès réservé aux dépôts")
    
    # Récupérer le dépôt
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    # Récupérer les livraisons en cours vers ce dépôt
    deliveries = db.query(Delivery).filter(
        Delivery.depot_id == depot_id,
        Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
    ).all()
    
    result = []
    for delivery in deliveries:
        # Récupérer le chauffeur et le camion
        driver = db.query(User).filter(User.id == delivery.driver_id).first()
        truck = db.query(Truck).filter(Truck.id == delivery.truck_id).first()
        
        # Récupérer la dernière position GPS (dans les 5 dernières minutes)
        five_min_ago = utc_now() - timedelta(minutes=5)
        last_gps = db.query(GPSLog).filter(
            GPSLog.truck_id == delivery.truck_id,
            GPSLog.timestamp >= five_min_ago
        ).order_by(GPSLog.timestamp.desc()).first()
        
        # Calculer la distance si position GPS disponible
        distance = None
        if last_gps and depot.latitude and depot.longitude:
            distance = calculate_distance(
                last_gps.latitude,
                last_gps.longitude,
                depot.latitude,
                depot.longitude
            )
        
        result.append(ActiveDeliveryTracking(
            delivery_id=delivery.id,
            driver_name=driver.full_name if driver else "Inconnu",
            truck_plate=truck.license_plate if truck else "Inconnu",
            status=delivery.status.value,
            destination_depot=depot.name,
            depot_latitude=depot.latitude,
            depot_longitude=depot.longitude,
            current_latitude=last_gps.latitude if last_gps else None,
            current_longitude=last_gps.longitude if last_gps else None,
            distance_to_depot=distance,
            quantity_6kg=delivery.quantity_6kg or 0,
            quantity_12kg=delivery.quantity_12kg or 0,
            last_update=last_gps.timestamp.isoformat() if last_gps else None
        ))
    
    # Trier par distance (les plus proches en premier)
    result.sort(key=lambda x: x.distance_to_depot if x.distance_to_depot else float('inf'))
    
    return result

@router.post("/driver/update-position")
def update_driver_position(
    position: GPSPosition,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mise à jour de la position GPS du ravitailleur"""
    
    if current_user.role != RoleEnum.RAVITAILLEUR:
        raise HTTPException(status_code=403, detail="Accès réservé aux ravitailleurs")
    
    # Trouver la livraison active du chauffeur
    active_delivery = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.status == DeliveryStatusEnum.IN_PROGRESS
    ).first()
    
    if not active_delivery:
        raise HTTPException(status_code=404, detail="Aucune livraison active")
    
    # Enregistrer la position GPS
    gps_log = GPSLog(
        truck_id=active_delivery.truck_id,
        delivery_id=active_delivery.id,
        latitude=position.latitude,
        longitude=position.longitude,
        timestamp=utc_now()
    )
    db.add(gps_log)
    db.commit()
    
    return {"message": "Position mise à jour", "timestamp": gps_log.timestamp.isoformat()}

@router.get("/user/nearby-deliveries")
def get_nearby_deliveries(
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupère les livraisons récentes dans un rayon donné pour notification utilisateur"""
    
    if current_user.role != RoleEnum.USER:
        raise HTTPException(status_code=403, detail="Accès réservé aux utilisateurs")
    
    # Récupérer les livraisons complétées dans les 30 dernières minutes
    thirty_min_ago = utc_now() - timedelta(minutes=30)
    recent_deliveries = db.query(Delivery).filter(
        Delivery.status == DeliveryStatusEnum.COMPLETED,
        Delivery.actual_end >= thirty_min_ago
    ).all()
    
    nearby = []
    for delivery in recent_deliveries:
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        if not depot or not depot.latitude or not depot.longitude:
            continue
        
        # Calculer la distance
        distance = calculate_distance(latitude, longitude, depot.latitude, depot.longitude)
        distance_km = distance / 1000
        
        if distance_km <= radius_km:
            nearby.append({
                "depot_id": depot.id,
                "depot_name": depot.name,
                "depot_address": depot.address,
                "distance_km": round(distance_km, 2),
                "quantity_6kg": delivery.quantity_6kg or 0,
                "quantity_12kg": delivery.quantity_12kg or 0,
                "delivered_at": delivery.actual_end.isoformat(),
                "latitude": depot.latitude,
                "longitude": depot.longitude
            })
    
    # Trier par distance
    nearby.sort(key=lambda x: x["distance_km"])
    
    return {
        "notifications": nearby,
        "count": len(nearby)
    }
