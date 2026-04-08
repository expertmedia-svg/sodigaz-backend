from datetime import datetime, time

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import (
    Delivery,
    DeliveryStatusEnum,
    Depot,
    IntegrationOutbox,
    PricingRule,
    Program,
    ProgramLine,
    ProgramTypeEnum,
    RoleEnum,
    Truck,
    User,
)
from app.schemas import (
    PricingRuleCreate,
    PricingRuleResponse,
    ProgramResponse,
    SageProgramInbound,
)
from app.services.pricing_service import calculate_delivery_amount, resolve_active_pricing_rule
from app.services.sage_x3_service import SageX3Service
from app.time_utils import utc_now, utc_now_iso


router = APIRouter(prefix="/api/integration", tags=["integration"])


def _resolved_program_type(raw_value: ProgramTypeEnum | str | None) -> ProgramTypeEnum:
    if isinstance(raw_value, ProgramTypeEnum):
        return raw_value
    normalized = (raw_value or ProgramTypeEnum.DELIVERY.value).strip().upper()
    return ProgramTypeEnum.COLLECTION if normalized == ProgramTypeEnum.COLLECTION.value else ProgramTypeEnum.DELIVERY


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
            source_type="sage_program",
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


@router.post("/sage/programs")
def upsert_sage_program(
    payload: SageProgramInbound,
    db: Session = Depends(get_db),
    x_sage_x3_token: str | None = Header(default=None),
):
    sage_service = SageX3Service(db)
    if not sage_service.validate_sage_token(x_sage_x3_token or ""):
        raise HTTPException(status_code=401, detail="Invalid Sage X3 token")

    depot = db.query(Depot).filter(Depot.id == payload.depot_id).first()
    if depot is None:
        raise HTTPException(status_code=404, detail=f"Depot introuvable: {payload.depot_id}")

    if payload.truck_id is not None:
        truck = db.query(Truck).filter(Truck.id == payload.truck_id).first()
        if truck is None:
            raise HTTPException(status_code=404, detail=f"Camion introuvable: {payload.truck_id}")

    if payload.driver_id is not None:
        driver = db.query(User).filter(User.id == payload.driver_id).first()
        if driver is None:
            raise HTTPException(status_code=404, detail=f"Livreur introuvable: {payload.driver_id}")

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
    program.truck_id = payload.truck_id
    program.driver_id = payload.driver_id
    program.transporter_name = payload.transporter
    program.status = payload.status
    program.sync_version = payload.sync_version
    program.source_updated_at = payload.source_updated_at
    program.source_payload = payload.model_dump(mode="json")
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
                quantity_delivered=delivered_quantity,
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