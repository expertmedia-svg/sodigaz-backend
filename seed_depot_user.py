"""
Script pour créer un utilisateur gestionnaire de dépôt
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import User, Depot, RoleEnum
from app.auth import hash_password
from datetime import datetime

# Configuration de la base de données
DATABASE_URL = "sqlite:///./dev.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def create_depot_manager():
    db = SessionLocal()
    
    try:
        # Supprimer l'utilisateur existant s'il existe
        existing_user = db.query(User).filter(User.email == "depot1@sodigaz.com").first()
        if existing_user:
            print(f"⚠️  Suppression de l'utilisateur existant: {existing_user.email}")
            db.delete(existing_user)
            db.commit()
        
        # Récupérer le premier dépôt
        depot = db.query(Depot).first()
        if not depot:
            print("❌ Aucun dépôt trouvé dans la base de données")
            print("   Veuillez d'abord exécuter seed_bottles.py")
            return
        
        # Créer l'utilisateur gestionnaire
        depot_manager = User(
            email="depot1@sodigaz.com",
            username="depot1",
            hashed_password=hash_password("depot123"),  # Hash sécurisé
            full_name="Gestionnaire Dépôt 1",
            role=RoleEnum.DEPOT,
            is_active=True,
            created_at=datetime.now()
        )
        
        db.add(depot_manager)
        db.commit()
        db.refresh(depot_manager)
        
        # Associer le gestionnaire au dépôt
        depot.manager_id = depot_manager.id
        db.commit()
        
        print(f"✅ Gestionnaire de dépôt créé avec succès!")
        print(f"   Email: depot1@sodigaz.com")
        print(f"   Mot de passe: depot123")
        print(f"   Dépôt: {depot.name}")
        print(f"   ID Gestionnaire: {depot_manager.id}")
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("🔧 Création du gestionnaire de dépôt...")
    create_depot_manager()
    print("✅ Terminé!")
