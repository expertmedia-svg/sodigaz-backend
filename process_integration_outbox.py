from app.database import SessionLocal
from app.services.outbox_worker import process_pending_outbox_events


def main():
    db = SessionLocal()
    try:
        result = process_pending_outbox_events(db)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()