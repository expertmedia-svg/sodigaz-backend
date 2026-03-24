"""Seed database with custom test data"""
from app.database import SessionLocal
from app.models import User, Depot, Truck, Stock, RoleEnum, BottleTypeEnum
from app.auth import hash_password

def seed_all():
    db = SessionLocal()
    
    print("🌱 Seeding database with custom users...\n")
    
    try:
        # Clean up existing data
        print("Cleaning up old data...")
        
        # Delete trucks first (foreign key constraint)
        existing_trucks = db.query(Truck).all()
        for truck in existing_trucks:
            db.delete(truck)
        db.commit()
        
        existing_depots = db.query(Depot).all()
        for depot in existing_depots:
            db.delete(depot)
        db.commit()
        
        existing_users = db.query(User).all()
        for user in existing_users:
            db.delete(user)
        db.commit()
        print("✅ Old data deleted\n")
        
        # Create ADMIN
        print("Creating ADMIN...")
        admin = User(
            email="admin@sodigaz.bf",
            username="admin",
            hashed_password=hash_password("admin123"),
            full_name="Admin SODIGAZ",
            role=RoleEnum.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print("✅ Admin: admin / admin123\n")
        
        # Create DRIVER (Ravitailleur)
        print("Creating DRIVER...")
        driver = User(
            email="driver1@sodigaz.bf",
            username="driver1",
            hashed_password=hash_password("driver123"),
            full_name="Driver One",
            role=RoleEnum.RAVITAILLEUR,
            is_active=True
        )
        db.add(driver)
        db.commit()
        db.refresh(driver)
        print("✅ Driver: driver1 / driver123\n")
        
        # Create USERS (customers)
        print("Creating USERS...")
        for i in range(1, 4):
            user = User(
                email=f"user{i}@sodigaz.bf",
                username=f"user{i}",
                hashed_password=hash_password("user123"),
                full_name=f"User {i}",
                role=RoleEnum.USER,
                is_active=True
            )
            db.add(user)
        db.commit()
        print("✅ Users: user1, user2, user3 / user123\n")
        
        # Create DEPOT users (if needed for depot management)
        print("Creating DEPOT users...")
        depot_user1 = User(
            email="depot1@sodigaz.bf",
            username="depot1",
            hashed_password=hash_password("depot123"),
            full_name="Depot Manager Ouagadougou",
            role=RoleEnum.DEPOT,
            is_active=True
        )
        depot_user2 = User(
            email="depot2@sodigaz.bf",
            username="depot2",
            hashed_password=hash_password("depot123"),
            full_name="Depot Manager Bobo",
            role=RoleEnum.DEPOT,
            is_active=True
        )
        db.add_all([depot_user1, depot_user2])
        db.commit()
        db.refresh(depot_user1)
        db.refresh(depot_user2)
        print("✅ Depot managers: depot1, depot2 / depot123\n")
        
        # Create DEPOTS (physical locations)
        print("Creating DEPOTS...")
        depot1 = Depot(
            name="Dépôt Ouagadougou Centre",
            latitude=12.3714,
            longitude=-1.5197,
            address="Avenue Kwame Nkrumah, Secteur 4",
            phone="+226 25 30 65 45",
            city="Ouagadougou",
            manager_id=depot_user1.id,
            is_active=True
        )
        depot2 = Depot(
            name="Dépôt Bobo-Dioulasso",
            latitude=11.1770,
            longitude=-4.2970,
            address="Route de Banfora, Quartier Lafiabougou",
            phone="+226 20 97 02 34",
            city="Bobo-Dioulasso",
            manager_id=depot_user2.id,
            is_active=True
        )
        db.add_all([depot1, depot2])
        db.commit()
        db.refresh(depot1)
        db.refresh(depot2)
        print("✅ Depots created (Ouagadougou, Bobo-Dioulasso)\n")
        
        # Create STOCKS
        print("Creating STOCKS...")
        stock1 = Stock(depot_id=depot1.id, bottle_type=BottleTypeEnum.B6KG, quantity_plein=350, quantity_vide=50, is_low_stock=False)
        stock2 = Stock(depot_id=depot1.id, bottle_type=BottleTypeEnum.B12KG, quantity_plein=120, quantity_vide=20, is_low_stock=False)
        stock3 = Stock(depot_id=depot2.id, bottle_type=BottleTypeEnum.B6KG, quantity_plein=80, quantity_vide=10, is_low_stock=True)
        stock4 = Stock(depot_id=depot2.id, bottle_type=BottleTypeEnum.B12KG, quantity_plein=40, quantity_vide=5, is_low_stock=True)
        db.add_all([stock1, stock2, stock3, stock4])
        db.commit()
        print("✅ Stocks created\n")
        
        # Create TRUCKS
        print("Creating TRUCKS...")
        truck1 = Truck(
            license_plate="BF-1234-AB",
            driver_id=driver.id,
            capacity_6kg=500,
            capacity_12kg=200,
            current_load_6kg_plein=0,
            current_load_12kg_plein=0,
            current_load_6kg_vide=0,
            current_load_12kg_vide=0,
            is_active=True
        )
        db.add(truck1)
        db.commit()
        print("✅ Truck created (BF-1234-AB for driver1)\n")
        
        print("="*60)
        print("✅ SEED COMPLETE!")
        print("="*60)
        print("\n📋 CREDENTIALS:\n")
        print("ADMIN:")
        print("  └─ admin / admin123\n")
        print("DRIVER:")
        print("  └─ driver1 / driver123\n")
        print("USERS (Customers):")
        print("  └─ user1, user2, user3 / user123\n")
        print("DEPOT Managers:")
        print("  └─ depot1, depot2 / depot123\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_all()
