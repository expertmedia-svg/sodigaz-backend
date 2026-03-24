"""
Script pour créer la table stock_movements
"""
from sqlalchemy import create_engine
from app.database import Base
from app.models import StockMovement, MovementTypeEnum

# Configuration de la base de données
DATABASE_URL = "sqlite:///./dev.db"
engine = create_engine(DATABASE_URL)

def create_stock_movements_table():
    print("🔧 Création de la table stock_movements...")
    try:
        # Créer uniquement la nouvelle table
        Base.metadata.create_all(bind=engine, tables=[StockMovement.__table__])
        print("✅ Table stock_movements créée avec succès!")
    except Exception as e:
        print(f"❌ Erreur: {e}")

if __name__ == "__main__":
    create_stock_movements_table()
    print("✅ Terminé!")
