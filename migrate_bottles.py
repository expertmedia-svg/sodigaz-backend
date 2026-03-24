"""
Migration vers le système de bouteilles 6kg/12kg
Supprime l'ancien schéma basé sur les litres
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, Base
from app.models import User, Depot, Truck, Delivery, Stock, Preorder, GPSLog, Notification

def migrate():
    print("🔄 Migration vers système de bouteilles...")
    print("⚠️  ATTENTION: Cette opération supprime toutes les données existantes!")
    
    # Drop all tables
    print("Suppression des anciennes tables...")
    Base.metadata.drop_all(bind=engine)
    print("✅ Tables supprimées")
    
    # Create new schema
    print("Création du nouveau schéma...")
    Base.metadata.create_all(bind=engine)
    print("✅ Nouveau schéma créé")
    
    print("\n✨ Migration terminée!")
    print("Nouvelle structure:")
    print("  - Dépôts: stock_6kg_plein, stock_12kg_plein, stock_6kg_vide, stock_12kg_vide")
    print("  - Camions: capacity_6kg, capacity_12kg, current_load par type")
    print("  - Livraisons: quantity_6kg, quantity_12kg, échange_effectue")
    print("\n👉 Exécutez maintenant: python seed_bottles.py")

if __name__ == "__main__":
    migrate()
