from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from datetime import datetime, timedelta
from typing import Optional
from app.database import get_db
from app.models import Depot, Delivery, DeliveryStatusEnum, NotificationSubscription
from pydantic import BaseModel, ConfigDict
from app.time_utils import utc_now
import math

router = APIRouter(prefix="/api/user/public", tags=["user-public"])

class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm(cls, obj):
        return cls.model_validate(obj)


# Schemas
class DepotPublicResponse(OrmModel):
    id: int
    name: str
    latitude: float
    longitude: float
    address: str
    phone: Optional[str]
    stock_6kg_plein: int
    stock_12kg_plein: int
    stock_6kg_vide: int
    stock_12kg_vide: int
    capacity_6kg: int
    capacity_12kg: int
    
class NotificationSubscriptionCreate(BaseModel):
    phone: str
    latitude: float
    longitude: float
    radius_km: int = 5
    bottle_type: str = "both"  # "6kg", "12kg", ou "both"

class NotificationSubscriptionResponse(OrmModel):
    id: int
    phone: str
    latitude: float
    longitude: float
    radius_km: int
    bottle_type: str
    is_active: bool
    created_at: datetime
    
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculer la distance en km entre deux points GPS (Formule de Haversine)"""
    R = 6371  # Rayon de la Terre en km
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

@router.get("/depots/nearest")
def get_nearest_depots_public(
    lat: float = Query(..., description="Latitude utilisateur"),
    lon: float = Query(..., description="Longitude utilisateur"),
    radius: float = Query(50, description="Rayon de recherche en km"),
    db: Session = Depends(get_db)
):
    """
    Récupérer les dépôts proches de la position utilisateur
    SANS AUTHENTIFICATION - Backend calcule la distance
    """
    # Récupérer tous les dépôts actifs
    depots = db.query(Depot).filter(Depot.is_active == True).all()
    
    # Calculer la distance et filtrer
    nearby_depots = []
    for depot in depots:
        distance = calculate_distance(lat, lon, depot.latitude, depot.longitude)
        if distance <= radius:
            depot_data = {
                "id": depot.id,
                "name": depot.name,
                "latitude": depot.latitude,
                "longitude": depot.longitude,
                "address": depot.address,
                "phone": depot.phone,
                "stock_6kg_plein": depot.stock_6kg_plein,
                "stock_12kg_plein": depot.stock_12kg_plein,
                "stock_6kg_vide": depot.stock_6kg_vide,
                "stock_12kg_vide": depot.stock_12kg_vide,
                "capacity_6kg": depot.capacity_6kg,
                "capacity_12kg": depot.capacity_12kg,
                "distance_km": round(distance, 2)
            }
            nearby_depots.append(depot_data)
    
    # Trier par distance
    nearby_depots.sort(key=lambda x: x["distance_km"])
    
    return nearby_depots

@router.get("/depots/{depot_id}")
def get_depot_details_public(
    depot_id: int,
    db: Session = Depends(get_db)
):
    """Obtenir les détails d'un dépôt SANS AUTHENTIFICATION"""
    depot = db.query(Depot).filter(
        Depot.id == depot_id,
        Depot.is_active == True
    ).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    return {
        "id": depot.id,
        "name": depot.name,
        "latitude": depot.latitude,
        "longitude": depot.longitude,
        "address": depot.address,
        "phone": depot.phone,
        "stock_6kg_plein": depot.stock_6kg_plein,
        "stock_12kg_plein": depot.stock_12kg_plein,
        "stock_6kg_vide": depot.stock_6kg_vide,
        "stock_12kg_vide": depot.stock_12kg_vide,
        "capacity_6kg": depot.capacity_6kg,
        "capacity_12kg": depot.capacity_12kg
    }

@router.get("/depots/recently-delivered")
def get_recently_delivered_depots_public(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    hours: int = Query(24, description="Nombre d'heures en arrière"),
    db: Session = Depends(get_db)
):
    """
    Récupérer les dépôts récemment livrés (dernières X heures)
    SANS AUTHENTIFICATION
    """
    cutoff_time = utc_now() - timedelta(hours=hours)
    
    # Trouver les livraisons complétées récemment
    recent_deliveries = db.query(Delivery).filter(
        Delivery.status == DeliveryStatusEnum.COMPLETED,
        Delivery.actual_end >= cutoff_time
    ).all()
    
    # Récupérer les dépôts uniques
    depot_ids = set([d.depot_id for d in recent_deliveries if d.depot_id])
    depots = db.query(Depot).filter(Depot.id.in_(depot_ids)).all()
    
    result = []
    for depot in depots:
        depot_data = {
            "id": depot.id,
            "name": depot.name,
            "latitude": depot.latitude,
            "longitude": depot.longitude,
            "address": depot.address,
            "phone": depot.phone,
            "stock_6kg_plein": depot.stock_6kg_plein,
            "stock_12kg_plein": depot.stock_12kg_plein,
            "capacity_6kg": depot.capacity_6kg,
            "capacity_12kg": depot.capacity_12kg
        }
        
        # Ajouter distance si position fournie
        if lat and lon:
            distance = calculate_distance(lat, lon, depot.latitude, depot.longitude)
            depot_data["distance_km"] = round(distance, 2)
        
        result.append(depot_data)
    
    # Trier par distance si fournie, sinon par nom
    if lat and lon:
        result.sort(key=lambda x: x.get("distance_km", 999))
    else:
        result.sort(key=lambda x: x["name"])
    
    return result

@router.post("/notifications/subscribe", response_model=NotificationSubscriptionResponse)
def subscribe_to_notifications(
    subscription: NotificationSubscriptionCreate,
    db: Session = Depends(get_db)
):
    """
    S'abonner aux notifications de livraison
    SANS AUTHENTIFICATION - Utilise le numéro de téléphone
    """
    # Valider le type de bouteille
    if subscription.bottle_type not in ["6kg", "12kg", "both"]:
        raise HTTPException(
            status_code=400,
            detail="Type de bouteille invalide. Utilisez '6kg', '12kg' ou 'both'"
        )
    
    # Créer l'abonnement
    new_subscription = NotificationSubscription(
        phone=subscription.phone,
        latitude=subscription.latitude,
        longitude=subscription.longitude,
        radius_km=subscription.radius_km,
        bottle_type=subscription.bottle_type,
        is_active=True
    )
    
    db.add(new_subscription)
    db.commit()
    db.refresh(new_subscription)
    
    return new_subscription

@router.get("/notifications/my-subscriptions")
def get_my_subscriptions(
    phone: str = Query(..., description="Numéro de téléphone"),
    db: Session = Depends(get_db)
):
    """
    Récupérer mes abonnements aux notifications
    SANS AUTHENTIFICATION - Utilise le numéro de téléphone
    """
    subscriptions = db.query(NotificationSubscription).filter(
        NotificationSubscription.phone == phone,
        NotificationSubscription.is_active == True
    ).all()
    
    return [{
        "id": sub.id,
        "radius_km": sub.radius_km,
        "bottle_type": sub.bottle_type,
        "created_at": sub.created_at.isoformat()
    } for sub in subscriptions]

@router.delete("/notifications/unsubscribe/{subscription_id}")
def unsubscribe_from_notifications(
    subscription_id: int,
    phone: str = Query(..., description="Numéro de téléphone pour vérification"),
    db: Session = Depends(get_db)
):
    """
    Se désabonner des notifications
    SANS AUTHENTIFICATION - Vérifie le numéro de téléphone
    """
    subscription = db.query(NotificationSubscription).filter(
        NotificationSubscription.id == subscription_id,
        NotificationSubscription.phone == phone
    ).first()
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")
    
    subscription.is_active = False
    db.commit()
    
    return {"message": "Désabonnement réussi"}

# Fonction helper pour vérifier les livraisons et envoyer notifications (sera appelée par un job/webhook)
def check_and_notify_deliveries(db: Session):
    """
    Vérifier les nouvelles livraisons et envoyer des notifications
    Cette fonction devrait être appelée par un job périodique ou un webhook
    """
    # Récupérer les livraisons complétées dans les dernières 5 minutes
    cutoff_time = utc_now() - timedelta(minutes=5)
    recent_deliveries = db.query(Delivery).filter(
        Delivery.status == DeliveryStatusEnum.COMPLETED,
        Delivery.actual_end >= cutoff_time
    ).all()
    
    # Pour chaque livraison, trouver les abonnements concernés
    for delivery in recent_deliveries:
        if not delivery.depot_id:
            continue
            
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        if not depot:
            continue
        
        # Trouver les abonnements dans le rayon
        subscriptions = db.query(NotificationSubscription).filter(
            NotificationSubscription.is_active == True
        ).all()
        
        for sub in subscriptions:
            distance = calculate_distance(
                sub.latitude, sub.longitude,
                depot.latitude, depot.longitude
            )
            
            if distance <= sub.radius_km:
                # Vérifier le type de bouteille
                notify = False
                if sub.bottle_type == "both":
                    notify = True
                elif sub.bottle_type == "6kg" and delivery.quantity_6kg > 0:
                    notify = True
                elif sub.bottle_type == "12kg" and delivery.quantity_12kg > 0:
                    notify = True
                
                if notify:
                    # Dans une vraie application, envoyer SMS/Push notification
                    print(f"🔔 Notification à {sub.phone}: Dépôt {depot.name} livré ({distance:.1f}km)")
    
    return {"message": "Notifications vérifiées"}
