"""Seed database with test data"""
import os
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models import User, Depot, Truck, Delivery, Stock, RoleEnum, DeliveryStatusEnum
from app.auth import hash_password
from datetime import datetime, timedelta

def seed():
    db = SessionLocal()
    # Supprimer les camions existants si présents
    from app.models import Truck
    existing_trucks = db.query(Truck).all()
    for truck in existing_trucks:
        print(f"Suppression du camion existant: {truck.license_plate}")
        db.delete(truck)
        db.commit()
    # Supprimer les dépôts existants si présents
    for depot_name in ["Dépôt Ouagadougou Centre", "Dépôt Bobo-Dioulasso"]:
        existing_depot = db.query(Depot).filter(Depot.name == depot_name).first()
        if existing_depot:
            print(f"Suppression du dépôt existant: {depot_name}")
            db.delete(existing_depot)
            db.commit()

    try:
        # Supprimer l'admin existant si présent
        print("Vérification de l'admin existant (admin@sodigaz.bf)...")
        existing_admin = db.query(User).filter(User.email == "admin@sodigaz.bf").first()
        if existing_admin:
            print("Suppression de l'admin existant: admin@sodigaz.bf")
            db.delete(existing_admin)
            db.commit()

        # Créer admin@sodigaz.bf
        print("Création de l'utilisateur admin (admin@sodigaz.bf)...")
        admin_user = User(
            email="admin@sodigaz.bf",
            username="admin",
            hashed_password=hash_password("password123"),
            full_name="Admin Central SODIGAZ",
            role=RoleEnum.ADMIN,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        # Créer ravitailleurs
        print("Creating ravitailleurs...")
        ravitailleur1 = db.query(User).filter(User.username == "ravitailleur1").first()
        if not ravitailleur1:
            ravitailleur1 = User(
                email="ravitailleur1@example.com",
                username="ravitailleur1",
                hashed_password=hash_password("password123"),
                full_name="Ouedraogo Moussa",
                role=RoleEnum.RAVITAILLEUR,
                is_active=True
            )
            db.add(ravitailleur1)
            db.commit()
            db.refresh(ravitailleur1)

        ravitailleur2 = db.query(User).filter(User.username == "ravitailleur2").first()
        if not ravitailleur2:
            ravitailleur2 = User(
                email="ravitailleur2@example.com",
                username="ravitailleur2",
                hashed_password=hash_password("password123"),
                full_name="Kaboré Ibrahim",
                role=RoleEnum.RAVITAILLEUR,
                is_active=True
            )
            db.add(ravitailleur2)
            db.commit()
            db.refresh(ravitailleur2)

        # Créer dépôts
        print("Creating depots...")
        depot1 = Depot(
            name="Dépôt Ouagadougou Centre",
            latitude=12.3714,
            longitude=-1.5197,
            address="Avenue Kwame Nkrumah, Secteur 4",
            phone="+226 25 30 65 45",
            city="Ouagadougou",
            is_active=True
        )
        depot2 = Depot(
            name="Dépôt Bobo-Dioulasso",
            latitude=11.1770,
            longitude=-4.2970,
            address="Route de Banfora, Quartier Lafiabougou",
            phone="+226 20 97 02 34",
            city="Bobo-Dioulasso",
            is_active=True
        )
        db.add_all([depot1, depot2])
        db.commit()
        db.refresh(depot1)
        db.refresh(depot2)

        # Créer stocks (par type de bouteille)
        from app.models import BottleTypeEnum
        stock1 = Stock(depot_id=depot1.id, bottle_type=BottleTypeEnum.B6KG, quantity_plein=350, quantity_vide=50, is_low_stock=False)
        stock2 = Stock(depot_id=depot1.id, bottle_type=BottleTypeEnum.B12KG, quantity_plein=120, quantity_vide=20, is_low_stock=False)
        stock3 = Stock(depot_id=depot2.id, bottle_type=BottleTypeEnum.B6KG, quantity_plein=80, quantity_vide=10, is_low_stock=True)
        stock4 = Stock(depot_id=depot2.id, bottle_type=BottleTypeEnum.B12KG, quantity_plein=40, quantity_vide=5, is_low_stock=True)
        db.add_all([stock1, stock2, stock3, stock4])
        db.commit()

        # Créer camions
        print("Creating trucks...")
        truck1 = Truck(
            license_plate="BF-1234-AB",
            driver_id=ravitailleur1.id,
            capacity_6kg=500,
            capacity_12kg=200,
            current_load_6kg_plein=0,
            current_load_12kg_plein=0,
            current_load_6kg_vide=0,
            current_load_12kg_vide=0,
            is_active=True
        )
        truck2 = Truck(
            license_plate="BF-5678-CD",
            driver_id=ravitailleur2.id,
            capacity_6kg=300,
            capacity_12kg=100,
            current_load_6kg_plein=0,
            current_load_12kg_plein=0,
            current_load_6kg_vide=0,
            current_load_12kg_vide=0,
            is_active=True
        )
        db.add_all([truck1, truck2])
        db.commit()
        db.refresh(truck1)
        db.refresh(truck2)

        # Créer livraisons
        print("Creating deliveries...")
        delivery1 = Delivery(
            truck_id=truck1.id,
            depot_id=depot1.id,
            destination_name="Boutique Wend Konta",
            destination_address="Secteur 15, Avenue Charles de Gaulle",
            destination_latitude=12.3850,
            destination_longitude=-1.5240,
            contact_name="Sawadogo Rasmané",
            contact_phone="+226 70 12 34 56",
            driver_id=ravitailleur1.id,
            quantity_6kg=500,
            quantity_12kg=0,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=datetime.now() + timedelta(hours=2),
            notes="Livraison urgente - paiement comptant"
        )

        delivery2 = Delivery(
            truck_id=truck1.id,
            depot_id=depot1.id,
            destination_name="Station Paspanga",
            destination_address="Route de Koudougou, Zone 3",
            destination_latitude=12.3420,
            destination_longitude=-1.5380,
            contact_name="Compaoré Fatimata",
            contact_phone="+226 76 54 32 10",
            driver_id=ravitailleur1.id,
            quantity_6kg=1200,
            quantity_12kg=0,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=datetime.now() + timedelta(hours=4),
            notes="Livraison hebdomadaire"
        )

        delivery3 = Delivery(
            truck_id=truck2.id,
            depot_id=depot2.id,
            destination_name="Boutique Yennega",
            destination_address="Quartier Accart-Ville, près du marché",
            destination_latitude=11.1850,
            destination_longitude=-4.2850,
            contact_name="Traoré Mamadou",
            contact_phone="+226 71 98 76 54",
            driver_id=ravitailleur2.id,
            quantity_6kg=800,
            quantity_12kg=0,
            status=DeliveryStatusEnum.IN_PROGRESS,
            scheduled_date=datetime.now() - timedelta(hours=1),
            actual_start=datetime.now() - timedelta(minutes=45),
            start_latitude=11.1770,
            start_longitude=-4.2970,
            notes="Client régulier"
        )

        delivery4 = Delivery(
            truck_id=truck2.id,
            depot_id=depot2.id,
            destination_name="Bar-Restaurant Le Palmier",
            destination_address="Route de Ouagadougou, Secteur 7",
            destination_latitude=11.1920,
            destination_longitude=-4.3100,
            contact_name="Ouattara Salif",
            contact_phone="+226 78 11 22 33",
            driver_id=ravitailleur2.id,
            quantity_6kg=350,
            quantity_12kg=0,
            status=DeliveryStatusEnum.COMPLETED,
            scheduled_date=datetime.now() - timedelta(days=1),
            actual_start=datetime.now() - timedelta(days=1, hours=2),
            actual_end=datetime.now() - timedelta(days=1, hours=1),
            start_latitude=11.1770,
            start_longitude=-4.2970,
            end_latitude=11.1920,
            end_longitude=-4.3100,
            notes="Livraison terminée avec succès"
        )

        db.add_all([delivery1, delivery2, delivery3, delivery4])
        db.commit()

        print("\n✅ Database seeded successfully!")
        print("\n📊 Summary:")
        print(f"- 2 Ravitailleurs created (ravitailleur1/password123, ravitailleur2/password123)")
        print(f"- 2 Depots created (Ouagadougou, Bobo-Dioulasso)")
        print(f"- 2 Trucks created (BF-1234-AB, BF-5678-CD)")
        print(f"- 4 Deliveries created (1 completed, 1 in progress, 2 pending)")
        print("\n🔐 Admin credentials: admin@sodigaz.bf/password123")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed()