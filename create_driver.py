from app.database import SessionLocal
from app.models import User, RoleEnum
from app.auth import hash_password

def create_driver():
    db = SessionLocal()
    
    # Créer un utilisateur ravitailleur
    driver = User(
        email="driver1@sodigaz.com",
        username="driver1",
        hashed_password=hash_password("driver123"),
        role=RoleEnum.RAVITAILLEUR,
        full_name="Mohammed Ali",
        is_active=True
    )
    
    db.add(driver)
    db.commit()
    
    print(f"✅ Ravitailleur créé: {driver.email} / driver123")
    print(f"   Nom: {driver.full_name}")
    print(f"   ID: {driver.id}")
    
    db.close()

if __name__ == "__main__":
    create_driver()
