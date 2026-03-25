import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Depot, Delivery, Preorder, Stock, Truck, RoleEnum, DeliveryStatusEnum, PreorderStatusEnum, StockMovement, MovementTypeEnum, BottleTypeEnum
from app.schemas import DeliveryResponse, PreorderResponse, StockResponse
from app.auth import require_role, create_access_token, verify_password
from app.time_utils import utc_now, utc_now_iso
from app.websocket_manager import manager

router = APIRouter(prefix="/api/depot", tags=["depot"])


def _broadcast(message: dict) -> None:
    asyncio.run(manager.broadcast_to_all(message))

# Schemas pour les requêtes
class LoginRequest(BaseModel):
    email: str
    password: str

class CancelPreorderRequest(BaseModel):
    reason: str


class AssignDeliveryRequest(BaseModel):
    driver_id: int

# Schéma pour création dépôt + user
class CreateDepotUserRequest(BaseModel):
    """Schéma de création d'un dépôt + utilisateur gestionnaire.

    Pour rester compatible avec les différentes versions de front/back,
    on accepte à la fois:
    - capacity_6kg / capacity_12kg (capacités par type de bouteille)
    - depot_capacity (capacité globale unique)
    """

    depot_name: str
    depot_address: str
    depot_phone: str
    depot_latitude: float
    depot_longitude: float
    # Capacités détaillées (optionnelles pour compatibilité)
    capacity_6kg: Optional[float] = None
    capacity_12kg: Optional[float] = None
    # Capacité globale (optionnelle, utilisée en fallback)
    depot_capacity: Optional[float] = None
    # Infos utilisateur gestionnaire
    user_email: str
    user_password: str
    user_full_name: str

# Authentification
@router.post("/login")
def depot_login(request: LoginRequest, db: Session = Depends(get_db)):
    """Connexion gestionnaire de dépôt"""
    user = db.query(User).filter(
        User.email == request.email,
        User.role == RoleEnum.DEPOT
    ).first()
    
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    depot = db.query(Depot).filter(Depot.manager_id == user.id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Aucun dépôt associé à ce compte")
    
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    
    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.full_name,
            "role": user.role.value,
            "depot_id": depot.id,
            "depot_name": depot.name
        }
    }

# Endpoint pour créer un dépôt et un user associé
@router.post("/create")
def create_depot_and_user(request: CreateDepotUserRequest, db: Session = Depends(get_db)):
    """Créer un dépôt et un utilisateur associé automatiquement"""

    # DEBUG: Affiche le modèle et les champs reçus
    print("DEBUG FASTAPI - Modèle reçu:", type(request))
    try:
        print("DEBUG FASTAPI - Champs reçus:", request.dict())
    except Exception as e:
        print("DEBUG FASTAPI - Erreur lors du dict():", e)

    # Vérifier si l'email existe déjà
    if db.query(User).filter(User.email == request.user_email).first():
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    # Créer l'utilisateur
    from app.auth import hash_password
    hashed_pw = hash_password(request.user_password)
    user = User(
        email=request.user_email,
        hashed_password=hashed_pw,
        full_name=request.user_full_name,
        role=RoleEnum.DEPOT,
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Déterminer les capacités 6kg / 12kg à partir des champs reçus
    cap_6kg = request.capacity_6kg
    cap_12kg = request.capacity_12kg

    # Si les capacités détaillées ne sont pas fournies mais qu'on a une
    # capacité globale, on la répartit simplement à 50/50.
    if cap_6kg is None and cap_12kg is None and request.depot_capacity is not None:
        half = float(request.depot_capacity) / 2.0
        cap_6kg = half
        cap_12kg = half

    # Valeurs par défaut à 0 si toujours None
    cap_6kg = float(cap_6kg or 0)
    cap_12kg = float(cap_12kg or 0)

    # Créer le dépôt
    depot = Depot(
        name=request.depot_name,
        address=request.depot_address,
        phone=request.depot_phone,
        latitude=request.depot_latitude,
        longitude=request.depot_longitude,
        capacity_6kg=cap_6kg,
        capacity_12kg=cap_12kg,
        manager_id=user.id
    )
    db.add(depot)
    db.commit()
    db.refresh(depot)

    return {
        "status": "ok",
        "user_id": user.id,
        "depot_id": depot.id,
        "depot_name": depot.name,
        "user_email": user.email
    }

@router.get("/me")
def get_current_depot_user(
    current_user: User = Depends(require_role(RoleEnum.DEPOT)),
    db: Session = Depends(get_db)
):
    """Obtenir les informations de l'utilisateur connecté"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.full_name,
        "role": current_user.role.value,
        "depot_id": depot.id if depot else None,
        "depot_name": depot.name if depot else None
    }

@router.get("/info")
def get_depot_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir les infos du dépôt"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    stock = db.query(Stock).filter(Stock.depot_id == depot.id).first()
    
    return {
        "id": depot.id,
        "name": depot.name,
        "latitude": depot.latitude,
        "longitude": depot.longitude,
        "capacity": float((depot.capacity_6kg or 0) + (depot.capacity_12kg or 0)),
        "current_stock": float((depot.stock_6kg_plein or 0) + (depot.stock_12kg_plein or 0)),
        "address": depot.address,
        "phone": depot.phone,
        "is_low_stock": stock.is_low_stock if stock else False,
        "is_out_of_stock": stock.is_out_of_stock if stock else False
    }

@router.get("/scheduled-deliveries", response_model=list[DeliveryResponse])
def get_scheduled_deliveries(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Voir les livraisons programmées"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    deliveries = db.query(Delivery).filter(
        Delivery.depot_id == depot.id,
        Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
    ).all()
    
    return [DeliveryResponse.from_orm(d) for d in deliveries]

@router.get("/preorders", response_model=list[PreorderResponse])
def get_preorders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Voir les précommandes des utilisateurs"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    preorders = db.query(Preorder).filter(
        Preorder.depot_id == depot.id,
        Preorder.status == PreorderStatusEnum.ATTENTE
    ).all()
    
    return [PreorderResponse.from_orm(p) for p in preorders]

@router.put("/declare-low-stock")
async def declare_low_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Déclarer un stock faible"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    stock = db.query(Stock).filter(Stock.depot_id == depot.id).first()
    if stock:
        stock.is_low_stock = True
    
    db.commit()
    
    await manager.broadcast_to_all({
        "type": "depot_low_stock",
        "depot_id": depot.id,
        "depot_name": depot.name
    })
    
    return {"status": "ok", "message": "Stock faible déclaré"}

@router.put("/declare-out-of-stock")
async def declare_out_of_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Déclarer une rupture"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    stock = db.query(Stock).filter(Stock.depot_id == depot.id).first()
    if stock:
        stock.is_out_of_stock = True
        stock.is_low_stock = False
    
    db.commit()
    
    await manager.broadcast_to_all({
        "type": "depot_out_of_stock",
        "depot_id": depot.id,
        "depot_name": depot.name
    })
    
    return {"status": "ok", "message": "Rupture déclarée"}

@router.put("/declare-restocked")
async def declare_restocked(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Déclarer réalimentation"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    stock = db.query(Stock).filter(Stock.depot_id == depot.id).first()
    if stock:
        stock.is_out_of_stock = False
        stock.is_low_stock = False
    
    db.commit()
    
    await manager.broadcast_to_all({
        "type": "depot_restocked",
        "depot_id": depot.id,
        "depot_name": depot.name
    })
    
    return {"status": "ok", "message": "Dépôt réapprovisionné"}

@router.get("/stock", response_model=StockResponse)
def get_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir l'état du stock"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    stock = db.query(Stock).filter(Stock.depot_id == depot.id).first()
    
    if not stock:
        raise HTTPException(status_code=404, detail="Stock introuvable")
    
    return StockResponse.from_orm(stock)

# Nouveaux endpoints pour le Panel Dépôt

@router.get("/my-depot")
def get_my_depot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir les informations complètes du dépôt avec stock"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    return {
        "id": depot.id,
        "name": depot.name,
        "address": depot.address,
        "phone": depot.phone,
        "latitude": float(depot.latitude),
        "longitude": float(depot.longitude),
        "stock_6kg_plein": depot.stock_6kg_plein,
        "stock_6kg_vide": depot.stock_6kg_vide,
        "stock_12kg_plein": depot.stock_12kg_plein,
        "stock_12kg_vide": depot.stock_12kg_vide,
        "capacity_6kg": depot.capacity_6kg,
        "capacity_12kg": depot.capacity_12kg
    }

@router.get("/stats")
def get_depot_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir les statistiques du dépôt"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    # Compter les livraisons en attente
    pending_deliveries = db.query(Delivery).filter(
        Delivery.depot_id == depot.id,
        Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
    ).count()
    
    # Compter les précommandes en attente
    pending_preorders = db.query(Preorder).filter(
        Preorder.depot_id == depot.id,
        Preorder.status == PreorderStatusEnum.ATTENTE
    ).count()
    
    return {
        "pending_deliveries": pending_deliveries,
        "pending_preorders": pending_preorders
    }

@router.get("/pending-deliveries")
def get_pending_deliveries(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir les livraisons en attente de confirmation"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    deliveries = db.query(Delivery).filter(
        Delivery.depot_id == depot.id,
        Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
    ).order_by(Delivery.created_at.desc()).all()
    
    result = []
    for delivery in deliveries:
        driver = db.query(User).filter(User.id == delivery.driver_id).first() if delivery.driver_id else None
        result.append({
            "id": delivery.id,
            "status": delivery.status.value,
            "quantity_6kg_plein": delivery.quantity_6kg or 0,
            "quantity_6kg_vide": delivery.quantity_6kg_vide_recupere or 0,
            "quantity_12kg_plein": delivery.quantity_12kg or 0,
            "quantity_12kg_vide": delivery.quantity_12kg_vide_recupere or 0,
            "notes": delivery.notes,
            "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
            "driver_name": driver.full_name if driver else None
        })
    
    return result


@router.get("/available-drivers")
def get_available_drivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Lister les ravitailleurs pouvant recevoir une mission depuis ce depot."""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()

    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")

    drivers = db.query(User).filter(
        User.role == RoleEnum.RAVITAILLEUR,
        User.is_active == True,
    ).order_by(User.full_name.asc()).all()

    result = []
    for driver in drivers:
        truck = db.query(Truck).filter(
            Truck.driver_id == driver.id,
            Truck.is_active == True,
        ).first()
        if not truck:
            continue

        active_deliveries = db.query(Delivery).filter(
            Delivery.driver_id == driver.id,
            Delivery.status.in_([
                DeliveryStatusEnum.PENDING,
                DeliveryStatusEnum.IN_PROGRESS,
            ]),
        ).count()

        result.append({
            "id": driver.id,
            "full_name": driver.full_name,
            "email": driver.email,
            "truck_id": truck.id,
            "truck_plate": truck.license_plate,
            "current_pending_deliveries": active_deliveries,
        })

    return result


@router.post("/assign-delivery/{delivery_id}")
def assign_delivery_to_driver(
    delivery_id: int,
    request: AssignDeliveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Affecter une livraison du depot a un ravitailleur disposant d'un camion."""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()

    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")

    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.depot_id == depot.id,
    ).first()

    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")

    if delivery.status == DeliveryStatusEnum.COMPLETED:
        raise HTTPException(status_code=400, detail="Impossible d'affecter une livraison déjà terminée")

    driver = db.query(User).filter(
        User.id == request.driver_id,
        User.role == RoleEnum.RAVITAILLEUR,
        User.is_active == True,
    ).first()

    if not driver:
        raise HTTPException(status_code=404, detail="Ravitailleur introuvable")

    truck = db.query(Truck).filter(
        Truck.driver_id == driver.id,
        Truck.is_active == True,
    ).first()

    if not truck:
        raise HTTPException(status_code=400, detail="Aucun camion actif associé à ce ravitailleur")

    delivery.driver_id = driver.id
    delivery.truck_id = truck.id
    delivery.notes = (
        f"{delivery.notes}\n" if delivery.notes else ""
    ) + f"Affectée par {current_user.full_name} le {utc_now_iso()}"

    db.commit()
    db.refresh(delivery)

    _broadcast({
        "type": "delivery_assigned",
        "delivery_id": delivery.id,
        "depot_id": depot.id,
        "driver_id": driver.id,
        "truck_id": truck.id,
    })

    return {
        "status": "ok",
        "delivery": {
            "id": delivery.id,
            "driver_id": driver.id,
            "driver_name": driver.full_name,
            "truck_id": truck.id,
            "truck_plate": truck.license_plate,
            "status": delivery.status.value,
        },
    }

@router.post("/confirm-delivery/{delivery_id}")
async def confirm_delivery_reception(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Confirmer la réception d'une livraison"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    delivery = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.depot_id == depot.id
    ).first()
    
    if not delivery:
        raise HTTPException(status_code=404, detail="Livraison introuvable")
    
    if delivery.status == DeliveryStatusEnum.COMPLETED:
        raise HTTPException(status_code=400, detail="Livraison déjà confirmée")
    
    # Mettre à jour le stock du dépôt
    depot.stock_6kg_plein += delivery.quantity_6kg or 0
    depot.stock_6kg_vide += delivery.quantity_6kg_vide_recupere or 0
    depot.stock_12kg_plein += delivery.quantity_12kg or 0
    depot.stock_12kg_vide += delivery.quantity_12kg_vide_recupere or 0
    
    # Marquer la livraison comme livrée
    delivery.status = DeliveryStatusEnum.COMPLETED
    delivery.actual_end = datetime.now()
    
    # Créer un mouvement de stock
    movement = StockMovement(
        depot_id=depot.id,
        type=MovementTypeEnum.RECEPTION,
        quantity_6kg_plein=delivery.quantity_6kg or 0,
        quantity_6kg_vide=delivery.quantity_6kg_vide_recupere or 0,
        quantity_12kg_plein=delivery.quantity_12kg or 0,
        quantity_12kg_vide=delivery.quantity_12kg_vide_recupere or 0,
        description=f"Réception livraison #{delivery.id}",
        created_by_id=current_user.id
    )
    db.add(movement)
    
    db.commit()
    
    # Notifier via websocket
    await manager.broadcast_to_all({
        "type": "delivery_confirmed",
        "delivery_id": delivery.id,
        "depot_id": depot.id
    })
    
    return {"status": "ok", "message": "Livraison confirmée"}

@router.get("/preorders-list")
def get_preorders_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir la liste complète des précommandes"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    preorders = db.query(Preorder).filter(
        Preorder.depot_id == depot.id
    ).order_by(Preorder.created_at.desc()).all()
    
    # Grouper les précommandes par user_id et calculer les quantités par type
    preorders_grouped = {}
    for preorder in preorders:
        if preorder.id not in preorders_grouped:
            user = db.query(User).filter(User.id == preorder.user_id).first()
            preorders_grouped[preorder.id] = {
                "id": preorder.id,
                "status": preorder.status.value,
                "quantity_6kg": 0,
                "quantity_12kg": 0,
                "notes": None,
                "cancel_reason": None,
                "created_at": preorder.created_at.isoformat() if preorder.created_at else None,
                "user_name": user.full_name if user else "Client",
                "user_phone": None  # Pas de champ phone dans le modèle User
            }
        
        # Ajouter la quantité selon le type
        if preorder.bottle_type == BottleTypeEnum.B6KG:
            preorders_grouped[preorder.id]["quantity_6kg"] = preorder.quantity
        elif preorder.bottle_type == BottleTypeEnum.B12KG:
            preorders_grouped[preorder.id]["quantity_12kg"] = preorder.quantity
    
    return list(preorders_grouped.values())

@router.post("/confirm-preorder/{preorder_id}")
async def confirm_preorder_action(
    preorder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Confirmer une précommande"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    preorder = db.query(Preorder).filter(
        Preorder.id == preorder_id,
        Preorder.depot_id == depot.id
    ).first()
    
    if not preorder:
        raise HTTPException(status_code=404, detail="Précommande introuvable")
    
    if preorder.status != PreorderStatusEnum.ATTENTE:
        raise HTTPException(status_code=400, detail="Précommande déjà traitée")
    
    # Vérifier le stock disponible selon le type de bouteille
    if preorder.bottle_type == BottleTypeEnum.B6KG:
        if depot.stock_6kg_plein < preorder.quantity:
            raise HTTPException(status_code=400, detail="Stock insuffisant pour bouteilles 6kg")
    elif preorder.bottle_type == BottleTypeEnum.B12KG:
        if depot.stock_12kg_plein < preorder.quantity:
            raise HTTPException(status_code=400, detail="Stock insuffisant pour bouteilles 12kg")
    
    # Mettre à jour le statut
    preorder.status = PreorderStatusEnum.CONFIRMEE
    preorder.confirmed_at = datetime.now()
    preorder.confirmed_by_id = current_user.id
    
    db.commit()
    
    # Notifier l'utilisateur
    await manager.broadcast_to_all({
        "type": "preorder_confirmed",
        "preorder_id": preorder.id,
        "user_id": preorder.user_id
    })
    
    return {"status": "ok", "message": "Précommande confirmée"}

@router.post("/cancel-preorder/{preorder_id}")
async def cancel_preorder_action(
    preorder_id: int,
    request: CancelPreorderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Annuler une précommande"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    preorder = db.query(Preorder).filter(
        Preorder.id == preorder_id,
        Preorder.depot_id == depot.id
    ).first()
    
    if not preorder:
        raise HTTPException(status_code=404, detail="Précommande introuvable")
    
    if preorder.status != PreorderStatusEnum.ATTENTE:
        raise HTTPException(status_code=400, detail="Précommande déjà traitée")
    
    preorder.status = PreorderStatusEnum.ANNULEE
    preorder.cancel_reason = request.reason
    preorder.cancelled_at = datetime.now()
    
    db.commit()
    
    # Notifier l'utilisateur
    await manager.broadcast_to_all({
        "type": "preorder_cancelled",
        "preorder_id": preorder.id,
        "user_id": preorder.user_id,
        "reason": request.reason
    })
    
    return {"status": "ok", "message": "Précommande annulée"}

@router.get("/history")
def get_depot_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.DEPOT))
):
    """Obtenir l'historique des mouvements de stock"""
    depot = db.query(Depot).filter(Depot.manager_id == current_user.id).first()
    
    if not depot:
        raise HTTPException(status_code=404, detail="Dépôt introuvable")
    
    movements = db.query(StockMovement).filter(
        StockMovement.depot_id == depot.id
    ).order_by(StockMovement.created_at.desc()).limit(100).all()
    
    result = []
    for movement in movements:
        user = db.query(User).filter(User.id == movement.created_by_id).first() if movement.created_by_id else None
        result.append({
            "id": movement.id,
            "type": movement.type.value,
            "quantity_6kg_plein": movement.quantity_6kg_plein or 0,
            "quantity_6kg_vide": movement.quantity_6kg_vide or 0,
            "quantity_12kg_plein": movement.quantity_12kg_plein or 0,
            "quantity_12kg_vide": movement.quantity_12kg_vide or 0,
            "description": movement.description,
            "created_at": movement.created_at.isoformat() if movement.created_at else None,
            "user_name": user.full_name if user else None
        })
    
    return result