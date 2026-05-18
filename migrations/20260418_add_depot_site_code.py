"""Ajoute la colonne site_code sur la table depots pour résoudre YFCY → depot_id.

Run from the backend folder:

    python migrations/20260418_add_depot_site_code.py
"""

import os
import sys

from sqlalchemy import create_engine, inspect, text

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings

ENGINE = create_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

COLUMN_NAME = "site_code"
TABLE_NAME = "depots"


def _column_exists(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _index_exists(inspector, table: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def migrate():
    inspector = inspect(ENGINE)

    if TABLE_NAME not in inspector.get_table_names():
        print(f"Table {TABLE_NAME} n'existe pas encore, migration ignorée.")
        return

    with ENGINE.begin() as conn:
        if not _column_exists(inspector, TABLE_NAME, COLUMN_NAME):
            conn.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {COLUMN_NAME} VARCHAR(50)"))
            print(f"  + Colonne {COLUMN_NAME} ajoutée sur {TABLE_NAME}")
        else:
            print(f"  = Colonne {COLUMN_NAME} existe déjà sur {TABLE_NAME}")

        idx_name = "ix_depots_site_code"
        if not _index_exists(inspector, TABLE_NAME, idx_name):
            conn.execute(text(f"CREATE UNIQUE INDEX {idx_name} ON {TABLE_NAME} ({COLUMN_NAME})"))
            print(f"  + Index {idx_name} créé")
        else:
            print(f"  = Index {idx_name} existe déjà")

    print("Migration 20260418_add_depot_site_code terminée.")


if __name__ == "__main__":
    migrate()
