"""Add status fields for driver mapping suggestions.

Run from the backend folder:

    python migrations/20260414_add_driver_mapping_status_fields.py
"""

import os
import sys

from sqlalchemy import create_engine, text


CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings


ENGINE = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)


def _has_column(connection, table_name: str, column_name: str) -> bool:
    result = connection.execute(text(f"SELECT * FROM {table_name} LIMIT 0"))
    return column_name in result.keys()


def migrate() -> None:
    print(f"[migration] Running against {settings.DATABASE_URL}")
    with ENGINE.begin() as connection:
        if not _has_column(connection, "driver_mappings", "status"):
            connection.execute(text("ALTER TABLE driver_mappings ADD COLUMN status VARCHAR(30) DEFAULT 'active' NOT NULL"))
        if not _has_column(connection, "driver_mappings", "auto_created"):
            connection.execute(text("ALTER TABLE driver_mappings ADD COLUMN auto_created BOOLEAN DEFAULT FALSE NOT NULL"))
        if not _has_column(connection, "driver_mappings", "source_program_code"):
            connection.execute(text("ALTER TABLE driver_mappings ADD COLUMN source_program_code VARCHAR(100) NULL"))

        connection.execute(text("UPDATE driver_mappings SET status = CASE WHEN is_active THEN 'active' ELSE 'inactive' END WHERE status IS NULL OR status = ''"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_driver_mappings_status_idx ON driver_mappings (status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_driver_mappings_source_program_code_idx ON driver_mappings (source_program_code)"))
    print("[migration] Driver mapping status migration completed successfully.")


if __name__ == "__main__":
    migrate()