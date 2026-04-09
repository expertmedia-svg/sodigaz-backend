"""Idempotent schema migration for Sage driver/truck to mobile user mapping.

Run from the backend folder:

    python migrations/20260409_add_driver_mapping_table.py
"""

import os
import sys

from sqlalchemy import create_engine, text


CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings
from app.database import Base
from app.models import DriverMapping


ENGINE = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)


def migrate() -> None:
    print(f"[migration] Running against {settings.DATABASE_URL}")
    Base.metadata.create_all(bind=ENGINE)
    with ENGINE.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_driver_mappings_sage_driver_truck_idx "
                "ON driver_mappings (sage_driver_code, truck_code)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_driver_mappings_user_active_idx "
                "ON driver_mappings (user_id, is_active)"
            )
        )
    print("[migration] Driver mapping table migration completed successfully.")


if __name__ == "__main__":
    migrate()
