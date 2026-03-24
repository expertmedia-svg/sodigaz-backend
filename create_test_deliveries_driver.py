#!/usr/bin/env python3
"""
Create test deliveries for the driver
"""
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import User, Delivery, Depot, DeliveryStatusEnum, RoleEnum

db = SessionLocal()

# Get driver1
driver = db.query(User).filter(
    User.email == "driver1@sodigaz.bf",
    User.role == RoleEnum.RAVITAILLEUR
).first()

if not driver:
    print("❌ Driver not found!")
    exit(1)

# Get depots
depot1 = db.query(Depot).filter(Depot.name.contains("Ouagadougou")).first()
depot2 = db.query(Depot).filter(Depot.name.contains("Bobo")).first()

if not depot1 or not depot2:
    print("❌ Depots not found!")
    exit(1)

# Create test deliveries
print("Creating test deliveries...")
now = datetime.utcnow()

deliveries = [
    Delivery(
        driver_id=driver.id,
        depot_id=depot1.id,
        destination_name="Client ABC - Ouagadougou",
        contact_name="Monsieur Dupont",
        contact_phone="+226 70 12 34 56",
        latitude=12.3714,
        longitude=-1.5197,
        quantity_6kg=10,
        quantity_12kg=5,
        status=DeliveryStatusEnum.PENDING,
        scheduled_date=now + timedelta(days=1),
        source_type="user_created",
    ),
    Delivery(
        driver_id=driver.id,
        depot_id=depot1.id,
        destination_name="Restaurant XYZ - Ouagadougou",
        contact_name="Chef Omar",
        contact_phone="+226 75 98 76 54",
        latitude=12.3650,
        longitude=-1.5150,
        quantity_6kg=20,
        quantity_12kg=10,
        status=DeliveryStatusEnum.PENDING,
        scheduled_date=now + timedelta(days=1),
        source_type="user_created",
    ),
    Delivery(
        driver_id=driver.id,
        depot_id=depot2.id,
        destination_name="Boutique SODIGAZ - Bobo",
        contact_name="Manager Bobo",
        contact_phone="+226 20 12 34 56",
        latitude=11.1770,
        longitude=-4.2970,
        quantity_6kg=15,
        quantity_12kg=8,
        status=DeliveryStatusEnum.PENDING,
        scheduled_date=now + timedelta(days=2),
        source_type="user_created",
    ),
]

db.add_all(deliveries)
db.commit()

print(f"✅ {len(deliveries)} test deliveries created for driver1!")
print("\nDeliveries:")
for i, delivery in enumerate(deliveries, 1):
    print(f"  {i}. {delivery.destination_name} ({delivery.quantity_6kg}x 6kg, {delivery.quantity_12kg}x 12kg)")

db.close()
