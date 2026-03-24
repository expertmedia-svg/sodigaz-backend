"""
Migration pour ajouter le champ phone à la table users
"""
from sqlalchemy import text
from app.database import engine

def migrate():
    """Ajouter le champ phone à la table users"""
    try:
        with engine.connect() as conn:
            # Vérifier si la colonne existe déjà
            result = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            columns = [row[1] for row in result]
            
            if 'phone' not in columns:
                print("🔄 Ajout du champ 'phone' à la table users...")
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
                conn.commit()
                print("✅ Champ 'phone' ajouté avec succès!")
            else:
                print("ℹ️  Le champ 'phone' existe déjà")
                
    except Exception as e:
        print(f"❌ Erreur lors de la migration: {e}")
        raise

if __name__ == "__main__":
    print("🚀 Démarrage de la migration...")
    migrate()
    print("✅ Migration terminée!")
