from app.database import SessionLocal
from app.models import Delivery, Depot, User, DeliveryStatusEnum, RoleEnum

db = SessionLocal()

print('=== VÉRIFICATION DES LIVRAISONS ===\n')

# Trouver le dépôt
depot_user = db.query(User).filter(User.email == 'depot1@sodigaz.com').first()
if not depot_user:
    print('❌ Utilisateur dépôt non trouvé')
    db.close()
    exit()

depot = db.query(Depot).filter(Depot.manager_id == depot_user.id).first()
if not depot:
    print('❌ Dépôt non trouvé')
    db.close()
    exit()

print(f'✅ Dépôt trouvé: {depot.name} (ID: {depot.id})')
print(f'   Stock 6kg plein: {depot.stock_6kg_plein}')
print(f'   Stock 12kg plein: {depot.stock_12kg_plein}')
print()

# Voir les livraisons en attente
pending_deliveries = db.query(Delivery).filter(
    Delivery.depot_id == depot.id,
    Delivery.status.in_([DeliveryStatusEnum.PENDING, DeliveryStatusEnum.IN_PROGRESS])
).all()

print(f'📦 Livraisons en attente: {len(pending_deliveries)}')
if pending_deliveries:
    for d in pending_deliveries:
        print(f'\n  Livraison #{d.id}')
        print(f'  Status: {d.status}')
        print(f'  6kg: {d.quantity_6kg or 0}')
        print(f'  12kg: {d.quantity_12kg or 0}')
        print(f'  Créée: {d.created_at}')
else:
    print('  ⚠️  Aucune livraison en attente')
    print('  Voulez-vous en créer une pour tester ?')

# Voir toutes les livraisons
all_deliveries = db.query(Delivery).filter(Delivery.depot_id == depot.id).all()
print(f'\n📊 Total livraisons pour ce dépôt: {len(all_deliveries)}')

# Vérifier le statut DeliveryStatusEnum
print(f'\n🔍 Valeurs du DeliveryStatusEnum:')
for status in DeliveryStatusEnum:
    print(f'  - {status.name}: {status.value}')

db.close()
