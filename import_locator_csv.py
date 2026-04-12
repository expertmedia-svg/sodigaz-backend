from __future__ import annotations

import argparse
import re
from pathlib import Path

from openlocationcode import openlocationcode as olc

from app.database import SessionLocal
from app.models import Depot


HEADER_LINES = 25
FIELD_COUNT = 13
CSV_FIELDS = [
    'row_id',
    'title',
    'total_score',
    'reviews_count',
    'street',
    'city',
    'state',
    'country_code',
    'website',
    'phone',
    'categories',
    'url',
    'category_name',
]

CITY_REFERENCES: dict[str, tuple[float, float]] = {
    'ouagadougou': (12.3714, -1.5197),
    'tanghin-dassouri': (12.2722, -1.6684),
    'bobo-dioulasso': (11.1771, -4.2979),
    'koudougou': (12.2526, -2.3627),
}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('\ufeff')
    if not cleaned or cleaned in {'undefined', 'null', '#'}:
        return None
    return cleaned


def _load_records(csv_path: Path) -> list[dict[str, str | None]]:
    raw_lines = csv_path.read_text(encoding='utf-8', errors='replace').splitlines()
    payload = [line.strip().strip('\ufeff') for line in raw_lines if line.strip()]
    rows = payload[HEADER_LINES:]

    records: list[dict[str, str | None]] = []
    for index in range(0, len(rows), FIELD_COUNT):
        chunk = rows[index:index + FIELD_COUNT]
        if not chunk:
            continue
        if len(chunk) < FIELD_COUNT:
            chunk = chunk + [None] * (FIELD_COUNT - len(chunk))
        record = dict(zip(CSV_FIELDS, chunk, strict=False))
        title = _clean(record.get('title'))
        if not title:
            continue
        records.append(record)
    return records


def _city_reference(city: str | None) -> tuple[float, float]:
    normalized = (city or 'ouagadougou').strip().lower()
    return CITY_REFERENCES.get(normalized, CITY_REFERENCES['ouagadougou'])


def _decode_plus_code(street: str | None, city: str | None) -> tuple[float, float] | None:
    value = _clean(street)
    if not value or '+' not in value:
        return None

    plus_code = value.split(',')[0].strip()
    if len(plus_code) < 6:
        return None

    ref_lat, ref_lng = _city_reference(city)
    try:
        full_code = plus_code
        if not olc.isFull(plus_code):
            full_code = olc.recoverNearest(plus_code, ref_lat, ref_lng)
        area = olc.decode(full_code)
        return (area.latitudeCenter, area.longitudeCenter)
    except Exception:
        return None


def _extract_plv_code(title: str | None) -> str | None:
    if not title:
      return None
    match = re.search(r'\bPLV\s*([0-9A-Za-z-]+)\b', title, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def _build_address(record: dict[str, str | None]) -> str:
    street = _clean(record.get('street'))
    city = _clean(record.get('city'))
    parts = [part for part in [street, city, 'Burkina Faso'] if part]
    return ', '.join(parts)


def _build_unique_name(base_name: str, city: str | None, row_id: str | None, existing_names: set[str]) -> str:
    candidate = base_name.strip()
    if candidate.lower() not in existing_names:
        existing_names.add(candidate.lower())
        return candidate

    suffixes = [
        city,
        _extract_plv_code(base_name),
        row_id,
    ]
    for suffix in suffixes:
        if not suffix:
            continue
        next_candidate = f'{base_name} - {suffix}'
        if next_candidate.lower() not in existing_names:
            existing_names.add(next_candidate.lower())
            return next_candidate

    counter = 2
    while True:
        next_candidate = f'{base_name} - {counter}'
        if next_candidate.lower() not in existing_names:
            existing_names.add(next_candidate.lower())
            return next_candidate
        counter += 1


def import_locator_csv(csv_path: Path) -> tuple[int, int, int]:
    records = _load_records(csv_path)
    db = SessionLocal()
    created = 0
    updated = 0
    skipped = 0

    try:
        existing_names = {depot.name.lower() for depot in db.query(Depot).all()}

        for record in records:
            title = _clean(record.get('title'))
            city = _clean(record.get('city')) or 'Ouagadougou'
            maps_url = _clean(record.get('url'))
            phone = _clean(record.get('phone')) or ''
            website = _clean(record.get('website'))
            category_name = _clean(record.get('category_name'))
            street = _clean(record.get('street'))
            row_id = _clean(record.get('row_id'))
            coordinates = _decode_plus_code(street, city)

            if not title or coordinates is None:
                skipped += 1
                continue

            latitude, longitude = coordinates
            plv_code = _extract_plv_code(title)
            address = _build_address(record)
            depot = None

            if maps_url:
                depot = db.query(Depot).filter(Depot.maps_url == maps_url).first()
            if depot is None and plv_code:
                depot = db.query(Depot).filter(Depot.plv_code == plv_code).first()
            if depot is None:
                depot = db.query(Depot).filter(Depot.name == title).first()

            if depot is None:
                name = _build_unique_name(title, city, row_id, existing_names)
                depot = Depot(
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    address=address,
                    city=city,
                    quartier=category_name,
                    plv_code=plv_code,
                    maps_url=maps_url or website,
                    phone=phone,
                    capacity_6kg=0,
                    capacity_12kg=0,
                    stock_6kg_plein=0,
                    stock_12kg_plein=0,
                    stock_6kg_vide=0,
                    stock_12kg_vide=0,
                    is_active=True,
                )
                db.add(depot)
                created += 1
            else:
                if depot.name.lower() in existing_names:
                    existing_names.discard(depot.name.lower())
                depot.name = _build_unique_name(title, city, row_id, existing_names)
                depot.latitude = latitude
                depot.longitude = longitude
                depot.address = address
                depot.city = city
                depot.quartier = category_name or depot.quartier
                depot.plv_code = plv_code or depot.plv_code
                depot.maps_url = maps_url or website or depot.maps_url
                depot.phone = phone or depot.phone or ''
                depot.is_active = True
                updated += 1

        db.commit()
        return created, updated, skipped
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Importer les points SODIGAZ du locator CSV dans les dépôts.')
    parser.add_argument(
        '--csv',
        default=str(Path(__file__).resolve().parent.parent / 'mobile_apps' / 'sodigaz_locator' / 'location.csv'),
        help='Chemin vers le fichier location.csv',
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f'Fichier introuvable: {csv_path}')

    created, updated, skipped = import_locator_csv(csv_path)
    print(f'Import terminé: {created} créés, {updated} mis à jour, {skipped} ignorés')


if __name__ == '__main__':
    main()