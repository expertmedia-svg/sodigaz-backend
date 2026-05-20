from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import (
    Delivery,
    DeliveryStatusEnum,
    Depot,
    DriverMapping,
    DriverMappingStatusEnum,
    IntegrationOutbox,
    PricingRule,
    Program,
    ProgramLine,
    ProgramTypeEnum,
    RoleEnum,
    SageMissionStatusEnum,
    Truck,
    User,
)
from app.schemas import (
    PricingRuleCreate,
    PricingRuleResponse,
    ProgramResponse,
    SageProgramInbound,
    SageRawProgramInbound,
    normalize_sage_raw_to_inbound,
)
import logging

from app.config import settings
from app.services.pricing_service import calculate_delivery_amount, resolve_active_pricing_rule
from app.services.sage_sql_service import lire_programmes_du_jour, lire_tous_programmes_sage
from app.services.sage_x3_service import SageX3Service
from app.time_utils import utc_now, utc_now_iso

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/integration", tags=["integration"])


def _resolved_program_type(raw_value: ProgramTypeEnum | str | None) -> ProgramTypeEnum:
    if isinstance(raw_value, ProgramTypeEnum):
        return raw_value
    normalized = (raw_value or ProgramTypeEnum.DELIVERY.value).strip().upper()
    return ProgramTypeEnum.COLLECTION if normalized in {ProgramTypeEnum.COLLECTION.value, "PCOL"} else ProgramTypeEnum.DELIVERY


def _resolved_line_code(inbound_line) -> str:
    if inbound_line.line_code:
        return inbound_line.line_code
    if inbound_line.external_line_id:
        return inbound_line.external_line_id
    client_ref = inbound_line.client_id or inbound_line.client_code or inbound_line.client_name
    article_ref = inbound_line.article or inbound_line.product_code
    return f"{client_ref}:{article_ref}"


def _find_existing_program_line(program: Program, inbound_line) -> ProgramLine | None:
    resolved_line_code = _resolved_line_code(inbound_line)
    for existing in program.lines:
        if inbound_line.external_line_id and existing.external_line_id == inbound_line.external_line_id:
            return existing
        if existing.line_code == resolved_line_code:
            return existing
    return None


def _line_identity(external_line_id: str | None, line_code: str) -> str:
    return external_line_id or line_code


def _delivery_quantities(product_code: str, quantity: int) -> tuple[int, int]:
    normalized = (product_code or "").upper()
    if "12" in normalized:
        return 0, quantity
    return quantity, 0


def _empty_amounts() -> dict:
    return {
        "unit_price": None,
        "tax_rate": None,
        "subtotal_amount": None,
        "tax_amount": None,
        "total_amount": None,
    }


def _normalize_mapping_code(raw_value: str | None) -> str | None:
    normalized = (raw_value or "").strip().upper()
    return normalized or None


def _ensure_pending_mapping_suggestion(
    db: Session,
    *,
    sage_driver_code: str,
    truck_code: str,
    program_code: str,
) -> str:
    from app.auth import hash_password

    existing_pair = db.query(DriverMapping).filter(
        func.upper(DriverMapping.sage_driver_code) == sage_driver_code,
        func.upper(DriverMapping.truck_code) == truck_code,
    ).first()
    if existing_pair is not None:
        if existing_pair.status == DriverMappingStatusEnum.PENDING_APPROVAL:
            # Auto-activer le mapping en attente
            existing_pair.is_active = True
            existing_pair.status = DriverMappingStatusEnum.ACTIVE
            return "Mapping en attente auto-activé par le programme Sage."
        if existing_pair.status == DriverMappingStatusEnum.INACTIVE:
            # Réactiver le mapping inactif
            existing_pair.is_active = True
            existing_pair.status = DriverMappingStatusEnum.ACTIVE
            return "Mapping inactif réactivé automatiquement par le programme Sage."

    resolved_truck = db.query(Truck).filter(
        func.upper(Truck.license_plate) == truck_code,
        Truck.is_active == True,
    ).first()
    if resolved_truck is None:
        # Auto-créer le camion à partir du matricule Sage
        resolved_truck = Truck(
            license_plate=truck_code,
            is_active=True,
        )
        db.add(resolved_truck)
        db.flush()

    known_driver_links = db.query(DriverMapping).filter(
        func.upper(DriverMapping.sage_driver_code) == sage_driver_code,
    ).all()
    candidate_user_ids = sorted({mapping.user_id for mapping in known_driver_links})

    if len(candidate_user_ids) == 1:
        # Un seul chauffeur lié à ce code Sage, l'utiliser
        candidate_driver = db.query(User).filter(
            User.id == candidate_user_ids[0],
            User.role == RoleEnum.RAVITAILLEUR,
            User.is_active == True,
        ).first()
        if candidate_driver is not None:
            if existing_pair is None:
                db.add(
                    DriverMapping(
                        user_id=candidate_driver.id,
                        sage_driver_code=sage_driver_code,
                        truck_code=truck_code,
                        is_active=True,
                        status=DriverMappingStatusEnum.ACTIVE,
                        auto_created=True,
                        source_program_code=program_code,
                    )
                )
                return "Mapping auto-créé et activé automatiquement."
            else:
                existing_pair.user_id = candidate_driver.id
                existing_pair.is_active = True
                existing_pair.status = DriverMappingStatusEnum.ACTIVE
                existing_pair.auto_created = True
                existing_pair.source_program_code = program_code
                return "Mapping existant réactivé automatiquement."
        else:
            return "Le chauffeur détecté pour YLIV est introuvable ou inactif."

    # Cas: aucun mapping ou mappings multiples
    # Chercher un chauffeur rattaché au camion
    if resolved_truck.driver_id is not None:
        candidate_driver = db.query(User).filter(
            User.id == resolved_truck.driver_id,
            User.role == RoleEnum.RAVITAILLEUR,
            User.is_active == True,
        ).first()
        if candidate_driver is not None:
            db.add(
                DriverMapping(
                    user_id=candidate_driver.id,
                    sage_driver_code=sage_driver_code,
                    truck_code=truck_code,
                    is_active=True,
                    status=DriverMappingStatusEnum.ACTIVE,
                    auto_created=True,
                    source_program_code=program_code,
                )
            )
            return "Mapping auto-créé et activé via le chauffeur rattaché au camion."

    # Cas: aucun chauffeur trouvé → créer automatiquement le chauffeur
    normalized_code = sage_driver_code.lower().strip()
    email = f"{normalized_code}@sodigaz-app.local"
    username = normalized_code

    # Vérifier que le chauffeur n'existe pas
    existing_driver = db.query(User).filter(
        func.upper(User.email) == email.upper()
    ).first()

    if existing_driver and existing_driver.is_active and existing_driver.role == RoleEnum.RAVITAILLEUR:
        candidate_driver = existing_driver
        msg = "Chauffeur existant trouvé lors de la création auto; "
    else:
        # Créer le nouveau chauffeur
        password = f"Code{sage_driver_code.upper()}@2026"
        candidate_driver = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            full_name=f"Chauffeur {sage_driver_code}",
            phone=None,
            role=RoleEnum.RAVITAILLEUR,
            is_active=True,
        )
        db.add(candidate_driver)
        db.flush()
        msg = f"Chauffeur créé auto: {email} / {password}; "

    # Créer le mapping avec le chauffeur
    db.add(
        DriverMapping(
            user_id=candidate_driver.id,
            sage_driver_code=sage_driver_code,
            truck_code=truck_code,
            is_active=True,
            status=DriverMappingStatusEnum.ACTIVE,
            auto_created=True,
            source_program_code=program_code,
        )
    )
    return f"{msg}mapping auto-créé et activé pour le programme {program_code}."


def _resolve_program_assignment(db: Session, payload: SageProgramInbound) -> tuple[User | None, Truck | None, str, str | None, str | None, str | None]:
    sage_driver_code = _normalize_mapping_code(payload.sage_driver_code)
    truck_code = _normalize_mapping_code(payload.truck_code)

    resolved_driver: User | None = None
    resolved_truck: Truck | None = None
    assignment_reason: str | None = None

    if payload.truck_id is not None or payload.driver_id is not None:
        if payload.truck_id is not None:
            resolved_truck = db.query(Truck).filter(Truck.id == payload.truck_id).first()
            if resolved_truck is None:
                raise HTTPException(status_code=404, detail=f"Camion introuvable: {payload.truck_id}")

        if payload.driver_id is not None:
            resolved_driver = db.query(User).filter(
                User.id == payload.driver_id,
                User.role == RoleEnum.RAVITAILLEUR,
            ).first()
            if resolved_driver is None:
                raise HTTPException(status_code=404, detail=f"Livreur introuvable: {payload.driver_id}")
        elif resolved_truck is not None and resolved_truck.driver_id is not None:
            resolved_driver = db.query(User).filter(
                User.id == resolved_truck.driver_id,
                User.role == RoleEnum.RAVITAILLEUR,
            ).first()

        if resolved_driver and resolved_truck and resolved_truck.driver_id not in (None, resolved_driver.id):
            return None, resolved_truck, "UNASSIGNED", "Le camion explicite ne correspond pas au chauffeur explicite.", sage_driver_code, truck_code

        if resolved_driver is None:
            return None, resolved_truck, "UNASSIGNED", "Aucun chauffeur resolu a partir des identifiants internes fournis.", sage_driver_code, truck_code

        return resolved_driver, resolved_truck, payload.status, None, sage_driver_code, truck_code

    if not sage_driver_code or not truck_code:
        return None, None, "UNASSIGNED", "Codes Sage incomplets: YLIV et YMATCAM sont requis pour l'affectation mobile.", sage_driver_code, truck_code

    mapping = db.query(DriverMapping).filter(
        func.upper(DriverMapping.sage_driver_code) == sage_driver_code,
        func.upper(DriverMapping.truck_code) == truck_code,
        DriverMapping.status == DriverMappingStatusEnum.ACTIVE,
        DriverMapping.is_active == True,
    ).first()
    if mapping is None:
        assignment_reason = _ensure_pending_mapping_suggestion(
            db,
            sage_driver_code=sage_driver_code,
            truck_code=truck_code,
            program_code=payload.program_code,
        )
        db.flush()
        # Re-chercher le mapping après auto-activation
        mapping = db.query(DriverMapping).filter(
            func.upper(DriverMapping.sage_driver_code) == sage_driver_code,
            func.upper(DriverMapping.truck_code) == truck_code,
            DriverMapping.status == DriverMappingStatusEnum.ACTIVE,
            DriverMapping.is_active == True,
        ).first()
        if mapping is None:
            return None, None, "UNASSIGNED", assignment_reason, sage_driver_code, truck_code

    resolved_driver = db.query(User).filter(
        User.id == mapping.user_id,
        User.role == RoleEnum.RAVITAILLEUR,
        User.is_active == True,
    ).first()
    if resolved_driver is None:
        return None, None, "UNASSIGNED", "Le mapping pointe vers un livreur introuvable ou inactif.", sage_driver_code, truck_code

    resolved_truck = db.query(Truck).filter(
        func.upper(Truck.license_plate) == truck_code,
        Truck.is_active == True,
    ).first()
    if resolved_truck is None:
        return None, None, "UNASSIGNED", "Le camion YMATCAM n'existe pas dans le referentiel local.", sage_driver_code, truck_code

    if resolved_truck.driver_id not in (None, resolved_driver.id):
        assignment_reason = (
            "Affectation resolue via le mapping actif YLIV + YMATCAM; "
            "le camion local est partage et n'est pas rattache statiquement a ce chauffeur."
        )

    return resolved_driver, resolved_truck, payload.status, assignment_reason, sage_driver_code, truck_code


def _upsert_delivery_from_program_line(db: Session, program: Program, program_line: ProgramLine) -> Delivery:
    delivery = db.query(Delivery).filter(Delivery.program_line_id == program_line.id).first()

    quantity_6kg, quantity_12kg = _delivery_quantities(
        program_line.product_code,
        program_line.quantity_planned,
    )

    if delivery is None:
        delivery = Delivery(
            truck_id=program.truck_id,
            depot_id=program.depot_id,
            destination_name=program_line.client_name,
            destination_address=program_line.destination_address,
            destination_latitude=program_line.destination_latitude,
            destination_longitude=program_line.destination_longitude,
            contact_name=program_line.contact_name,
            contact_phone=program_line.contact_phone,
            driver_id=program.driver_id,
            quantity_6kg=quantity_6kg,
            quantity_12kg=quantity_12kg,
            quantity=program_line.quantity_planned,
            status=DeliveryStatusEnum.PENDING,
            source_type="sage_inbound",
            external_status=SageMissionStatusEnum.PENDING_APPROVAL,
            external_delivery_id=f"{program.program_code}:{program_line.line_code}",
            scheduled_date=program.program_date,
            notes=f"Programme Sage X3 {program.program_code}",
            program_type=program.program_type.value,
            program_id=program.id,
            program_line_id=program_line.id,
            pricing_rule_id=program_line.pricing_rule_id,
            unit_price_applied=program_line.unit_price,
            tax_rate_applied=program_line.tax_rate,
            subtotal_amount=program_line.subtotal_amount,
            tax_amount=program_line.tax_amount,
            total_amount=program_line.total_amount,
            delivered_quantity_total=program_line.quantity_delivered or 0,
            collected_quantity_total=program_line.quantity_collected or 0,
        )
        db.add(delivery)
        db.flush()
    elif delivery.status != DeliveryStatusEnum.COMPLETED:
        delivery.truck_id = program.truck_id
        delivery.depot_id = program.depot_id
        delivery.destination_name = program_line.client_name
        delivery.destination_address = program_line.destination_address
        delivery.destination_latitude = program_line.destination_latitude
        delivery.destination_longitude = program_line.destination_longitude
        delivery.contact_name = program_line.contact_name
        delivery.contact_phone = program_line.contact_phone
        delivery.driver_id = program.driver_id
        delivery.quantity_6kg = quantity_6kg
        delivery.quantity_12kg = quantity_12kg
        delivery.quantity = program_line.quantity_planned
        delivery.scheduled_date = program.program_date
        delivery.program_type = program.program_type.value
        delivery.program_id = program.id
        delivery.program_line_id = program_line.id
        delivery.pricing_rule_id = program_line.pricing_rule_id
        delivery.unit_price_applied = program_line.unit_price
        delivery.tax_rate_applied = program_line.tax_rate
        delivery.subtotal_amount = program_line.subtotal_amount
        delivery.tax_amount = program_line.tax_amount
        delivery.total_amount = program_line.total_amount
        delivery.delivered_quantity_total = program_line.quantity_delivered or 0
        delivery.collected_quantity_total = program_line.quantity_collected or 0
    return delivery


def _serialize_program(program: Program) -> dict:
    return ProgramResponse.model_validate(program).model_dump(mode="json")


@router.post("/sage/programs/raw")
def upsert_sage_program_raw(
    raw_payload: SageRawProgramInbound,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint qui accepte le JSON natif Sage X3 (header + lines avec noms de
    champs Sage : YTRSTYP, YNUMPROG, YLIV, YMATCAM, YBPC, YITMREF, YQTY…).
    Le backend normalise automatiquement vers le format interne puis délègue
    au traitement standard upsert_sage_program.
    """
    sage_service = SageX3Service(db)
    if not sage_service.validate_inbound_headers(request.headers):
        raise HTTPException(status_code=401, detail="Invalid Sage X3 token")

    # Normaliser le payload Sage brut
    normalized = normalize_sage_raw_to_inbound(raw_payload)

    # Résoudre le depot_id à partir du code site YFCY
    site_code = raw_payload.header.YFCY.strip().upper()
    depot = db.query(Depot).filter(
        func.upper(Depot.site_code) == site_code
    ).first()
    if depot is None and raw_payload.header.YFCYNAM:
        # Fallback : chercher par nom (ex: YFCYNAM="Depot Balole")
        depot = db.query(Depot).filter(
            Depot.name.ilike(f"%{raw_payload.header.YFCYNAM}%")
        ).first()
        # Mémoriser le site_code pour les prochains appels
        if depot is not None:
            depot.site_code = site_code
            db.flush()
    if depot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun dépôt trouvé pour YFCY='{site_code}' / YFCYNAM='{raw_payload.header.YFCYNAM or ''}'. "
                   f"Créez le dépôt ou vérifiez le nom dans l'admin.",
        )

    normalized.depot_id = depot.id

    # Auto-incrémenter sync_version si le programme existe déjà
    existing_program = db.query(Program).filter(
        Program.program_code == normalized.program_code
    ).first()
    if existing_program is not None:
        normalized.sync_version = existing_program.sync_version + 1

    return _process_sage_program(normalized, db)


@router.post("/sage/programs")
def upsert_sage_program(
    payload: SageProgramInbound,
    request: Request,
    db: Session = Depends(get_db),
):
    sage_service = SageX3Service(db)
    if not sage_service.validate_inbound_headers(request.headers):
        raise HTTPException(status_code=401, detail="Invalid Sage X3 token")

    return _process_sage_program(payload, db)


def _process_sage_program(payload: SageProgramInbound, db: Session):
    """Logique métier partagée par /sage/programs et /sage/programs/raw."""
    depot = db.query(Depot).filter(Depot.id == payload.depot_id).first()
    if depot is None:
        raise HTTPException(status_code=404, detail=f"Depot introuvable: {payload.depot_id}")

    resolved_driver, resolved_truck, resolved_status, assignment_reason, sage_driver_code, truck_code = _resolve_program_assignment(db, payload)

    existing_message = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.external_message_id == f"sage_program:{payload.program_code}:v{payload.sync_version}"
    ).first()

    program = db.query(Program).filter(Program.program_code == payload.program_code).first()
    created = program is None
    program_type = _resolved_program_type(payload.program_type)
    if program is None:
        program = Program(program_code=payload.program_code)
        db.add(program)

    program.program_type = program_type
    program.site_code = payload.site
    program.program_date = datetime.combine(payload.date, time.min)
    program.program_time = payload.time
    program.depot_id = payload.depot_id
    program.truck_id = resolved_truck.id if resolved_truck else None
    program.driver_id = resolved_driver.id if resolved_driver else None
    program.transporter_name = payload.transporter
    program.status = resolved_status
    program.sync_version = payload.sync_version
    program.source_updated_at = payload.source_updated_at
    program.source_payload = {
        **payload.model_dump(mode="json"),
        "assignment": {
            "status": resolved_status,
            "reason": assignment_reason,
            "assigned_user_id": resolved_driver.id if resolved_driver else None,
            "assigned_truck_id": resolved_truck.id if resolved_truck else None,
            "sage_driver_code": sage_driver_code,
            "truck_code": truck_code,
            "security_rule": "server_side_filtering_only",
        },
    }
    db.flush()

    synced_deliveries = 0
    processed_line_keys: set[str] = set()
    for inbound_line in payload.lines:
        line_code = _resolved_line_code(inbound_line)
        processed_line_keys.add(_line_identity(inbound_line.external_line_id, line_code))
        program_line = _find_existing_program_line(program, inbound_line)
        if program_line is None:
            program_line = ProgramLine(program_id=program.id, line_code=line_code)
            db.add(program_line)

        delivered_quantity = inbound_line.quantity_delivered or program_line.quantity_delivered or 0
        collected_quantity = inbound_line.quantity_collected or program_line.quantity_collected or 0
        pricing_rule = None
        if program_type == ProgramTypeEnum.DELIVERY:
            preview_quantity = delivered_quantity if delivered_quantity > 0 else inbound_line.quantity_planned
            pricing_rule = resolve_active_pricing_rule(
                db,
                product_code=inbound_line.product_code,
                depot_id=payload.depot_id,
            )
            unit_price = inbound_line.unit_price
            tax_rate = inbound_line.tax_rate
            if pricing_rule is not None:
                unit_price = pricing_rule.unit_price
                tax_rate = pricing_rule.tax_rate
            if unit_price is None:
                unit_price = 0
            if tax_rate is None:
                tax_rate = 0
            amounts = calculate_delivery_amount(
                quantity_delivered=preview_quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
            )
        else:
            amounts = _empty_amounts()

        program_line.external_line_id = inbound_line.external_line_id
        program_line.line_code = line_code
        program_line.client_id = inbound_line.client_id or inbound_line.client_code
        program_line.client_code = inbound_line.client_code
        program_line.client_name = inbound_line.client_name
        program_line.destination_address = inbound_line.destination_address
        program_line.destination_latitude = inbound_line.destination_latitude
        program_line.destination_longitude = inbound_line.destination_longitude
        program_line.contact_name = inbound_line.contact_name
        program_line.contact_phone = inbound_line.contact_phone
        program_line.product_code = inbound_line.product_code
        program_line.product_label = inbound_line.product_label
        program_line.article = inbound_line.article
        program_line.zone = inbound_line.zone
        program_line.quantity_planned = inbound_line.quantity_planned
        program_line.quantity_delivered = delivered_quantity
        program_line.quantity_collected = collected_quantity
        program_line.pricing_rule_id = pricing_rule.id if pricing_rule else None
        program_line.unit_price = amounts["unit_price"]
        program_line.tax_rate = amounts["tax_rate"]
        program_line.subtotal_amount = amounts["subtotal_amount"]
        program_line.tax_amount = amounts["tax_amount"]
        program_line.total_amount = amounts["total_amount"]
        program_line.delivery_mode = inbound_line.delivery_mode
        program_line.collection_sheet = inbound_line.collection_sheet
        program_line.comment = inbound_line.comment
        if program_type == ProgramTypeEnum.COLLECTION:
            program_line.status = "collected" if collected_quantity >= inbound_line.quantity_planned and inbound_line.quantity_planned > 0 else ("partial" if collected_quantity > 0 else "pending")
        else:
            program_line.status = "delivered" if delivered_quantity >= inbound_line.quantity_planned and inbound_line.quantity_planned > 0 else ("partial" if delivered_quantity > 0 else "pending")
        db.flush()

        _upsert_delivery_from_program_line(db, program, program_line)
        synced_deliveries += 1

    for existing_line in program.lines:
        if _line_identity(existing_line.external_line_id, existing_line.line_code) in processed_line_keys:
            continue
        existing_line.status = "cancelled"
        if existing_line.delivery and existing_line.delivery.status != DeliveryStatusEnum.COMPLETED:
            existing_line.delivery.status = DeliveryStatusEnum.CANCELLED

    if existing_message is None:
        db.add(
            IntegrationOutbox(
                event_type="program_upserted",
                direction="inbound",
                system_name="sage_x3",
                aggregate_type="program",
                aggregate_id=payload.program_code,
                external_message_id=f"sage_program:{payload.program_code}:v{payload.sync_version}",
                status="sent",
                payload_json=payload.model_dump(mode="json"),
                response_json={"received_at": utc_now_iso()},
                sent_at=utc_now(),
            )
        )

    db.commit()
    db.refresh(program)

    return {
        "success": True,
        "status": "created" if created else "updated",
        "program_code": program.program_code,
        "program_id": program.id,
        "line_count": len(program.lines),
        "delivery_projection_count": synced_deliveries,
        "replayed": existing_message is not None,
        "program": _serialize_program(program),
    }


def _build_sage_program_payload_from_sql(program: dict, db: Session) -> SageProgramInbound:
    site_code = (program.get("site") or "").strip().upper()
    if not site_code:
        raise ValueError("Le programme Sage doit contenir un code de site YFCY")

    depot = db.query(Depot).filter(func.upper(Depot.site_code) == site_code).first()
    if depot is None:
        raise ValueError(f"Dépôt introuvable pour site Sage '{site_code}'")

    program_code = (program.get("program_code") or "").strip()
    existing_program = db.query(Program).filter(Program.program_code == program_code).first()
    payload = {
        "program_code": program_code,
        "program_type": program.get("program_type", "DELIVERY"),
        "site": site_code,
        "date": program.get("date"),
        "time": program.get("time"),
        "depot_id": depot.id,
        "sage_driver_code": program.get("sage_driver_code"),
        "truck_code": program.get("truck_code"),
        "transporter": program.get("transporter"),
        "status": "active",
        "source_updated_at": utc_now(),
        "sync_version": (existing_program.sync_version + 1) if existing_program else 1,
        "lines": [],
    }

    for line in program.get("lines", []):
        line_number = line.get("line")
        line_code = f"{program_code}:{line_number}" if line_number is not None else None
        client_code = (line.get("client_code") or "").strip()
        product_code = (line.get("article") or line.get("product_code") or "").strip() or "UNKNOWN"
        payload["lines"].append({
            "external_line_id": (line.get("num_fiche") or "").strip() or None,
            "line_code": line_code,
            "client_id": client_code or None,
            "client_code": client_code or None,
            "client_name": client_code or f"Client_{line_number}",
            "destination_address": (line.get("zone") or "").strip() or None,
            "zone": (line.get("zone") or "").strip() or None,
            "product_code": product_code,
            "product_label": None,
            "article": product_code,
            "quantity_planned": int(float(line.get("quantite") or 0)),
            "quantity_delivered": 0,
            "quantity_collected": 0,
            "delivery_mode": (line.get("mode_livr") or "").strip() or None,
            "collection_sheet": (line.get("num_fiche") or "").strip() or None,
            "comment": (line.get("designation") or "").strip() or None,
        })

    return SageProgramInbound.model_validate(payload)


def sync_sage_programs_from_sql(db: Session) -> dict:
    try:
        programs = lire_programmes_du_jour()
    except Exception as e:
        logger.error(f"[SAGE SQL SYNC] Erreur connexion Sage SQL: {e}")
        return {
            "synced": 0,
            "created": 0,
            "updated": 0,
            "errors": [{"error": f"Sage SQL connection failed: {str(e)}"}],
        }

    result = {
        "synced": 0,
        "created": 0,
        "updated": 0,
        "errors": [],
        "debug_info": {
            "programs_found": len(programs),
        }
    }

    for program in programs:
        try:
            payload = _build_sage_program_payload_from_sql(program, db)
            response = _process_sage_program(payload, db)
            result["synced"] += 1
            if response.get("status") == "created":
                result["created"] += 1
            else:
                result["updated"] += 1
        except Exception as exc:
            logger.error(f"[SAGE SQL SYNC] Erreur programme {program.get('program_code')}: {exc}")
            result["errors"].append({
                "program_code": program.get("program_code"),
                "error": str(exc),
            })

    return result


@router.post("/sage/sync-today")
def sync_sage_programs_today(
    db: Session = Depends(get_db),
    current_user=Depends(require_role(RoleEnum.ADMIN)),
):
    return sync_sage_programs_from_sql(db)


@router.get("/programs", response_model=list[ProgramResponse])
def list_programs(
    status: str | None = Query(default=None),
    program_type: ProgramTypeEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(RoleEnum.ADMIN)),
):
    query = db.query(Program).order_by(Program.program_date.desc(), Program.updated_at.desc())
    if status:
        query = query.filter(Program.status == status)
    if program_type:
        query = query.filter(Program.program_type == program_type)
    return query.limit(limit).all()


@router.get("/programs/{program_code}", response_model=ProgramResponse)
def get_program(
    program_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(RoleEnum.ADMIN)),
):
    program = db.query(Program).filter(Program.program_code == program_code).first()
    if program is None:
        raise HTTPException(status_code=404, detail="Programme introuvable")
    return program


@router.get("/sage/test-connection")
def test_sage_connection():
    """Test la connexion Sage SQL (public - pour diagnostiquer)."""
    try:
        from app.services.sage_sql_service import get_sage_sql_connection
        conn = get_sage_sql_connection()
        cursor = conn.cursor()
        database = settings.SAGE_SQL_DATABASE
        schema = settings.SAGE_SQL_SCHEMA

        # Test 1: Count ALL programs
        cursor.execute(f"USE {database}")
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.YPRGCOLL")
        all_count = cursor.fetchone()[0]

        # Test 2: Count programs with YFLGVAL2_0=1
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.YPRGCOLL WHERE YFLGVAL2_0=1")
        yflgval2_1_count = cursor.fetchone()[0]

        # Test 3: Count programs with correct date
        cursor.execute(f"""
            SELECT COUNT(*) FROM {schema}.YPRGCOLL
            WHERE CAST(YDATE_0 AS DATE) >= CAST(DATEADD(day, -1, GETDATE()) AS DATE)
        """)
        date_count = cursor.fetchone()[0]

        # Test 4: Count programs with BOTH conditions
        cursor.execute(f"""
            SELECT COUNT(*) FROM {schema}.YPRGCOLL
            WHERE YFLGVAL2_0=1
            AND CAST(YDATE_0 AS DATE) >= CAST(DATEADD(day, -1, GETDATE()) AS DATE)
        """)
        final_count = cursor.fetchone()[0]

        conn.close()

        return {
            "status": "ok",
            "database": database,
            "schema": schema,
            "programs_total": all_count,
            "programs_yflgval2_1": yflgval2_1_count,
            "programs_recent_date": date_count,
            "programs_matching_filter": final_count
        }
    except Exception as e:
        logger.error(f"[SAGE SQL TEST] Error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/sage/diagnostic")
def sage_sync_diagnostic(
    db: Session = Depends(get_db),
    current_user=Depends(require_role(RoleEnum.ADMIN)),
):
    """Diagnostic endpoint to debug why programs aren't being synced."""
    try:
        # Get all programs from Sage SQL
        sage_programs = lire_tous_programmes_sage()

        # Get all depots from database with their site codes
        depots = db.query(Depot).all()
        depot_map = {d.site_code.upper(): d for d in depots if d.site_code}

        # Get all programs from database
        db_programs = db.query(Program).all()
        db_program_codes = {p.program_code for p in db_programs}

        # Check which Sage programs match depot site codes
        unmapped_sites = set()
        mapped_count = 0
        for prog in sage_programs:
            site = prog["site"].upper() if prog["site"] else None
            if site and site in depot_map:
                mapped_count += 1
            elif site:
                unmapped_sites.add(site)

        return {
            "sage_programs_count": len(sage_programs),
            "sage_programs": sage_programs[:20],  # First 20 for inspection
            "depots_in_db": [
                {
                    "id": d.id,
                    "name": d.name,
                    "site_code": d.site_code,
                }
                for d in depots
            ],
            "depot_site_code_map": list(depot_map.keys()),
            "unmapped_sage_sites": list(unmapped_sites),
            "sage_programs_already_synced": list(db_program_codes),
            "sync_status": {
                "total_sage_programs": len(sage_programs),
                "depot_sites_mapped": mapped_count,
                "depot_sites_unmapped": len(unmapped_sites),
                "programs_in_db": len(db_programs),
            }
        }
    except Exception as exc:
        logger.exception("Error in sage sync diagnostic")
        return {
            "error": str(exc),
            "message": "Failed to retrieve diagnostic information",
        }


@router.get("/pricing-rules", response_model=list[PricingRuleResponse])
def list_pricing_rules(
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user=Depends(require_role(RoleEnum.ADMIN)),
):
    query = db.query(PricingRule).order_by(PricingRule.product_code.asc(), PricingRule.updated_at.desc())
    if active_only:
        query = query.filter(PricingRule.active == True)
    return query.all()


@router.post("/pricing-rules", response_model=PricingRuleResponse)
def create_pricing_rule(
    payload: PricingRuleCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role(RoleEnum.ADMIN)),
):
    pricing_rule = PricingRule(**payload.model_dump())
    db.add(pricing_rule)
    db.commit()
    db.refresh(pricing_rule)
    return pricing_rule