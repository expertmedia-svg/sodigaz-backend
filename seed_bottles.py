"""
Données de test pour le système de bouteilles 6kg/12kg
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import engine
from app.models import User, Depot, Truck, Delivery, RoleEnum, DeliveryStatusEnum
from app.auth import hash_password
from datetime import datetime, timedelta

def seed():
    print("🌱 Seed des données - Système bouteilles...\n")
    
    db = Session(bind=engine)
    
    try:
        # 1. Admin
        print("1️⃣ Création de l'admin...")
        admin = User(
            email="admin@sodigaz.bf",
            username="admin",
            hashed_password=hash_password("password123"),
            full_name="Administrateur SODIGAZ",
            role=RoleEnum.ADMIN
        )
        db.add(admin)
        db.flush()
        
        # 2. Ravitailleurs
        print("2️⃣ Création des ravitailleurs...")
        ravitailleur1 = User(
            email="moussa@sodigaz.bf",
            username="ravitailleur1",
            hashed_password=hash_password("password123"),
            full_name="Ouedraogo Moussa",
            role=RoleEnum.RAVITAILLEUR
        )
        ravitailleur2 = User(
            email="kabore@sodigaz.bf",
            username="ravitailleur2",
            hashed_password=hash_password("password123"),
            full_name="Kaboré Ibrahim",
            role=RoleEnum.RAVITAILLEUR
        )
        db.add_all([ravitailleur1, ravitailleur2])
        db.flush()
        
        # 3. Dépôts avec stocks de bouteilles
        print("3️⃣ Création des dépôts...")
        depot1 = Depot(
            name="Dépôt Ouagadougou Centre",
            latitude=12.3714,
            longitude=-1.5197,
            address="Avenue Kwame Nkrumah, Secteur 4",
            city="Ouagadougou",
            phone="+226 25 30 00 00",
            # Capacités
            capacity_6kg=500,
            capacity_12kg=300,
            # Stocks pleins
            stock_6kg_plein=450,
            stock_12kg_plein=280,
            # Stocks vides
            stock_6kg_vide=30,
            stock_12kg_vide=15,
            manager_id=admin.id
        )
        
        depot2 = Depot(
            name="Dépôt Bobo-Dioulasso",
            latitude=11.1770,
            longitude=-4.2900,
            address="Route de Banfora, Secteur 25",
            city="Bobo-Dioulasso",
            phone="+226 20 97 00 00",
            # Capacités
            capacity_6kg=400,
            capacity_12kg=250,
            # Stocks pleins (stock bas pour créer des alertes)
            stock_6kg_plein=45,  # 11% seulement
            stock_12kg_plein=30,  # 12% seulement
            # Stocks vides
            stock_6kg_vide=80,  # Beaucoup de vides à échanger
            stock_12kg_vide=50,
            manager_id=admin.id
        )
        
        depot3 = Depot(
            name="Dépôt Koudougou",
            latitude=12.2543,
            longitude=-2.3623,
            address="Quartier Central",
            city="Koudougou",
            phone="+226 25 44 00 00",
            # Capacités
            capacity_6kg=300,
            capacity_12kg=200,
            # Stocks pleins
            stock_6kg_plein=280,
            stock_12kg_plein=190,
            # Stocks vides
            stock_6kg_vide=15,
            stock_12kg_vide=8,
            manager_id=admin.id
        )
        
        db.add_all([depot1, depot2, depot3])
        db.flush()
        
        # 4. Camions avec capacités de bouteilles
        print("4️⃣ Création des camions...")
        truck1 = Truck(
            license_plate="BF-1234-AB",
            driver_id=ravitailleur1.id,
            # Capacités
            capacity_6kg=120,
            capacity_12kg=80,
            # Charges actuelles
            current_load_6kg_plein=100,
            current_load_12kg_plein=60,
            current_load_6kg_vide=10,
            current_load_12kg_vide=5
        )
        
        truck2 = Truck(
            license_plate="BF-5678-CD",
            driver_id=ravitailleur2.id,
            # Capacités
            capacity_6kg=150,
            capacity_12kg=100,
            # Charges actuelles
            current_load_6kg_plein=130,
            current_load_12kg_plein=85,
            current_load_6kg_vide=15,
            current_load_12kg_vide=10
        )
        
        db.add_all([truck1, truck2])
        db.flush()
        
        # 5. Livraisons avec quantités de bouteilles
        print("5️⃣ Création des livraisons...")
        
        # Livraison complétée
        delivery1 = Delivery(
            truck_id=truck1.id,
            depot_id=depot1.id,
            driver_id=ravitailleur1.id,
            destination_name="Boutique Zongo Market",
            destination_address="Zone commerciale Zongo",
            destination_latitude=12.3650,
            destination_longitude=-1.5280,
            contact_name="Sawadogo Jean",
            contact_phone="+226 70 11 22 33",
            quantity_6kg=30,
            quantity_12kg=20,
            echange_effectue=True,
            quantity_6kg_vide_recupere=30,
            quantity_12kg_vide_recupere=20,
            status=DeliveryStatusEnum.COMPLETED,
            scheduled_date=datetime.now() - timedelta(days=1),
            actual_start=datetime.now() - timedelta(days=1, hours=2),
            actual_end=datetime.now() - timedelta(days=1, hours=1),
            notes="Échange complet effectué"
        )
        
        # Livraison en cours
        delivery2 = Delivery(
            truck_id=truck2.id,
            depot_id=depot1.id,
            driver_id=ravitailleur2.id,
            destination_name="SuperMart Gounghin",
            destination_address="Boulevard Charles de Gaulle",
            destination_latitude=12.3800,
            destination_longitude=-1.5100,
            contact_name="Ouédraogo Marie",
            contact_phone="+226 70 44 55 66",
            quantity_6kg=50,
            quantity_12kg=30,
            echange_effectue=False,  # Pas encore effectué
            status=DeliveryStatusEnum.IN_PROGRESS,
            scheduled_date=datetime.now(),
            actual_start=datetime.now() - timedelta(hours=1),
            notes="En route vers le client"
        )
        
        # Livraison programmée - 6kg seulement
        delivery3 = Delivery(
            truck_id=truck1.id,
            depot_id=depot2.id,
            driver_id=ravitailleur1.id,
            destination_name="Alimentation Dafra",
            destination_address="Quartier Dafra, Bobo-Dioulasso",
            destination_latitude=11.1850,
            destination_longitude=-4.2850,
            contact_name="Traoré Amadou",
            contact_phone="+226 70 77 88 99",
            quantity_6kg=60,  # Que des 6kg
            quantity_12kg=0,
            echange_effectue=False,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=datetime.now() + timedelta(hours=4),
            notes="Précommande bouteilles 6kg uniquement"
        )
        
        # Livraison programmée - 12kg seulement
        delivery4 = Delivery(
            truck_id=truck2.id,
            depot_id=depot3.id,
            driver_id=ravitailleur2.id,
            destination_name="Restaurant Le Palmier",
            destination_address="Centre-ville Koudougou",
            destination_latitude=12.2500,
            destination_longitude=-2.3700,
            contact_name="Compaoré Pascal",
            contact_phone="+226 70 99 00 11",
            quantity_6kg=0,  # Que des 12kg
            quantity_12kg=40,
            echange_effectue=False,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=datetime.now() + timedelta(days=1),
            notes="Client professionnel - bouteilles 12kg uniquement"
        )
        
        # Livraison mixte programmée
        delivery5 = Delivery(
            truck_id=truck1.id,
            depot_id=depot1.id,
            driver_id=ravitailleur1.id,
            destination_name="Marché Central Ouaga",
            destination_address="Avenue de la Nation",
            destination_latitude=12.3700,
            destination_longitude=-1.5250,
            contact_name="Sana Fatimata",
            contact_phone="+226 70 22 33 44",
            quantity_6kg=40,
            quantity_12kg=25,
            echange_effectue=False,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=datetime.now() + timedelta(days=2),
            notes="Livraison mixte pour point de vente central"
        )
        
        db.add_all([delivery1, delivery2, delivery3, delivery4, delivery5])
        
        db.commit()
        
        print("\n✅ Données créées avec succès!")
        print("\n📊 Résumé:")
        print(f"   - 1 Admin (admin/password123)")
        print(f"   - 2 Ravitailleurs (ravitailleur1/password123, ravitailleur2/password123)")
        print(f"   - 3 Dépôts avec stocks 6kg/12kg (plein + vide)")
        print(f"   - 2 Camions avec capacités et charges par type")
        print(f"   - 5 Livraisons (1 complétée, 1 en cours, 3 programmées)")
        print("\n🔵 Bouteilles 6kg | 🟢 Bouteilles 12kg")
        print("\n📍 Dépôts:")
        print(f"   • {depot1.name}: {depot1.stock_6kg_plein}🔵 {depot1.stock_12kg_plein}🟢 pleines | {depot1.stock_6kg_vide}🔵 {depot1.stock_12kg_vide}🟢 vides")
        print(f"   • {depot2.name}: {depot2.stock_6kg_plein}🔵 {depot2.stock_12kg_plein}🟢 pleines | {depot2.stock_6kg_vide}🔵 {depot2.stock_12kg_vide}🟢 vides ⚠️ STOCK BAS")
        print(f"   • {depot3.name}: {depot3.stock_6kg_plein}🔵 {depot3.stock_12kg_plein}🟢 pleines | {depot3.stock_6kg_vide}🔵 {depot3.stock_12kg_vide}🟢 vides")
        
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()
