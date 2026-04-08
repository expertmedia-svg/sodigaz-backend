from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.orm import Session

from app.models import PricingRule, ProgramLine


TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")


def _to_decimal(value: Optional[object], default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_amount(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(FOURPLACES, rounding=ROUND_HALF_UP)


def resolve_active_pricing_rule(
    db: Session,
    *,
    product_code: str,
    depot_id: Optional[int] = None,
) -> Optional[PricingRule]:
    scoped_rule = None
    if depot_id is not None:
        scoped_rule = (
            db.query(PricingRule)
            .filter(
                PricingRule.active == True,
                PricingRule.product_code == product_code,
                PricingRule.depot_id == depot_id,
            )
            .order_by(PricingRule.updated_at.desc())
            .first()
        )
    if scoped_rule is not None:
        return scoped_rule

    return (
        db.query(PricingRule)
        .filter(
            PricingRule.active == True,
            PricingRule.product_code == product_code,
            PricingRule.depot_id.is_(None),
        )
        .order_by(PricingRule.updated_at.desc())
        .first()
    )


def calculate_delivery_amount(
    *,
    quantity_delivered: int,
    unit_price: Decimal,
    tax_rate: Decimal,
) -> dict[str, Decimal]:
    quantity = Decimal(quantity_delivered)
    normalized_unit_price = quantize_amount(_to_decimal(unit_price))
    normalized_tax_rate = quantize_rate(_to_decimal(tax_rate))
    subtotal_amount = quantize_amount(quantity * normalized_unit_price)
    tax_amount = quantize_amount(subtotal_amount * normalized_tax_rate)
    total_amount = quantize_amount(subtotal_amount + tax_amount)
    return {
        "unit_price": normalized_unit_price,
        "tax_rate": normalized_tax_rate,
        "subtotal_amount": subtotal_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
    }


def resolve_program_line_amount(
    db: Session,
    *,
    program_line: ProgramLine,
    quantity_delivered: int,
    depot_id: Optional[int] = None,
) -> tuple[Optional[PricingRule], dict[str, Decimal]]:
    pricing_rule = resolve_active_pricing_rule(
        db,
        product_code=program_line.product_code,
        depot_id=depot_id,
    )

    unit_price = _to_decimal(program_line.unit_price)
    tax_rate = _to_decimal(program_line.tax_rate)
    if pricing_rule is not None:
        unit_price = _to_decimal(pricing_rule.unit_price)
        tax_rate = _to_decimal(pricing_rule.tax_rate)

    amount_breakdown = calculate_delivery_amount(
        quantity_delivered=quantity_delivered,
        unit_price=unit_price,
        tax_rate=tax_rate,
    )
    return pricing_rule, amount_breakdown