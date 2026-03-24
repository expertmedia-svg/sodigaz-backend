from app.database import SessionLocal
from app.models import Delivery, DeliveryStatusEnum, User, Depot, Truck
from datetime import datetime, timedelta

def create_test_delivery():
    db = SessionLocal()
    
    # Trouver le ravitailleur
    driver = db.query(User).filter(User.email == "driver1@sodigaz.com").first()
    if not driver:
        print("❌ Ravitailleur introuvable")
        return
    
    # Trouver le premier dépôt
    depot = db.query(Depot).first()
    if not depot:
        print("❌ Aucun dépôt trouvé")
        return
    
    # Trouver un camion
    truck = db.query(Truck).first()
    if not truck:
        print("❌ Aucun camion trouvé")
        return
    
    # Créer une livraison test
    delivery = Delivery(
        depot_id=depot.id,
        driver_id=driver.id,
        truck_id=truck.id,
        status=DeliveryStatusEnum.PENDING,
        scheduled_date=datetime.utcnow() + timedelta(hours=2),
        destination_name="Boutique Test",
        destination_address="123 Rue de Test",
        destination_latitude=depot.latitude + 0.001,
        destination_longitude=depot.longitude + 0.001,
        contact_name="Client Test",
        contact_phone="0612345678",
        quantity_6kg=10,
        quantity_12kg=8,
        quantity_6kg_vide_recupere=0,
        quantity_12kg_vide_recupere=0
    )
    
    db.add(delivery)
    db.commit()
    
    print(f"✅ Mission de livraison créée:")
    print(f"   ID: {delivery.id}")
    print(f"   Ravitailleur: {driver.full_name} ({driver.email})")
    print(f"   Dépôt: {depot.name}")
    print(f"   Coordonnées: {depot.latitude}, {depot.longitude}")
    print(f"   Camion: {truck.license_plate}")
    print(f"   Heure prévue: {delivery.scheduled_date}")
    print(f"   Destination: {delivery.destination_name}")
    print(f"   Quantités: {delivery.quantity_6kg}x 6kg, {delivery.quantity_12kg}x 12kg")
    print(f"   Status: {delivery.status.value}")
    
    db.close()

if __name__ == "__main__":
    create_test_delivery()
