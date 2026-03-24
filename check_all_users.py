from app.database import SessionLocal
from app.models import User, RoleEnum
from app.auth import verify_password

db = SessionLocal()

print('=== VÉRIFICATION DE TOUS LES UTILISATEURS ===\n')

# Admin
print('1️⃣  ADMIN:')
admin = db.query(User).filter(User.role == RoleEnum.ADMIN).first()
if admin:
    print(f'   Email: {admin.email}')
    print(f'   admin123: {verify_password("admin123", admin.hashed_password)}')
    print(f'   password123: {verify_password("password123", admin.hashed_password)}')
else:
    print('   ❌ Aucun admin trouvé')

print()

# Depot
print('2️⃣  DEPOT:')
depot = db.query(User).filter(User.role == RoleEnum.DEPOT).first()
if depot:
    print(f'   Email: {depot.email}')
    print(f'   depot123: {verify_password("depot123", depot.hashed_password)}')
    print(f'   password123: {verify_password("password123", depot.hashed_password)}')
else:
    print('   ❌ Aucun gestionnaire dépôt trouvé')

print()

# Ravitailleur
print('3️⃣  RAVITAILLEUR:')
ravitailleurs = db.query(User).filter(User.role == RoleEnum.RAVITAILLEUR).all()
if ravitailleurs:
    for rav in ravitailleurs:
        print(f'   Email: {rav.email}')
        print(f'   Nom: {rav.full_name}')
        print(f'   password123: {verify_password("password123", rav.hashed_password)}')
        print()
else:
    print('   ❌ Aucun ravitailleur trouvé')

# Users
print('4️⃣  CLIENTS:')
users = db.query(User).filter(User.role == RoleEnum.USER).all()
if users:
    for user in users[:3]:  # Les 3 premiers
        print(f'   Email: {user.email}')
        print(f'   Nom: {user.full_name}')
        print(f'   password123: {verify_password("password123", user.hashed_password)}')
        print()
else:
    print('   ❌ Aucun client trouvé')

db.close()
