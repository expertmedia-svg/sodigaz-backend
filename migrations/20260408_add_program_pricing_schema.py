"""Idempotent schema migration for program-driven Sage X3 support.

This repository does not use Alembic. The migration is therefore implemented as
an explicit, repeatable script that:

1. Creates the new program/pricing tables if missing.
2. Adds the compatibility columns on deliveries if missing.
3. Creates the supporting indexes if missing.

Run from the backend folder:

    python migrations/20260408_add_program_pricing_schema.py
"""

import os
import sys

from sqlalchemy import create_engine, inspect, text


CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings
from app.database import Base
from app.models import PricingRule, Program, ProgramLine


ENGINE = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)


PROGRAM_COLUMN_DEFINITIONS = {
    "program_type": "VARCHAR(20) NOT NULL DEFAULT 'DELIVERY'",
    "site_code": "VARCHAR(100)",
    "program_time": "VARCHAR(20)",
}


PROGRAM_LINE_COLUMN_DEFINITIONS = {
    "client_id": "VARCHAR(100)",
    "article": "VARCHAR(100)",
    "zone": "VARCHAR(255)",
    "quantity_collected": "INTEGER NOT NULL DEFAULT 0",
    "delivery_mode": "VARCHAR(50)",
    "collection_sheet": "VARCHAR(100)",
    "comment": "TEXT",
}


DELIVERY_COLUMN_DEFINITIONS = {
    "program_type": "VARCHAR(20)",
    "program_id": "INTEGER",
    "program_line_id": "INTEGER",
    "pricing_rule_id": "INTEGER",
    "delivered_quantity_total": "INTEGER NOT NULL DEFAULT 0",
    "collected_quantity_total": "INTEGER NOT NULL DEFAULT 0",
    "unit_price_applied": "NUMERIC(12, 2)",
    "tax_rate_applied": "NUMERIC(8, 4)",
    "subtotal_amount": "NUMERIC(12, 2)",
    "tax_amount": "NUMERIC(12, 2)",
    "total_amount": "NUMERIC(12, 2)",
}


PROGRAM_INDEX_STATEMENTS = {
    "ix_programs_program_type_migration": "CREATE INDEX IF NOT EXISTS ix_programs_program_type_migration ON programs (program_type)",
    "ix_programs_site_code_migration": "CREATE INDEX IF NOT EXISTS ix_programs_site_code_migration ON programs (site_code)",
}


PROGRAM_LINE_INDEX_STATEMENTS = {
    "ix_program_lines_client_id_migration": "CREATE INDEX IF NOT EXISTS ix_program_lines_client_id_migration ON program_lines (client_id)",
    "ix_program_lines_zone_migration": "CREATE INDEX IF NOT EXISTS ix_program_lines_zone_migration ON program_lines (zone)",
}


DELIVERY_INDEX_STATEMENTS = {
    "ix_deliveries_program_type_migration": "CREATE INDEX IF NOT EXISTS ix_deliveries_program_type_migration ON deliveries (program_type)",
    "ix_deliveries_program_id_migration": "CREATE INDEX IF NOT EXISTS ix_deliveries_program_id_migration ON deliveries (program_id)",
    "ix_deliveries_program_line_id_migration": "CREATE INDEX IF NOT EXISTS ix_deliveries_program_line_id_migration ON deliveries (program_line_id)",
    "ix_deliveries_pricing_rule_id_migration": "CREATE INDEX IF NOT EXISTS ix_deliveries_pricing_rule_id_migration ON deliveries (pricing_rule_id)",
}


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def create_missing_tables() -> None:
    print("[migration] Creating missing tables if needed...")
    Base.metadata.create_all(bind=ENGINE)


def add_missing_columns(table_name: str, definitions: dict[str, str]) -> None:
    inspector = inspect(ENGINE)
    if not _table_exists(inspector, table_name):
        raise RuntimeError(f"The {table_name} table must exist before running this migration.")

    with ENGINE.begin() as connection:
        for column_name, definition in definitions.items():
            if _column_exists(inspector, table_name, column_name):
                print(f"[migration] Column {table_name}.{column_name} already exists")
                continue

            print(f"[migration] Adding {table_name}.{column_name}")
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def create_indexes() -> None:
    print("[migration] Creating supporting indexes if needed...")
    with ENGINE.begin() as connection:
        for name, statement in {
            **PROGRAM_INDEX_STATEMENTS,
            **PROGRAM_LINE_INDEX_STATEMENTS,
            **DELIVERY_INDEX_STATEMENTS,
        }.items():
            print(f"[migration] Ensuring index {name}")
            connection.execute(text(statement))


def migrate() -> None:
    print(f"[migration] Running against {settings.DATABASE_URL}")
    create_missing_tables()
    add_missing_columns("programs", PROGRAM_COLUMN_DEFINITIONS)
    add_missing_columns("program_lines", PROGRAM_LINE_COLUMN_DEFINITIONS)
    add_missing_columns("deliveries", DELIVERY_COLUMN_DEFINITIONS)
    create_indexes()
    print("[migration] Program/pricing schema migration completed successfully.")


if __name__ == "__main__":
    migrate()