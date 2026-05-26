from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta
from app.database import get_db
from pydantic import BaseModel, Field
from typing import Any, Optional
from app.models import (
    User,
    Delivery,
    Depot,
    Program,
    ProgramTypeEnum,
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
import logging

from app.auth import get_current_user, verify_password, create_access_token
from app.services.pricing_service import resolve_program_line_amount, resolve_active_pricing_rule, calculate_delivery_amount
from decimal import Decimal
from app.services.outbox_worker import process_pending_outbox_events
from app.services.sage_sql_service import valider_programme_sage, ecrire_livraison_sage
from app.time_utils import utc_now, utc_now_iso

router = APIRouter()
logger = logging.getLogger(__name__)

class LoginRequest(BaseModel):
    identifier: str = Field(..., description="Username ou email")
    password: str

class ProgramCompleteRequest(BaseModel):
    program_code: str

class CompleteDeliveryRequest(BaseModel):
    latitude: float
    longitude: float
    quantity_6kg_delivered: int = 0
    quantity_12kg_delivered: int = 0

class SyncGPSPayload(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None

class DeliveryConfirmationPayload(BaseModel):
    confirmation_id: str
    delivery_id: int
    product: str
    quantity_delivered: int = 0
    quantity_collected: int = 0
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
        "program_code": delivery.program.program_code if delivery.program else None,
        "program_line_id": delivery.program_line.id if delivery.program_line else None,
        "program_type": delivery.program_type or (delivery.program.program_type.value if delivery.program else ProgramTypeEnum.DELIVERY.value),
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
        "quantity_collected": delivery.collected_quantity_total,
        "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
        "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
        "article": delivery.program_line.article if delivery.program_line else None,
        "zone": delivery.program_line.zone if delivery.program_line else None,
        "delivery_mode": delivery.program_line.delivery_mode if delivery.program_line else None,
        "collection_sheet": delivery.program_line.collection_sheet if delivery.program_line else None,
        "comment": delivery.program_line.comment if delivery.program_line else None,
        "unit_price": float(delivery.unit_price_applied) if delivery.unit_price_applied is not None else None,
        "tax_rate": float(delivery.tax_rate_applied) if delivery.tax_rate_applied is not None else None,
        "total_amount": float(delivery.total_amount) if delivery.total_amount is not None else None,
        "actual_start": delivery.actual_start.isoformat() if delivery.actual_start else None,
        "actual_end": delivery.actual_end.isoformat() if delivery.actual_end else None,
        "notes": delivery.notes,
        "last_server_sync_at": utc_now_iso(),
    }

def _append_delivery_note(delivery: Delivery, note: str) -> None:
    if not note:
        return
    delivery.notes = f"{delivery.notes}\n{note}".strip() if delivery.notes else note


def _refresh_delivery_pricing_preview(delivery: Delivery, db: Session) -> bool:
    if delivery.program_type != ProgramTypeEnum.DELIVERY.value:
        return False
    if delivery.program_line is None or delivery.status == DeliveryStatusEnum.COMPLETED:
        return False

    preview_quantity = (
        delivery.delivered_quantity_total
        or delivery.program_line.quantity_delivered
        or delivery.quantity
        or delivery.program_line.quantity_planned
        or 0
    )
    if preview_quantity <= 0:
        return False

    pricing_rule, amount_summary = resolve_program_line_amount(
        db,
        program_line=delivery.program_line,
        quantity_delivered=preview_quantity,
        depot_id=delivery.depot_id,
    )

    changed = False

    next_pricing_rule_id = pricing_rule.id if pricing_rule else None
    next_unit_price = amount_summary["unit_price"]
    next_tax_rate = amount_summary["tax_rate"]
    next_subtotal = amount_summary["subtotal_amount"]
    next_tax_amount = amount_summary["tax_amount"]
    next_total = amount_summary["total_amount"]

    if delivery.program_line.pricing_rule_id != next_pricing_rule_id:
        delivery.program_line.pricing_rule_id = next_pricing_rule_id
        changed = True
    if delivery.program_line.unit_price != next_unit_price:
        delivery.program_line.unit_price = next_unit_price
        changed = True
    if delivery.program_line.tax_rate != next_tax_rate:
        delivery.program_line.tax_rate = next_tax_rate
        changed = True
    if delivery.program_line.subtotal_amount != next_subtotal:
        delivery.program_line.subtotal_amount = next_subtotal
        changed = True
    if delivery.program_line.tax_amount != next_tax_amount:
        delivery.program_line.tax_amount = next_tax_amount
        changed = True
    if delivery.program_line.total_amount != next_total:
        delivery.program_line.total_amount = next_total
        changed = True

    if delivery.pricing_rule_id != next_pricing_rule_id:
        delivery.pricing_rule_id = next_pricing_rule_id
        changed = True
    if delivery.unit_price_applied != next_unit_price:
        delivery.unit_price_applied = next_unit_price
        changed = True
    if delivery.tax_rate_applied != next_tax_rate:
        delivery.tax_rate_applied = next_tax_rate
        changed = True
    if delivery.subtotal_amount != next_subtotal:
        delivery.subtotal_amount = next_subtotal
        changed = True
    if delivery.tax_amount != next_tax_amount:
        delivery.tax_amount = next_tax_amount
        changed = True
    if delivery.total_amount != next_total:
        delivery.total_amount = next_total
        changed = True

    return changed


def _serialize_driver_program(program: Program) -> dict[str, Any]:
    return {
        "program_code": program.program_code,
        "program_type": program.program_type,
        "site_code": program.site_code,
        "program_date": program.program_date.isoformat() if program.program_date else None,
        "program_time": program.program_time,
        "depot_id": program.depot_id,
        "depot_name": program.depot.name if program.depot else None,
        "truck_id": program.truck_id,
        "truck_license_plate": program.truck.license_plate if program.truck else None,
        "transporter_name": program.transporter_name,
        "status": program.status,
        "lines": [
            {
                "line_id": line.id,
                "line_code": line.line_code,
                "client_id": line.client_id,
                "client_name": line.client_name,
                "destination_address": line.destination_address,
                "product_code": line.product_code,
                "product_label": line.product_label,
                "article": line.article,
                "zone": line.zone,
                "quantity_planned": line.quantity_planned,
                "quantity_delivered": line.quantity_delivered,
                "quantity_collected": line.quantity_collected,
                "delivery_mode": line.delivery_mode,
                "collection_sheet": line.collection_sheet,
                "comment": line.comment,
                "status": line.status,
                "unit_price": float(line.unit_price) if line.unit_price is not None else None,
                "tax_rate": float(line.tax_rate) if line.tax_rate is not None else None,
                "total_amount": float(line.total_amount) if line.total_amount is not None else None,
                "delivery_id": line.delivery.id if line.delivery else None,
                "delivery_notes": line.delivery.notes if (line.delivery and line.delivery.notes) else None,
            }
            for line in sorted(program.lines, key=lambda item: item.line_code)
        ],
    }


def _load_driver_today_programs(db: Session, driver_id: int) -> list[dict[str, Any]]:
    # On autorise l'affichage des programmes complétés récemment (moins de 2 jours) pour l'historique
    recent_limit = datetime.utcnow() - timedelta(days=2)
    programs = (
        db.query(Program)
        .filter(
            Program.driver_id == driver_id,
            or_(
                Program.status.in_(["active", "in_progress"]),
                (Program.status == "completed") & (Program.program_date >= recent_limit)
            ),
        )
        .order_by(Program.program_date.asc(), Program.updated_at.desc())
        .all()
    )
    return [_serialize_driver_program(program) for program in programs]


def _refresh_program_status(program: Optional[Program], db: Session) -> None:
    if program is None:
        return

    previous_status = program.status
    active_lines = [line for line in program.lines if line.status != "cancelled"]

    logger.info(f"[PROGRAM_STATUS] Programme {program.program_code}: {len(active_lines)} lignes actives")

    if not active_lines:
        program.status = "completed"
    else:
        fully_processed = []
        partially_processed = False
        for line in active_lines:
            if program.program_type == ProgramTypeEnum.COLLECTION:
                quantity_done = line.quantity_collected or 0
            else:
                quantity_done = line.quantity_delivered or 0

            is_complete = quantity_done >= (line.quantity_planned or 0) and (line.quantity_planned or 0) > 0
            fully_processed.append(is_complete)

            logger.info(
                f"[PROGRAM_STATUS] Ligne {line.line_code}: "
                f"planifiée={line.quantity_planned}, confirmée={quantity_done}, complète={is_complete}"
            )

            if quantity_done > 0:
                partially_processed = True

        if all(fully_processed):
            program.status = "completed"
            logger.info(f"[PROGRAM_STATUS] ✅ Programme {program.program_code} COMPLETED")
        elif partially_processed:
            program.status = "in_progress"
        else:
            program.status = "active"

    if program.status == "completed" and previous_status != "completed":
        logger.info(f"[PROGRAM_STATUS] Validation de {program.program_code} sur Sage X3...")
        _validate_sage_program_completion(program, db)


def _validate_sage_program_completion(program: Program, db: Session) -> None:
    logger.info(f"[SAGE_VALIDATION] Vérification du programme {program.program_code}")
    logger.info(f"[SAGE_VALIDATION] source_system={program.source_system}, program_code={program.program_code}")

    if program.source_system != "sage_x3" or not program.program_code:
        logger.warning(f"[SAGE_VALIDATION] ❌ Source non Sage X3 ou pas de code programme")
        return

    try:
        logger.info(f"[SAGE_VALIDATION] 🔄 Appel valider_programme_sage({program.program_code})...")
        validation_status = valider_programme_sage(program.program_code)
        logger.info(f"[SAGE_VALIDATION] Résultat: {validation_status}")

        if program.source_payload is None:
            program.source_payload = {}
        program.source_payload["sage_validation"] = {
            "status": validation_status,
            "validated_at": utc_now_iso(),
        }

        if validation_status == "OK":
            logger.info(f"[SAGE_VALIDATION] ✅ Programme {program.program_code} VALIDÉ sur Sage X3 (YFLGVAL2_0=2)")
            program.status = "completed"
        elif validation_status == "ALREADY_VALIDATED":
            logger.info(f"[SAGE_VALIDATION] ℹ️ Programme {program.program_code} déjà validé sur Sage X3")
            program.status = "completed"
        else:
            logger.warning(
                "Validation Sage failed for programme %s: %s",
                program.program_code,
                validation_status,
            )
    except Exception as exc:
        logger.error(
            "Erreur lors de la validation Sage pour programme %s: %s",
            program.program_code,
            exc,
        )
        if program.source_payload is None:
            program.source_payload = {}
        program.source_payload["sage_validation"] = {
            "status": "ERROR",
            "error": str(exc),
            "validated_at": utc_now_iso(),
        }

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

    program_type = (delivery.program_type or (delivery.program.program_type.value if delivery.program else ProgramTypeEnum.DELIVERY.value)).upper()
    confirmed_quantity = payload.quantity_collected if program_type == ProgramTypeEnum.COLLECTION.value else payload.quantity_delivered

    if confirmed_quantity <= 0:
        return _build_operation_result(
            operation.idempotency_key,
            "rejected",
            "INVALID_QUANTITY",
            "La quantite confirmee doit etre strictement positive.",
            retryable=False,
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
        # Vérifier si on a déjà une confirmation pour ce produit spécifique (idempotence multiniveau)
        existing_conf = db.query(DeliveryConfirmationEvent).filter(
            DeliveryConfirmationEvent.delivery_id == delivery.id,
            DeliveryConfirmationEvent.product_type == product_type
        ).first()
        
        if existing_conf:
            status_str = delivery.status.value if hasattr(delivery.status, "value") else str(delivery.status)
            return _build_operation_result(
                operation.idempotency_key,
                "accepted",
                "SUCCESS",
                "Déjà traité pour ce produit.",
                delivery_id=delivery.id,
                server_delivery_status=status_str,
            )

    # Gérer la création dynamique d'une 2ème ligne SQLite si le chauffeur récolte un 2ème produit différent de l'original
    if delivery.program_line and delivery.program_line.product_code not in ('UNKNOWN', product_type):
        from app.models import ProgramLine
        # C'est un 2ème produit pour le même client ! On crée une nouvelle ProgramLine et une nouvelle Delivery en SQLite
        new_line = ProgramLine(
            program_id=delivery.program_id,
            line_code=f"{delivery.program_line.line_code}_2",
            external_line_id=delivery.program_line.external_line_id,
            client_id=delivery.program_line.client_id,
            client_code=delivery.program_line.client_code,
            client_name=delivery.program_line.client_name,
            destination_address=delivery.program_line.destination_address,
            destination_latitude=delivery.program_line.destination_latitude,
            destination_longitude=delivery.program_line.destination_longitude,
            contact_name=delivery.program_line.contact_name,
            contact_phone=delivery.program_line.contact_phone,
            product_code=product_type,
            product_label="Gaz 12kg" if product_type == "GAZ_12KG" else "Gaz 6kg",
            quantity_planned=0,
            quantity_collected=0,
            quantity_delivered=0,
            status="pending",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(new_line)
        db.flush()
        
        new_delivery = Delivery(
            truck_id=delivery.truck_id,
            depot_id=delivery.depot_id,
            destination_name=delivery.destination_name,
            destination_address=delivery.destination_address,
            destination_latitude=delivery.destination_latitude,
            destination_longitude=delivery.destination_longitude,
            contact_name=delivery.contact_name,
            contact_phone=delivery.contact_phone,
            driver_id=delivery.driver_id,
            quantity_6kg=0,
            quantity_12kg=0,
            quantity=0,
            quantity_6kg_vide_recupere=0,
            quantity_12kg_vide_recupere=0,
            status=DeliveryStatusEnum.PENDING,
            source_type=delivery.source_type,
            external_delivery_id=delivery.external_delivery_id,
            external_status=delivery.external_status,
            scheduled_date=delivery.scheduled_date,
            actual_start=delivery.actual_start or payload.delivered_at,
            actual_end=payload.delivered_at,
            program_type=delivery.program_type,
            program_id=delivery.program_id,
            program_line_id=new_line.id,
        )
        db.add(new_delivery)
        db.flush()
        
        # On utilise cette nouvelle livraison pour la suite du traitement
        delivery = new_delivery
    elif delivery.program_line and delivery.program_line.product_code == 'UNKNOWN':
        # Si c'était UNKNOWN, on met à jour avec le vrai produit confirmé par le driver
        delivery.program_line.product_code = product_type
        delivery.program_line.product_label = "Gaz 6kg" if product_type == "GAZ_6KG" else "Gaz 12kg"

    amount_summary = None
    if delivery.program_line is not None and program_type == ProgramTypeEnum.DELIVERY.value:
        pricing_rule, amount_summary = resolve_program_line_amount(
            db,
            program_line=delivery.program_line,
            quantity_delivered=confirmed_quantity,
            depot_id=delivery.depot_id,
        )
        delivery.program_line.quantity_delivered = confirmed_quantity
        delivery.program_line.pricing_rule_id = pricing_rule.id if pricing_rule else None
        delivery.program_line.unit_price = amount_summary["unit_price"]
        delivery.program_line.tax_rate = amount_summary["tax_rate"]
        delivery.program_line.subtotal_amount = amount_summary["subtotal_amount"]
        delivery.program_line.tax_amount = amount_summary["tax_amount"]
        delivery.program_line.total_amount = amount_summary["total_amount"]
        delivery.program_line.status = (
            "delivered"
            if confirmed_quantity >= delivery.program_line.quantity_planned
            else "partial"
        )
        delivery.pricing_rule_id = pricing_rule.id if pricing_rule else None
        delivery.delivered_quantity_total = confirmed_quantity
        delivery.unit_price_applied = amount_summary["unit_price"]
        delivery.tax_rate_applied = amount_summary["tax_rate"]
        delivery.subtotal_amount = amount_summary["subtotal_amount"]
        delivery.tax_amount = amount_summary["tax_amount"]
        delivery.total_amount = amount_summary["total_amount"]
    elif delivery.program_line is not None:
        collected_quantity = payload.quantity_collected or payload.quantity_empty_collected
        delivery.program_line.quantity_collected = collected_quantity
        delivery.program_line.status = (
            "collected"
            if collected_quantity >= delivery.program_line.quantity_planned
            else "partial"
        )
        delivery.collected_quantity_total = collected_quantity
        
        # Résolution du prix et calcul automatique pour les collectes
        resolved_prod = product_type
        if resolved_prod == 'UNKNOWN' or not resolved_prod:
            resolved_prod = 'GAZ_6KG'
            
        pricing_rule = resolve_active_pricing_rule(db, product_code=resolved_prod, depot_id=delivery.depot_id)
        unit_price = Decimal("1676")  # Valeur par défaut si règle absente
        tax_rate = Decimal("0")
        if pricing_rule:
            unit_price = pricing_rule.unit_price
            tax_rate = pricing_rule.tax_rate
            
        amount_summary = calculate_delivery_amount(
            quantity_delivered=collected_quantity,
            unit_price=unit_price,
            tax_rate=tax_rate,
        )
        
        delivery.pricing_rule_id = pricing_rule.id if pricing_rule else None
        delivery.unit_price_applied = amount_summary["unit_price"]
        delivery.tax_rate_applied = amount_summary["tax_rate"]
        delivery.subtotal_amount = amount_summary["subtotal_amount"]
        delivery.tax_amount = amount_summary["tax_amount"]
        delivery.total_amount = amount_summary["total_amount"]

        # Mettre à jour également la program_line pour l'affichage de l'admin
        delivery.program_line.pricing_rule_id = pricing_rule.id if pricing_rule else None
        delivery.program_line.unit_price = amount_summary["unit_price"]
        delivery.program_line.tax_rate = amount_summary["tax_rate"]
        delivery.program_line.subtotal_amount = amount_summary["subtotal_amount"]
        delivery.program_line.tax_amount = amount_summary["tax_amount"]
        delivery.program_line.total_amount = amount_summary["total_amount"]

    if program_type == ProgramTypeEnum.COLLECTION.value:
        delivery.collected_quantity_total = payload.quantity_collected or payload.quantity_empty_collected
        delivery.delivered_quantity_total = 0
    else:
        delivery.delivered_quantity_total = confirmed_quantity

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

    collected_empty = payload.quantity_collected or payload.quantity_empty_collected
    if product_type == "GAZ_6KG":
        delivery.quantity_6kg_vide_recupere = collected_empty
    else:
        delivery.quantity_12kg_vide_recupere = collected_empty

    delivery.echange_effectue = collected_empty > 0

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
        quantity_delivered=confirmed_quantity,
        quantity_empty_collected=collected_empty,
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

    db.add(
        IntegrationOutbox(
            event_type="COLLECTION_CONFIRMED" if program_type == ProgramTypeEnum.COLLECTION.value else "DELIVERY_CONFIRMED",
            aggregate_type="delivery",
            aggregate_id=str(delivery.id),
            external_message_id=f"delivery_confirmation:{payload.confirmation_id}",
            payload_json={
                "delivery_id": delivery.id,
                "program_code": delivery.program.program_code if delivery.program else None,
                "program_type": program_type,
                "program_line_id": delivery.program_line.id if delivery.program_line else None,
                "confirmation_id": payload.confirmation_id,
                "product": product_type,
                "quantity": confirmed_quantity,
                "quantity_delivered": confirmed_quantity if program_type == ProgramTypeEnum.DELIVERY.value else 0,
                "quantity_collected": confirmed_quantity if program_type == ProgramTypeEnum.COLLECTION.value else 0,
                "quantity_empty_collected": collected_empty,
                "delivered_at": payload.delivered_at.isoformat(),
                "total_amount": str(amount_summary["total_amount"]) if amount_summary else None,
                "tax_amount": str(amount_summary["tax_amount"]) if amount_summary else None,
                "unit_price": str(amount_summary["unit_price"]) if amount_summary else None,
                "tax_rate": str(amount_summary["tax_rate"]) if amount_summary else None,
                # Champs Sage natifs pour que Sage retrouve directement ses lignes
                "sage_program_code": delivery.program.program_code if delivery.program else None,
                "sage_site_code": delivery.program.site_code if delivery.program else None,
                "sage_driver_code": (delivery.program.source_payload or {}).get("assignment", {}).get("sage_driver_code") if delivery.program else None,
                "sage_truck_code": (delivery.program.source_payload or {}).get("assignment", {}).get("truck_code") if delivery.program else None,
                "sage_client_code": delivery.program_line.client_code if delivery.program_line else None,
                "sage_product_code": delivery.program_line.product_code if delivery.program_line else None,
                "sage_external_line_id": delivery.program_line.external_line_id if delivery.program_line else None,
                "sage_line_code": delivery.program_line.line_code if delivery.program_line else None,
                "sage_quantity_planned": delivery.program_line.quantity_planned if delivery.program_line else None,
            },
            status="pending",
        )
    )

    logger.info(f"[CONFIRMATION] ✅ Livraison {delivery.id} confirmée - Statut: {delivery.status.value}")

    # 🔥 ÉCRIRE IMMÉDIATEMENT SUR SAGE X3
    if delivery.program and delivery.program.source_system == "sage_x3" and delivery.program.program_code:
        client_code = delivery.program_line.client_code if delivery.program_line else ""
        qty_6kg = 0
        qty_12kg = 0

        if program_type == ProgramTypeEnum.DELIVERY.value:
            if product_type == "GAZ_6KG":
                qty_6kg = confirmed_quantity
            else:
                qty_12kg = confirmed_quantity
        else:  # COLLECTION
            if product_type == "GAZ_6KG":
                qty_6kg = confirmed_quantity
            else:
                qty_12kg = confirmed_quantity

        logger.info(f"[SAGE_WRITE] Écriture livraison sur Sage: {delivery.program.program_code}/{client_code} → 6kg={qty_6kg}, 12kg={qty_12kg}")

        sage_result = ecrire_livraison_sage(
            num_programme=delivery.program.program_code,
            client_code=client_code,
            qty_6kg=qty_6kg,
            qty_12kg=qty_12kg,
            notes=payload.notes,
            total_amount_6kg=float(amount_summary["total_amount"]) if (qty_6kg > 0 and amount_summary) else 0,
            total_amount_12kg=float(amount_summary["total_amount"]) if (qty_12kg > 0 and amount_summary) else 0,
            product_type=product_type,
        )

        if sage_result["status"] == "OK":
            logger.info(f"[SAGE_WRITE] ✅ Livraison écrite sur Sage")
            if sage_result.get("program_validated"):
                logger.info(f"[SAGE_WRITE] 🎉 PROGRAMME {delivery.program.program_code} VALIDÉ SUR SAGE (YFLGVAL2_0=2)")
                delivery.program.status = "completed"
                # Mark all deliveries in this program as synced
                program_deliveries = db.query(Delivery).filter(
                    Delivery.program_id == delivery.program_id,
                ).all()
                for prog_delivery in program_deliveries:
                    prog_delivery.external_status = "synced"
                    logger.info(f"[SAGE_WRITE] 📍 Delivery {prog_delivery.id} marked as synced")
                db.flush()
        else:
            logger.error(f"[SAGE_WRITE] ❌ Erreur: {sage_result['detail']}")

    if delivery.program:
        logger.info(f"[CONFIRMATION] Rafraîchissement du programme {delivery.program.program_code}...")
        _refresh_program_status(delivery.program, db=db)
        logger.info(f"[CONFIRMATION] Nouveau statut du programme: {delivery.program.status}")
    else:
        logger.warning(f"[CONFIRMATION] ⚠️ Pas de programme associé à la livraison {delivery.id}")

    return _build_operation_result(
        operation.idempotency_key,
        "accepted",
        "SYNCED",
        "Confirmation de collecte synchronisee." if program_type == ProgramTypeEnum.COLLECTION.value else "Confirmation de livraison synchronisee.",
        retryable=False,
        delivery_id=delivery.id,
        server_delivery_status=delivery.status.value,
        server_event_id=f"dconf_{event.id}",
        amount_summary={
            "subtotal_amount": str(amount_summary["subtotal_amount"]),
            "tax_amount": str(amount_summary["tax_amount"]),
            "total_amount": str(amount_summary["total_amount"]),
        } if amount_summary else None,
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
    """Connexion ravitailleur avec username ou email"""
    try:
        identifier = credentials.identifier.strip()
        user = db.query(User).filter(
            or_(User.email == identifier, User.username == identifier)
        ).first()

        if not user or not verify_password(credentials.password, user.hashed_password):
            raise HTTPException(
                status_code=401,
                detail="Identifiant ou mot de passe incorrect",
            )

        if user.role != RoleEnum.RAVITAILLEUR:
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LOGIN ERROR] {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")

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

@router.post("/refresh")
def refresh_driver_token(current_user: User = Depends(require_driver_role)):
    """Refresh access token pour ravitailleur"""
    access_token = create_access_token(data={"sub": str(current_user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role.value
        }
    }


def _resolve_driver_operational_truck(
    db: Session,
    driver_id: int,
    active_deliveries: list[Delivery] | None = None,
) -> Truck | None:
    truck_ids: list[int] = []
    seen_ids: set[int] = set()

    deliveries = active_deliveries
    if deliveries is None:
        deliveries = db.query(Delivery).filter(
            Delivery.driver_id == driver_id,
            Delivery.status.in_([
                DeliveryStatusEnum.PENDING,
                DeliveryStatusEnum.IN_PROGRESS,
            ]),
        ).order_by(Delivery.scheduled_date).all()

    for delivery in deliveries:
        if delivery.truck_id and delivery.truck_id not in seen_ids:
            seen_ids.add(delivery.truck_id)
            truck_ids.append(delivery.truck_id)

    if truck_ids:
        active_trucks = db.query(Truck).filter(
            Truck.id.in_(truck_ids),
            Truck.is_active == True,
        ).all()
        trucks_by_id = {truck.id: truck for truck in active_trucks}
        for truck_id in truck_ids:
            truck = trucks_by_id.get(truck_id)
            if truck is not None:
                return truck

    return db.query(Truck).filter(
        Truck.driver_id == driver_id,
        Truck.is_active == True,
    ).order_by(Truck.id.asc()).first()

@router.get("/test-bootstrap")
def test_bootstrap():
    """Test endpoint to verify API is reachable"""
    logger.info("[TEST] test-bootstrap called")
    return {
        "status": "ok",
        "message": "API is reachable",
        "timestamp": utc_now_iso()
    }

@router.get("/whoami")
def whoami(current_user: User = Depends(require_driver_role), db: Session = Depends(get_db)):
    """Check who the driver app is authenticated as"""
    deliveries_count = db.query(Delivery).filter(Delivery.driver_id == current_user.id).count()
    pending_count = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        cast(Delivery.status, String).in_(["PENDING", "IN_PROGRESS"])
    ).count()

    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role.value,
        "total_deliveries": deliveries_count,
        "pending_deliveries": pending_count,
        "timestamp": utc_now_iso()
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
        cast(Delivery.status, String).in_([
            "PENDING", "IN_PROGRESS",
            "pending", "in_progress",
            DeliveryStatusEnum.PENDING.value,
            DeliveryStatusEnum.IN_PROGRESS.value
        ])
    ).order_by(Delivery.scheduled_date).all()

    # Eager load program_line for each delivery
    for delivery in deliveries:
        _ = delivery.program_line  # Force load relationship

    logger.info(f"[BOOTSTRAP] Driver {current_user.id} ({current_user.username}): Found {len(deliveries)} deliveries")

    pricing_changed = False
    for delivery in deliveries:
        pricing_changed = _refresh_delivery_pricing_preview(delivery, db) or pricing_changed
    if pricing_changed:
        db.commit()

    latest_batch = db.query(SyncBatch).filter(
        SyncBatch.driver_id == current_user.id
    ).order_by(SyncBatch.received_at.desc()).first()

    open_conflicts = db.query(SyncConflict).filter(
        SyncConflict.driver_id == current_user.id,
        SyncConflict.resolution_status == "open"
    ).count()

    truck = _resolve_driver_operational_truck(db, current_user.id, deliveries)

    assignments = []
    for delivery in deliveries:
        depot = db.query(Depot).filter(Depot.id == delivery.depot_id).first()
        assignments.append({
            "id": delivery.id,
            "status": delivery.status,
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
            "quantity_collected": delivery.collected_quantity_total,
            "quantity_6kg_vide_recupere": delivery.quantity_6kg_vide_recupere or 0,
            "quantity_12kg_vide_recupere": delivery.quantity_12kg_vide_recupere or 0,
            "program_type": delivery.program_type or (delivery.program.program_type.value if delivery.program else ProgramTypeEnum.DELIVERY.value),
            "article": delivery.program_line.article if delivery.program_line else None,
            "zone": delivery.program_line.zone if delivery.program_line else None,
            "delivery_mode": delivery.program_line.delivery_mode if delivery.program_line else None,
            "collection_sheet": delivery.program_line.collection_sheet if delivery.program_line else None,
            "comment": delivery.program_line.comment if delivery.program_line else None,
            "program_code": delivery.program.program_code if delivery.program else None,
            "unit_price": float(delivery.unit_price_applied) if delivery.unit_price_applied is not None else None,
            "tax_rate": float(delivery.tax_rate_applied) if delivery.tax_rate_applied is not None else None,
            "total_amount": float(delivery.total_amount) if delivery.total_amount is not None else None,
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

    logger.info(f"[BOOTSTRAP] Returning {len(assignments)} assignments for driver {current_user.id}")

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
            "program_types": ["DELIVERY", "COLLECTION"],
            "sync_policy_version": 3,
            "max_delivery_validation_radius_m": 500,
        },
        "today_programs": _load_driver_today_programs(db, current_user.id),
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

    if accepted_count > 0:
        outbox_result = process_pending_outbox_events(db, limit=max(accepted_count * 2, 10))
        response_payload["sage_outbox"] = outbox_result

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


@router.get("/programs/today")
def get_today_programs(
    current_user: User = Depends(require_driver_role),
    db: Session = Depends(get_db)
):
    return _load_driver_today_programs(db, current_user.id)

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
    deliveries = db.query(Delivery).filter(
        Delivery.driver_id == current_user.id,
        Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
    ).order_by(Delivery.scheduled_date).all()

    result = []

    for delivery in deliveries:
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
        Delivery.source_type.in_(["sage_inbound", "sage_program"]),
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

    # Update quantities delivered by driver
    delivery.quantity_6kg = request.quantity_6kg_delivered
    delivery.quantity_12kg = request.quantity_12kg_delivered
    delivery.quantity = request.quantity_6kg_delivered + request.quantity_12kg_delivered
    delivery.delivered_quantity_total = delivery.quantity

    # Recalculate price automatically based on actual quantities delivered
    if delivery.program and delivery.program.program_type == ProgramTypeEnum.DELIVERY:
        from app.services.pricing_service import calculate_delivery_amount, resolve_active_pricing_rule
        pricing_rule = resolve_active_pricing_rule(
            db,
            product_code=delivery.program_line.product_code if delivery.program_line else "",
            depot_id=delivery.depot_id,
        )
        unit_price = pricing_rule.unit_price if pricing_rule else (delivery.unit_price_applied or 0)
        tax_rate = pricing_rule.tax_rate if pricing_rule else (delivery.tax_rate_applied or 0)

        amounts = calculate_delivery_amount(
            quantity_delivered=delivery.quantity,
            unit_price=unit_price,
            tax_rate=tax_rate,
        )
        delivery.unit_price_applied = unit_price
        delivery.tax_rate_applied = tax_rate
        delivery.subtotal_amount = amounts["subtotal_amount"]
        delivery.tax_amount = amounts["tax_amount"]
        delivery.total_amount = amounts["total_amount"]

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
    
    if delivery.program:
        _refresh_program_status(delivery.program, db=db)

    db.commit()
    result = {
        "id": delivery.id,
        "external_delivery_id": delivery.external_delivery_id,
        "status": delivery.status.value if hasattr(delivery.status, "value") else delivery.status,
        "external_status": delivery.external_status.value if delivery.external_status else None,
        "scheduled_time": delivery.scheduled_date.isoformat() if delivery.scheduled_date else None,
        "completed_at": delivery.actual_end.isoformat() if delivery.actual_end else None,
        "depot_id": delivery.depot_id,
        "depot_name": depot.name if depot else "Dépôt inconnu",
        "quantity_6kg": delivery.quantity_6kg,
        "quantity_12kg": delivery.quantity_12kg,
    }

    return result


class ValidatedProgramInfo(BaseModel):
    """Info sur un programme validé (envoyé à Sage)."""
    program_code: str
    total_lines: int
    total_amount: float
    status: str
    validated_at: Optional[str] = None


@router.get("/driver/validated-programs", response_model=list[ValidatedProgramInfo])
def get_validated_programs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Retourne les programmes validés et envoyés à Sage (status=completed)."""
    try:
        programs = db.query(Program).filter(
            Program.status == "completed",
            Program.source_system == "sage_x3",
        ).order_by(Program.updated_at.desc()).limit(50).all()

        result = []
        for program in programs:
            total_amount = sum(
                (line.total_amount or 0) for line in program.lines
                if line.status != "cancelled"
            )
            result.append(
                ValidatedProgramInfo(
                    program_code=program.program_code,
                    total_lines=len([l for l in program.lines if l.status != "cancelled"]),
                    total_amount=total_amount,
                    status=program.status,
                    validated_at=program.updated_at.isoformat() if program.updated_at else None,
                )
            )

        return result
    except Exception as e:
        logger.error(f"[DRIVER API] Erreur récupération programmes validés: {e}")
        raise HTTPException(status_code=500, detail=str(e))
