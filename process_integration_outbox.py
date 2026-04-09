import argparse
import json

from app.database import SessionLocal
from app.services.outbox_worker import process_pending_outbox_events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Traiter manuellement les evenements en attente dans integration_outbox.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Nombre maximum d'evenements a traiter.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Afficher le resultat en JSON formate.",
    )
    return parser


def main():
    args = _build_parser().parse_args()
    db = SessionLocal()
    try:
        result = process_pending_outbox_events(db, limit=args.limit)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
        else:
            print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()