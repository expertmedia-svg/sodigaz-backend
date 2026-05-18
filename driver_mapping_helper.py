"""
Helper script pour gérer les chauffeurs et les mappages Sage.
Utilisation:
  python driver_mapping_helper.py create-driver <SAGE_CODE> [full_name]
  python driver_mapping_helper.py list-drivers
  python driver_mapping_helper.py list-mappings
  python driver_mapping_helper.py sync-from-sage
  python driver_mapping_helper.py create-mapping <SAGE_CODE> <TRUCK_LICENSE_PLATE>
"""
import sys
import logging
from app.database import SessionLocal
from app.models import User, RoleEnum, DriverMapping, DriverMappingStatusEnum, Truck
from app.auth import hash_password
from app.services.sage_sql_service import get_sage_sql_connection
from sqlalchemy import func

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def generate_password_for_code(sage_code: str) -> str:
    """Génère un mot de passe sécurisé pour un code chauffeur."""
    return f"Code{sage_code.upper()}@2026"


def create_driver(sage_code: str, full_name: str = None) -> User:
    """Crée un chauffeur pour un code Sage."""
    db = SessionLocal()
    try:
        normalized = sage_code.lower().strip()
        email = f"{normalized}@sodigaz-app.local"
        username = normalized
        password = generate_password_for_code(sage_code)

        # Vérifier que le chauffeur n'existe pas
        existing = db.query(User).filter(
            func.upper(User.email) == email.upper()
        ).first()

        if existing:
            if existing.is_active and existing.role == RoleEnum.RAVITAILLEUR:
                logger.info(f"✓ Chauffeur {sage_code} existe déjà (ID: {existing.id})")
                return existing
            elif not existing.is_active:
                existing.is_active = True
                db.commit()
                logger.info(f"↻ Chauffeur {sage_code} réactivé (ID: {existing.id})")
                return existing

        # Créer le chauffeur
        driver = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            full_name=full_name or f"Chauffeur {sage_code}",
            phone=None,
            role=RoleEnum.RAVITAILLEUR,
            is_active=True,
        )
        db.add(driver)
        db.commit()
        logger.info(f"✅ Chauffeur créé: ID={driver.id}, email={email}, password={password}")
        return driver
    finally:
        db.close()


def list_drivers():
    """Liste tous les chauffeurs."""
    db = SessionLocal()
    try:
        drivers = db.query(User).filter(
            User.role == RoleEnum.RAVITAILLEUR,
            User.is_active == True,
        ).order_by(User.email).all()

        print("\n=== CHAUFFEURS ACTIFS ===")
        for driver in drivers:
            print(f"  {driver.id:4d}  {driver.email:30s}  {driver.full_name}")
        print(f"\nTotal: {len(drivers)} chauffeurs")
    finally:
        db.close()


def list_mappings():
    """Liste tous les mappages chauffeur/camion."""
    db = SessionLocal()
    try:
        mappings = db.query(DriverMapping).join(User).filter(
            User.is_active == True
        ).order_by(User.email, DriverMapping.truck_code).all()

        print("\n=== MAPPAGES CHAUFFEUR/CAMION ===")
        print(f"{'SAGE_CODE':<15} {'TRUCK':<15} {'USER':<30} {'STATUS':<20} {'AUTO':<5}")
        print("-" * 85)
        for m in mappings:
            user = db.query(User).filter(User.id == m.user_id).first()
            print(f"{m.sage_driver_code:<15} {m.truck_code:<15} {user.email:<30} {m.status.value:<20} {'✓' if m.auto_created else ' ':<5}")
        print(f"\nTotal: {len(mappings)} mappages")
    finally:
        db.close()


def sync_from_sage():
    """Lit les codes Sage et crée les chauffeurs/mappages."""
    db = SessionLocal()
    try:
        logger.info("=== Lecture depuis Sage SQL ===")
        conn = get_sage_sql_connection()
        cursor = conn.cursor()
        db_sage = "SAGEX3V12"
        schema = "SCHEM001"

        cursor.execute(f"""
            SELECT DISTINCT UPPER(YLIV_0), UPPER(YMATCAM_0)
            FROM {db_sage}.{schema}.YPRGCOLL
            WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
            AND YMATCAM_0 IS NOT NULL AND YMATCAM_0 != ''
            ORDER BY YLIV_0, YMATCAM_0
        """)

        programs = cursor.fetchall()
        conn.close()

        created_drivers = 0
        created_mappings = 0

        for sage_code, truck_code in programs:
            sage_code = sage_code.strip()
            truck_code = truck_code.strip()

            # Créer ou récupérer le chauffeur
            normalized = sage_code.lower()
            email = f"{normalized}@sodigaz-app.local"
            driver = db.query(User).filter(
                func.upper(User.email) == email.upper()
            ).first()

            if not driver:
                driver = User(
                    email=email,
                    username=normalized,
                    hashed_password=hash_password(generate_password_for_code(sage_code)),
                    full_name=f"Chauffeur {sage_code}",
                    role=RoleEnum.RAVITAILLEUR,
                    is_active=True,
                )
                db.add(driver)
                db.flush()
                created_drivers += 1
                logger.info(f"✅ Chauffeur créé: {sage_code}")

            # Créer ou récupérer le camion
            truck = db.query(Truck).filter(
                func.upper(Truck.license_plate) == truck_code.upper()
            ).first()

            if not truck:
                truck = Truck(license_plate=truck_code, is_active=True)
                db.add(truck)
                db.flush()

            # Créer le mapping
            existing_mapping = db.query(DriverMapping).filter(
                func.upper(DriverMapping.sage_driver_code) == sage_code.upper(),
                func.upper(DriverMapping.truck_code) == truck_code.upper(),
            ).first()

            if not existing_mapping:
                mapping = DriverMapping(
                    user_id=driver.id,
                    sage_driver_code=sage_code,
                    truck_code=truck_code,
                    is_active=True,
                    status=DriverMappingStatusEnum.ACTIVE,
                    auto_created=True,
                )
                db.add(mapping)
                created_mappings += 1

        db.commit()
        logger.info(f"\n=== RÉSUMÉ ===")
        logger.info(f"✅ {created_drivers} chauffeurs créés")
        logger.info(f"✅ {created_mappings} mappages créés")

    except Exception as e:
        db.rollback()
        logger.error(f"Erreur: {e}")
        raise
    finally:
        db.close()


def create_mapping(sage_code: str, truck_license: str):
    """Crée un mapping chauffeur/camion."""
    db = SessionLocal()
    try:
        # Chercher le chauffeur
        normalized = sage_code.lower()
        email = f"{normalized}@sodigaz-app.local"
        driver = db.query(User).filter(
            func.upper(User.email) == email.upper(),
            User.role == RoleEnum.RAVITAILLEUR,
            User.is_active == True,
        ).first()

        if not driver:
            logger.error(f"✗ Chauffeur {sage_code} non trouvé")
            return

        # Chercher ou créer le camion
        truck = db.query(Truck).filter(
            func.upper(Truck.license_plate) == truck_license.upper()
        ).first()

        if not truck:
            truck = Truck(license_plate=truck_license, is_active=True)
            db.add(truck)
            db.flush()
            logger.info(f"✅ Camion créé: {truck_license}")

        # Créer le mapping
        existing = db.query(DriverMapping).filter(
            func.upper(DriverMapping.sage_driver_code) == sage_code.upper(),
            func.upper(DriverMapping.truck_code) == truck_license.upper(),
        ).first()

        if existing:
            logger.info(f"✓ Mapping {sage_code}/{truck_license} existe déjà")
            return

        mapping = DriverMapping(
            user_id=driver.id,
            sage_driver_code=sage_code,
            truck_code=truck_license,
            is_active=True,
            status=DriverMappingStatusEnum.ACTIVE,
            auto_created=False,
        )
        db.add(mapping)
        db.commit()
        logger.info(f"✅ Mapping créé: {sage_code} ↔ {truck_license}")
    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "create-driver":
        if len(sys.argv) < 3:
            logger.error("Usage: python driver_mapping_helper.py create-driver <SAGE_CODE> [full_name]")
            return
        sage_code = sys.argv[2]
        full_name = sys.argv[3] if len(sys.argv) > 3 else None
        create_driver(sage_code, full_name)

    elif command == "list-drivers":
        list_drivers()

    elif command == "list-mappings":
        list_mappings()

    elif command == "sync-from-sage":
        sync_from_sage()

    elif command == "create-mapping":
        if len(sys.argv) < 4:
            logger.error("Usage: python driver_mapping_helper.py create-mapping <SAGE_CODE> <TRUCK_LICENSE>")
            return
        create_mapping(sys.argv[2], sys.argv[3])

    else:
        logger.error(f"Commande inconnue: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
