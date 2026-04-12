"""Idempotent schema migration for depot map metadata.

Adds the metadata needed by the national depot-mapping experience:
- quartier
- plv_code
- maps_url

Run from the backend folder:

    python migrations/20260412_add_depot_map_metadata.py
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
from app.models import Depot


ENGINE = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

DEPOT_COLUMN_DEFINITIONS = {
    "quartier": "VARCHAR(255)",
    "plv_code": "VARCHAR(100)",
    "maps_url": "VARCHAR(1000)",
}

DEPOT_INDEX_STATEMENTS = {
    "ix_depots_plv_code_migration": "CREATE INDEX IF NOT EXISTS ix_depots_plv_code_migration ON depots (plv_code)",
    "ix_depots_city_migration": "CREATE INDEX IF NOT EXISTS ix_depots_city_migration ON depots (city)",
    "ix_depots_quartier_migration": "CREATE INDEX IF NOT EXISTS ix_depots_quartier_migration ON depots (quartier)",
}


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def create_missing_tables() -> None:
    Base.metadata.create_all(bind=ENGINE, tables=[Depot.__table__])


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
    with ENGINE.begin() as connection:
        for name, statement in DEPOT_INDEX_STATEMENTS.items():
            print(f"[migration] Ensuring index {name}")
            connection.execute(text(statement))


def migrate() -> None:
    print(f"[migration] Running against {settings.DATABASE_URL}")
    create_missing_tables()
    add_missing_columns("depots", DEPOT_COLUMN_DEFINITIONS)
    create_indexes()
    print("[migration] Depot map metadata migration completed successfully.")


if __name__ == "__main__":
    migrate()
