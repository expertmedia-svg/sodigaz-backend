"""
Service de gestion de l'intégration Sage X3

Gère:
- Réception des missions Sage X3
- Validation des authentifications  
- Création de deliveries à partir des missions
- Approbation/rejet des missions
- Synchronisation des statuts
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import (
    Delivery,
    SageMissionStatusEnum,
    User,
    Truck,
    DeliveryStatusEnum
)
from app.schemas import SageMissionInbound, SageMissionResponse
from app.time_utils import utc_now
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class SageX3Service:
    """Service pour gérer les intégrations Sage X3"""
    
    def __init__(self, db: Session):
        self.db = db
        self.mock_mode = settings.SAGE_X3_MOCK_MODE
        self.sage_token = settings.SAGE_X3_PUSH_TOKEN
        logger.info(f"🔌 SageX3Service initialized (mock_mode={self.mock_mode})")
    
    def validate_sage_token(self, token: str) -> bool:
        """Valide le token Sage X3 du header X-Sage-X3-Token"""
        if self.mock_mode:
            logger.info(f"🧪 Mock mode: accepting any token")
            return True
        
        is_valid = token == self.sage_token
        if is_valid:
            logger.info(f"✅ Valid Sage X3 token")
        else:
            logger.warning(f"❌ Invalid Sage X3 token")
        return is_valid
    
    def receive_sage_mission(
        self,
        mission_data: SageMissionInbound
    ) -> Dict[str, Any]:
        """
        Reçoit une mission de Sage X3 et la crée comme Delivery
        
        Args:
            mission_data: Données de la mission Sage X3
            
        Returns:
            dict avec success, message, delivery_id, external_delivery_id, status
            
        Raises:
            ValueError: Si la mission existe déjà
            HTTPException: Si erreur DB
        """
        logger.info(f"📥 Receiving Sage mission: {mission_data.external_delivery_id}")
        
        # Vérifier que la mission n'existe pas déjà
        existing = self.db.query(Delivery).filter(
            Delivery.external_delivery_id == mission_data.external_delivery_id
        ).first()
        
        if existing:
            logger.warning(f"⚠️ Mission already exists: {mission_data.external_delivery_id}")
            raise ValueError(f"Mission {mission_data.external_delivery_id} déjà reçue")
        
        try:
            # Créer la delivery avec source_type='sage_inbound'
            delivery = Delivery(
                external_delivery_id=mission_data.external_delivery_id,
                depot_id=mission_data.depot_id,
                destination_name=mission_data.destination_name,
                destination_address=mission_data.destination_address,
                destination_latitude=mission_data.destination_latitude,
                destination_longitude=mission_data.destination_longitude,
                contact_name=mission_data.contact_name,
                contact_phone=mission_data.contact_phone,
                quantity_6kg=mission_data.quantity_6kg,
                quantity_12kg=mission_data.quantity_12kg,
                scheduled_date=mission_data.scheduled_date,
                notes=mission_data.notes or "",
                status=DeliveryStatusEnum.PENDING,  # Delivery status
                source_type="sage_inbound",  # Source
                external_status=SageMissionStatusEnum.PENDING_APPROVAL,  # Sage status
                created_at=utc_now(),
            )
            
            self.db.add(delivery)
            self.db.commit()
            self.db.refresh(delivery)
            
            logger.info(f"✅ Mission reçue avec succès: delivery_id={delivery.id}")
            
            return {
                "success": True,
                "message": f"Mission {mission_data.external_delivery_id} reçue avec succès",
                "delivery_id": delivery.id,
                "external_delivery_id": mission_data.external_delivery_id,
                "status": "pending_approval"
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error creating mission: {str(e)}")
            raise
    
    def approve_mission(
        self,
        delivery_id: int,
        truck_id: int,
        admin_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Admin approuve une mission Sage et assigne un camion
        
        Args:
            delivery_id: ID de la delivery
            truck_id: ID du camion
            admin_id: ID de l'admin qui approuve (optional)
            
        Returns:
            dict avec status, message
        """
        logger.info(f"✅ Approving mission: delivery_id={delivery_id}, truck_id={truck_id}")
        
        delivery = self.db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not delivery:
            raise ValueError(f"Delivery {delivery_id} not found")
        
        if delivery.source_type != "sage_inbound":
            raise ValueError(f"Delivery {delivery_id} is not from Sage X3")
        
        if delivery.external_status != SageMissionStatusEnum.PENDING_APPROVAL:
            raise ValueError(f"Delivery {delivery_id} is not pending approval")
        
        # Vérifier que le camion existe
        truck = self.db.query(Truck).filter(Truck.id == truck_id).first()
        if not truck:
            raise ValueError(f"Truck {truck_id} not found")
        
        try:
            # Mettre à jour la delivery
            delivery.truck_id = truck_id
            delivery.driver_id = truck.driver_id  # Auto-assign driver from truck
            delivery.external_status = SageMissionStatusEnum.APPROVED
            delivery.external_sync_at = utc_now()
            
            self.db.commit()
            self.db.refresh(delivery)
            
            logger.info(f"✅ Mission approved: delivery_id={delivery_id}")
            
            return {
                "success": True,
                "message": f"Mission {delivery.external_delivery_id} approuvée",
                "delivery_id": delivery_id,
                "external_delivery_id": delivery.external_delivery_id
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error approving mission: {str(e)}")
            raise
    
    def reject_mission(
        self,
        delivery_id: int,
        reason: Optional[str] = None,
        admin_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Admin rejette une mission Sage
        
        Args:
            delivery_id: ID de la delivery
            reason: Raison du rejet
            admin_id: ID de l'admin qui rejette
            
        Returns:
            dict avec status, message
        """
        logger.info(f"❌ Rejecting mission: delivery_id={delivery_id}")
        
        delivery = self.db.query(Delivery).filter(Delivery.id == delivery_id).first()
        if not delivery:
            raise ValueError(f"Delivery {delivery_id} not found")
        
        if delivery.source_type != "sage_inbound":
            raise ValueError(f"Delivery {delivery_id} is not from Sage X3")
        
        try:
            delivery.external_status = SageMissionStatusEnum.REJECTED
            delivery.external_error = reason or "Rejetée par l'administrateur"
            delivery.external_sync_at = utc_now()
            
            self.db.commit()
            self.db.refresh(delivery)
            
            logger.info(f"✅ Mission rejected: delivery_id={delivery_id}")
            
            return {
                "success": True,
                "message": f"Mission {delivery.external_delivery_id} rejetée",
                "delivery_id": delivery_id,
                "reason": reason
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error rejecting mission: {str(e)}")
            raise
    
    def get_pending_missions(self) -> List[Delivery]:
        """Retourne toutes les missions en attente d'approbation"""
        return self.db.query(Delivery).filter(
            Delivery.source_type == "sage_inbound",
            Delivery.external_status == SageMissionStatusEnum.PENDING_APPROVAL
        ).all()
    
    def get_sage_missions(self, status: Optional[str] = None) -> List[Delivery]:
        """
        Retourne les missions Sage X3 optionnellement filtrées par status
        
        Args:
            status: Status à filtrer (pending_approval, approved, etc.)
            
        Returns:
            List[Delivery]
        """
        query = self.db.query(Delivery).filter(
            Delivery.source_type == "sage_inbound"
        )
        
        if status:
            try:
                status_enum = SageMissionStatusEnum(status)
                query = query.filter(Delivery.external_status == status_enum)
            except ValueError:
                logger.warning(f"Invalid status: {status}")
        
        return query.all()
    
    def get_health_status(self) -> Dict[str, Any]:
        """Retourne le status de l'intégration Sage X3"""
        return {
            "status": "healthy",
            "mode": "mock" if self.mock_mode else "http",
            "detail": "Mock mode enabled - no real Sage X3 calls" if self.mock_mode else "Production mode - real Sage X3 API",
            "timestamp": utc_now().isoformat()
        }
