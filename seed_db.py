"""
Script pour remplir la base de données avec des données de test
Exécuter: python backend/seed_db.py
"""

from app.database import SessionLocal
from app.models import User, Depot, Truck, Delivery, Stock, RoleEnum, DeliveryStatusEnum
from app.auth import hash_password
from datetime import datetime, timedelta
from decimal import Decimal

def seed_database():
    db = SessionLocal()
    
    # Nettoyer les données existantes
    db.query(Delivery).delete()
    db.query(Truck).delete()
    db.query(Depot).delete()
    db.query(User).delete()
    db.commit()
    
    # Créer l'admin
    admin = User(
        email="admin@sodigaz.com",
        username="admin",
        full_name="Admin SODIGAZ",
        hashed_password=hash_password("password123"),
        role=RoleEnum.ADMIN,
        is_active=True
    )
    db.add(admin)
    db.flush()
    
    # Créer des chauffeurs
    drivers = [
        User(
            email=f"driver{i}@sodigaz.com",
            username=f"driver{i}",
            full_name=f"Chauffeur {i}",
            hashed_password=hash_password("password123"),
            role=RoleEnum.RAVITAILLEUR,
            is_active=True
        )
        for i in range(1, 4)
    ]
    db.add_all(drivers)
    db.flush()
    
    # Créer des responsables de dépôts
    depot_managers = [
        User(
            email=f"depot{i}@sodigaz.com",
            username=f"depot{i}",
            full_name=f"Responsable Dépôt {i}",
            hashed_password=hash_password("password123"),
            role=RoleEnum.DEPOT,
            is_active=True
        )
        for i in range(1, 4)
    ]
    db.add_all(depot_managers)
    db.flush()
    
    # Créer des utilisateurs finaux
    final_users = [
        User(
            email=f"user{i}@test.com",
            username=f"user{i}",
            full_name=f"Utilisateur {i}",
            hashed_password=hash_password("password123"),
            role=RoleEnum.USER,
            is_active=True
        )
        for i in range(1, 6)
    ]
    db.add_all(final_users)
    db.commit()
    
    # Créer les dépôts
    depot_data = [
        {
            "name": "Dépôt Alger Centre",
            "latitude": 36.7372,
            "longitude": 3.0869,
            "capacity_6kg": 2500,
            "capacity_12kg": 2500,
            "address": "123 Rue Ahmed Bey, Alger",
            "city": "Alger",
            "phone": "+213 21 12 34 56",
            "manager_id": depot_managers[0].id
        },
        {
            "name": "Dépôt Oran",
            "latitude": 35.6931,
            "longitude": -0.6417,
            "capacity_6kg": 1500,
            "capacity_12kg": 1500,
            "address": "456 Boulevard de la République, Oran",
            "city": "Oran",
            "phone": "+213 41 12 34 56",
            "manager_id": depot_managers[1].id
        },
        {
            "name": "Dépôt Constantine",
            "latitude": 36.3650,
            "longitude": 6.6147,
            "capacity_6kg": 2000,
            "capacity_12kg": 2000,
            "address": "789 Rue Didouche Mourad, Constantine",
            "city": "Constantine",
            "phone": "+213 31 12 34 56",
            "manager_id": depot_managers[2].id
        }
    ]
    
    depots = [Depot(**data) for data in depot_data]
    db.add_all(depots)
    db.flush()
    
    from app.models import BottleTypeEnum
    # Créer les stocks (plein/vide pour chaque type de bouteille)
    for depot in depots:
        stock_6kg = Stock(
            depot_id=depot.id,
            bottle_type=BottleTypeEnum.B6KG,
            quantity_plein=1000,
            quantity_vide=200,
            is_low_stock=False,
            is_out_of_stock=False
        )
        stock_12kg = Stock(
            depot_id=depot.id,
            bottle_type=BottleTypeEnum.B12KG,
            quantity_plein=500,
            quantity_vide=100,
            is_low_stock=False,
            is_out_of_stock=False
        )
        db.add_all([stock_6kg, stock_12kg])
    db.flush()
    
    # Créer les camions
    truck_data = [
        {"license_plate": "AA-123-AA", "driver_id": drivers[0].id, "capacity_6kg": 1000, "capacity_12kg": 1000},
        {"license_plate": "AA-456-BB", "driver_id": drivers[1].id, "capacity_6kg": 1000, "capacity_12kg": 1000},
        {"license_plate": "AA-789-CC", "driver_id": drivers[2].id, "capacity_6kg": 800, "capacity_12kg": 700},
    ]
    
    trucks = [Truck(**data) for data in truck_data]
    db.add_all(trucks)
    db.flush()
    
    # Créer des livraisons
    now = datetime.utcnow()
    deliveries = [
        Delivery(
            truck_id=trucks[0].id,
            depot_id=depots[0].id,
            driver_id=drivers[0].id,
            quantity_6kg=500,
            quantity_12kg=0,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=now + timedelta(hours=2)
        ),
        Delivery(
            truck_id=trucks[1].id,
            depot_id=depots[1].id,
            driver_id=drivers[1].id,
            quantity_6kg=0,
            quantity_12kg=800,
            status=DeliveryStatusEnum.PENDING,
            scheduled_date=now + timedelta(hours=4)
        ),
        Delivery(
            truck_id=trucks[2].id,
            depot_id=depots[2].id,
            driver_id=drivers[2].id,
            quantity_6kg=600,
            quantity_12kg=0,
            status=DeliveryStatusEnum.IN_PROGRESS,
            scheduled_date=now + timedelta(hours=1),
            actual_start=now
        ),
    ]
    db.add_all(deliveries)
    db.commit()
    
    print("✅ Base de données initialisée avec succès!")
    print(f"👤 Admin créé: admin/password123")
    print(f"🚗 Chauffeurs créés: driver1-3/password123")
    print(f"📦 Dépôts créés: depot1-3/password123")
    print(f"👥 Utilisateurs créés: user1-5/password123")

if __name__ == "__main__":
    seed_database()
