from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.database import SessionLocal
from app.models import Depot


EXPORT_FIELDS = [
    'name',
    'address',
    'city',
    'quartier',
    'latitude',
    'longitude',
    'phone',
    'plv_code',
    'maps_url',
    'capacity_6kg',
    'capacity_12kg',
]


def _sanitize_export_row(row: dict[str, object]) -> dict[str, object]:
    name = str(row.get('name') or '').strip()
    quartier = str(row.get('quartier') or '').strip()
    phone = str(row.get('phone') or '').strip()
    plv_code = str(row.get('plv_code') or '').strip()
    maps_url = str(row.get('maps_url') or '').strip()

    if phone.startswith('http') and not maps_url:
        maps_url = phone
        phone = ''

    if phone.startswith('http') and maps_url.isdigit() and not plv_code:
        plv_code = maps_url
        maps_url = phone
        phone = ''

    if name.lower().startswith('fournisseur de bouteilles de gaz') and quartier:
        lower_quartier = quartier.lower()
        if 'point de vente' in lower_quartier or 'sodigaz point de vente' in lower_quartier:
            name = quartier
            quartier = 'Fournisseur de bouteilles de gaz'

    row['name'] = name
    row['quartier'] = quartier
    row['phone'] = phone
    row['plv_code'] = plv_code
    row['maps_url'] = maps_url
    return row


def export_depots_csv(output_path: Path) -> int:
    db = SessionLocal()
    try:
        depots = db.query(Depot).filter(Depot.is_active == True).order_by(Depot.city.asc(), Depot.name.asc()).all()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
            writer.writeheader()
            for depot in depots:
                row = _sanitize_export_row({
                    'name': depot.name or '',
                    'address': depot.address or '',
                    'city': depot.city or '',
                    'quartier': depot.quartier or '',
                    'latitude': depot.latitude if depot.latitude is not None else '',
                    'longitude': depot.longitude if depot.longitude is not None else '',
                    'phone': depot.phone or '',
                    'plv_code': depot.plv_code or '',
                    'maps_url': depot.maps_url or '',
                    'capacity_6kg': depot.capacity_6kg or 0,
                    'capacity_12kg': depot.capacity_12kg or 0,
                })
                writer.writerow(row)
        return len(depots)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Exporter les dépôts actifs vers un CSV modèle compatible avec l\'import admin.')
    parser.add_argument(
        '--output',
        default=str(Path(__file__).resolve().parent / 'depot_import_model.csv'),
        help='Chemin du CSV exporté',
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    count = export_depots_csv(output_path)
    print(f'Export terminé: {count} dépôts écrits dans {output_path}')


if __name__ == '__main__':
    main()