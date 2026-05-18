import json
import logging

from app.database import SessionLocal
from app.routers.integration import sync_sage_programs_from_sql

logger = logging.getLogger(__name__)


def sync_sage_programmes():
    db = SessionLocal()
    try:
        result = sync_sage_programs_from_sql(db)
        return result
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = sync_sage_programmes()
    print(json.dumps(result, indent=2, default=str))
