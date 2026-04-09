import csv
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = CURRENT_DIR
PROJECT_ROOT = CURRENT_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models import DriverMapping, RoleEnum, Truck, User


OUTPUT_FILE = PROJECT_ROOT / 'DRIVER_MAPPING_REFERENCE.csv'


def main() -> None:
    db = SessionLocal()
    try:
        drivers = db.query(User).filter(User.role == RoleEnum.RAVITAILLEUR).all()
        driver_by_id = {driver.id: driver for driver in drivers}
        mappings = db.query(DriverMapping).all()
        mapping_by_pair = {
            (mapping.user_id, mapping.truck_code.strip().upper()): mapping
            for mapping in mappings
        }
        trucks = db.query(Truck).filter(Truck.driver_id.isnot(None)).all()

        with OUTPUT_FILE.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    'user_id',
                    'username',
                    'full_name',
                    'email',
                    'truck_id',
                    'truck_license_plate',
                    'sage_driver_code',
                    'truck_code',
                    'is_active',
                    'notes',
                ],
            )
            writer.writeheader()

            for truck in sorted(trucks, key=lambda item: (item.driver_id, item.license_plate or '')):
                driver = driver_by_id.get(truck.driver_id)
                if driver is None:
                    continue
                truck_code = (truck.license_plate or '').strip().upper()
                mapping = mapping_by_pair.get((driver.id, truck_code))
                writer.writerow(
                    {
                        'user_id': driver.id,
                        'username': driver.username,
                        'full_name': driver.full_name,
                        'email': driver.email,
                        'truck_id': truck.id,
                        'truck_license_plate': truck.license_plate,
                        'sage_driver_code': mapping.sage_driver_code if mapping else '',
                        'truck_code': truck_code,
                        'is_active': mapping.is_active if mapping else False,
                        'notes': 'Genere automatiquement depuis la base locale',
                    }
                )

        print(f'export_ok {OUTPUT_FILE}')
    finally:
        db.close()


if __name__ == '__main__':
    main()