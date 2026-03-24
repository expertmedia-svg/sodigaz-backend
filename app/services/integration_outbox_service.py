"""
Service de gestion de l'IntegrationOutbox

Gère:
- L'enregistrement des événements d'intégration
- La tentative d'envoi aux systèmes externes (Sage X3, etc.)
- La gestion des erreurs et dead-letter queue
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import IntegrationOutbox
from app.time_utils import utc_now
import logging
import json

logger = logging.getLogger(__name__)


class IntegrationOutboxService:
    """Service pour gérer l'IntegrationOutbox"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_outbox_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Dict[str, Any],
        external_message_id: Optional[str] = None
    ) -> IntegrationOutbox:
        """
        Crée un événement dans l'outbox
        
        Args:
            event_type: Type d'événement (DeliveryCreated, MissionApproved, etc.)
            aggregate_type: Type d'agrégat (Delivery, Mission, etc.)
            aggregate_id: ID de l'agrégat
            payload: Payload JSON
            external_message_id: ID message pour d'éviter les doublons
            
        Returns:
            IntegrationOutbox
        """
        logger.info(f"📤 Creating outbox event: {event_type} for {aggregate_type}/{aggregate_id}")
        
        try:
            # Vérifier si déjà existe (idempotence)
            if external_message_id:
                existing = self.db.query(IntegrationOutbox).filter(
                    IntegrationOutbox.external_message_id == external_message_id
                ).first()
                
                if existing:
                    logger.info(f"⚠️ Outbox event already exists: {external_message_id}")
                    return existing
            
            outbox = IntegrationOutbox(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload_json=payload,
                external_message_id=external_message_id,
                status="pending",  # pending, sent, failed, dead_letter
                created_at=utc_now()
            )
            
            self.db.add(outbox)
            self.db.commit()
            self.db.refresh(outbox)
            
            logger.info(f"✅ Outbox event created: id={outbox.id}")
            return outbox
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error creating outbox event: {str(e)}")
            raise
    
    def mark_as_sent(
        self,
        outbox_id: int,
        external_id: Optional[str] = None
    ) -> IntegrationOutbox:
        """Marque un événement comme envoyé"""
        logger.info(f"📤 Marking outbox as sent: id={outbox_id}")
        
        outbox = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.id == outbox_id
        ).first()
        
        if not outbox:
            raise ValueError(f"Outbox {outbox_id} not found")
        
        try:
            outbox.status = "sent"
            outbox.sent_at = utc_now()
            if external_id:
                outbox.external_success_id = external_id
            
            self.db.commit()
            self.db.refresh(outbox)
            
            logger.info(f"✅ Outbox marked as sent: id={outbox_id}")
            return outbox
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error marking outbox as sent: {str(e)}")
            raise
    
    def mark_as_failed(
        self,
        outbox_id: int,
        error_message: str,
        retry_count: int = 0
    ) -> IntegrationOutbox:
        """Marque un événement comme échoué"""
        logger.info(f"❌ Marking outbox as failed: id={outbox_id}")
        
        outbox = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.id == outbox_id
        ).first()
        
        if not outbox:
            raise ValueError(f"Outbox {outbox_id} not found")
        
        try:
            if retry_count >= 3:
                # Après 3 tentatives, envoyer en dead-letter
                outbox.status = "dead_letter"
                logger.warning(f"💀 Outbox moved to dead-letter: id={outbox_id}")
            else:
                outbox.status = "failed"
            
            outbox.last_error = error_message
            outbox.retry_count = retry_count
            outbox.last_retry_at = utc_now()
            
            self.db.commit()
            self.db.refresh(outbox)
            
            return outbox
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error marking outbox as failed: {str(e)}")
            raise
    
    def get_pending_events(self) -> List[IntegrationOutbox]:
        """Retourne tous les événements en attente d'envoi"""
        return self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "pending"
        ).order_by(IntegrationOutbox.created_at).all()
    
    def get_failed_events(self) -> List[IntegrationOutbox]:
        """Retourne tous les événements échoués"""
        return self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "failed"
        ).order_by(IntegrationOutbox.last_retry_at).all()
    
    def get_dead_letter_events(self) -> List[IntegrationOutbox]:
        """Retourne tous les événements en dead-letter"""
        return self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "dead_letter"
        ).order_by(IntegrationOutbox.created_at).all()
    
    def get_health_status(self) -> Dict[str, Any]:
        """Retourne le status de l'outbox"""
        pending = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "pending"
        ).count()
        
        sent = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "sent"
        ).count()
        
        failed = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "failed"
        ).count()
        
        dead_letter = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == "dead_letter"
        ).count()
        
        return {
            "outbox": {
                "pending": pending,
                "sent": sent,
                "failed": failed,
                "failed_dead_letter": dead_letter,
                "total": pending + sent + failed + dead_letter
            }
        }
