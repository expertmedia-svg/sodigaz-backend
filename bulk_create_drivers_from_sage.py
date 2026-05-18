"""
Crée automatiquement des comptes chauffeur (RAVITAILLEUR) pour chaque code Sage (YLIV) unique.
Utilisation: python bulk_create_drivers_from_sage.py
"""
import logging
from app.database import SessionLocal
from app.models import User, RoleEnum, DriverMapping
from app.auth import hash_password
from app.services.sage_sql_service import get_sage_sql_connection
from sqlalchemy import func

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def read_unique_sage_driver_codes() -> list[str]:
    """Lit tous les codes YLIV uniques depuis Sage SQL YPRGCOLL."""
    try:
        conn = get_sage_sql_connection()
        cursor = conn.cursor()
        db = "SAGEX3V12"
        schema = "SCHEM001"

        cursor.execute(f"""
            SELECT DISTINCT UPPER(YLIV_0)
            FROM {db}.{schema}.YPRGCOLL
            WHERE YLIV_0 IS NOT NULL AND YLIV_0 != ''
            ORDER BY YLIV_0
        """)

        codes = [row[0].strip() for row in cursor.fetchall()]
        conn.close()
        return codes
    except Exception as e:
        logger.error(f"Erreur lors de la lecture des codes Sage: {e}")
        raise


def generate_credentials_for_code(sage_code: str) -> tuple[str, str, str]:
    """Génère email, username et password pour un code Sage."""
    # Normaliser le code (ex: "DRV001" → "drv001")
    normalized = sage_code.lower()

    # Email: drv001@sodigaz-app.local
    email = f"{normalized}@sodigaz-app.local"

    # Username: drv001
    username = normalized

    # Password: CodeDRV001@2026 (format: Code<SAGE_CODE>@<YEAR>)
    password = f"Code{sage_code.upper()}@2026"

    return email, username, password


def ensure_driver_exists(db, sage_code: str) -> tuple[User, str]:
    """
    Vérifie si un chauffeur existe pour ce code Sage.
    Si non, le crée.
    Retourne (user, status_message).
    """
    email, username, password = generate_credentials_for_code(sage_code)

    # Chercher par email ou username
    existing = db.query(User).filter(
        func.upper(User.email) == email.upper()
    ).first()

    if existing:
        if existing.role == RoleEnum.RAVITAILLEUR and existing.is_active:
            return existing, f"✓ Chauffeur {sage_code} existe déjà (ID: {existing.id})"
        elif not existing.is_active:
            existing.is_active = True
            db.flush()
            return existing, f"↻ Chauffeur {sage_code} réactivé (ID: {existing.id})"

    # Créer le chauffeur
    driver = User(
        email=email,
        username=username,
        hashed_password=hash_password(password),
        full_name=f"Chauffeur {sage_code}",
        phone=None,
        role=RoleEnum.RAVITAILLEUR,
        is_active=True,
    )
    db.add(driver)
    db.flush()

    logger.info(f"✅ Chauffeur créé: {email} / {password}")
    return driver, f"✅ Chauffeur {sage_code} créé (ID: {driver.id}, email: {email}, password: {password})"


def bulk_create_drivers():
    """Lit les codes Sage et crée les chauffeurs."""
    db = SessionLocal()
    try:
        logger.info("=== Lecture des codes YLIV uniques depuis Sage ===")
        sage_codes = read_unique_sage_driver_codes()
        logger.info(f"Trouvé {len(sage_codes)} codes chauffeurs uniques")

        if not sage_codes:
            logger.warning("Aucun code chauffeur trouvé dans Sage SQL")
            return

        logger.info("\n=== Création/vérification des chauffeurs ===")
        created_count = 0
        existing_count = 0

        for sage_code in sage_codes:
            user, status = ensure_driver_exists(db, sage_code)
            logger.info(status)

            if "créé" in status.lower() or "✅" in status:
                created_count += 1
            else:
                existing_count += 1

        db.commit()

        logger.info(f"\n=== RÉSUMÉ ===")
        logger.info(f"✅ {created_count} chauffeurs créés/réactivés")
        logger.info(f"✓ {existing_count} chauffeurs existaient déjà")
        logger.info(f"📊 Total: {len(sage_codes)} chauffeurs")

    except Exception as e:
        db.rollback()
        logger.error(f"Erreur: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    bulk_create_drivers()
