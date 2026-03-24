"""Migration script to update database schema for deliveries"""
import os
from sqlalchemy import create_engine, inspect, text
from app.database import Base
from app.models import User, Depot, Truck, Delivery, Stock, Preorder, GPSLog, Notification
from app.auth import hash_password

# Get database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
engine = create_engine(DATABASE_URL)

def migrate():
    inspector = inspect(engine)
    
    # Check if tables exist and drop them
    tables_to_drop = ['deliveries', 'depots', 'trucks', 'stocks', 'preorders', 'gps_logs', 'notifications']
    for table in tables_to_drop:
        if table in inspector.get_table_names():
            print(f"Deleting old {table} table...")
            with engine.connect() as conn:
                conn.execute(text(f"DROP TABLE {table}"))
                conn.commit()
    
    # Recreate all tables
    print("Creating new schema...")
    Base.metadata.create_all(bind=engine)
    
    print("Migration completed successfully!")
    print("\nNew schemas created:")
    print("- depot_id (departure depot)")
    print("- destination_name (shop/client name)")
    print("- destination_address")
    print("- destination_latitude")
    print("- destination_longitude")
    print("- contact_name")
    print("- contact_phone")
    print("- driver_id (auto-filled from truck.driver_id)")

if __name__ == "__main__":
    migrate()
