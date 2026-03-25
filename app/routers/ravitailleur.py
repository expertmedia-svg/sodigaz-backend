from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import User, Delivery, GPSLog, Truck, RoleEnum, DeliveryStatusEnum
from app.schemas import DeliveryResponse, GPSLogCreate, GPSLogResponse
from app.auth import require_role, get_current_user
from app.time_utils import utc_now
from app.websocket_manager import manager

router = APIRouter(prefix="/api/ravitailleur", tags=["ravitailleur"])

@router.get("/today-deliveries", response_model=list[DeliveryResponse])
def get_today_deliveries(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.RAVITAILLEUR))
):
    """Voir les livraisons prévues pour aujourd'hui"""
    today = utc_now().date()
    
    deliveries = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.scheduled_date >= datetime(today.year, today.month, today.day),
        Delivery.scheduled_date < datetime(today.year, today.month, today.day + 1) if today.day < 28 else datetime(today.year, today.month + 1, 1)
    ).all()
    
    return [DeliveryResponse.from_orm(d) for d in deliveries]

@router.put("/start-delivery/{delivery_id}")
async def start_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.RAVITAILLEUR))
):
    """Démarrer une livraison"""
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.driver_id == current_user.id
    ).first()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")
    
    delivery.status = DeliveryStatusEnum.EN_COURS
    delivery.actual_start = utc_now()
    
    db.commit()
    db.refresh(delivery)
    
    await manager.broadcast_to_all({
        "type": "delivery_started",
        "delivery_id": delivery.id,
        "truck_id": delivery.truck_id
    })
    
    return {"status": "ok", "delivery_id": delivery.id}

@router.put("/confirm-delivery/{delivery_id}")
async def confirm_delivery(
    delivery_id: int,
    end_latitude: float,
    end_longitude: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.RAVITAILLEUR))
):
    """Confirmer l'arrivée à la destination"""
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.driver_id == current_user.id
    ).first()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")
    
    delivery.status = DeliveryStatusEnum.LIVREE
    delivery.actual_end = utc_now()
    delivery.end_latitude = end_latitude
    delivery.end_longitude = end_longitude
    
    # Mettre à jour le stock du dépôt
    depot = db.query(Depot).filter(Depot.id == delivery.destination_depot_id).first()
    if depot:
        depot.current_stock = float(depot.current_stock) + float(delivery.quantity)
    
    db.commit()
    db.refresh(delivery)
    
    await manager.broadcast_to_all({
        "type": "delivery_completed",
        "delivery_id": delivery.id,
        "depot_id": delivery.destination_depot_id,
        "quantity": float(delivery.quantity)
    })
    
    return {"status": "ok", "message": "Livraison confirmée"}

@router.post("/gps-update")
async def send_gps_update(
    gps_data: GPSLogCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.RAVITAILLEUR))
):
    """Envoyer les mises à jour GPS en continu"""
    
    # Vérifier que le camion appartient au chauffeur
    truck = db.query(Truck).filter(
        Truck.id == gps_data.truck_id,
        Truck.driver_id == current_user.id
    ).first()
    
    if not truck:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    # Enregistrer le log GPS
    gps_log = GPSLog(
        truck_id=gps_data.truck_id,
        delivery_id=gps_data.delivery_id,
        latitude=gps_data.latitude,
        longitude=gps_data.longitude,
        accuracy=gps_data.accuracy
    )
    db.add(gps_log)
    db.commit()
    db.refresh(gps_log)
    
    # Broadcast en temps réel
    await manager.broadcast_to_all({
        "type": "gps_update",
        "truck_id": gps_data.truck_id,
        "latitude": gps_data.latitude,
        "longitude": gps_data.longitude,
        "timestamp": gps_log.timestamp.isoformat()
    })
    
    return GPSLogResponse.from_orm(gps_log)

@router.get("/truck-info")
def get_truck_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.RAVITAILLEUR))
):
    """Obtenir les infos du camion du chauffeur"""
    truck = db.query(Truck).filter(Truck.driver_id == current_user.id).first()
    
    if not truck:
        raise HTTPException(status_code=404, detail="Camion introuvable")
    
    return {
        "id": truck.id,
        "license_plate": truck.license_plate,
        "capacity": float(truck.capacity),
        "current_load": float(truck.current_load)
    }

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    """WebSocket pour les mises à jour en temps réel"""
    await manager.connect(f"ravitailleur_{user_id}", websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except:
        manager.disconnect(f"ravitailleur_{user_id}", websocket)