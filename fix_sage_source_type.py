"""
Fix existing deliveries with source_type='sage_program' that have no external_status.
Sets external_status to 'pending_approval' so they appear in the Sage X3 missions admin page.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import SessionLocal
from app.models import Delivery

db = SessionLocal()

try:
    updated = db.execute(text(
        """
        UPDATE deliveries
        SET external_status = 'pending_approval'
        WHERE source_type = 'sage_program'
          AND external_status IS NULL
        """
    ))
    count = updated.rowcount
    db.commit()
    print(f"✅ {count} delivery(ies) corrigée(s) : external_status → 'pending_approval'")
except Exception as e:
    db.rollback()
    print(f"❌ Erreur : {e}")
finally:
    db.close()
