from app.database import SessionLocal
from app.models import User, Depot, RoleEnum
from app.auth import verify_password

db = SessionLocal()
user = db.query(User).filter(User.email == 'depot1@sodigaz.com').first()

if not user:
    print('❌ Aucun utilisateur trouvé avec cet email')
else:
    print('=== USER INFO ===')
    print(f'Email: {user.email}')
    print(f'Role: {user.role}')
    print(f'Role value: {user.role.value}')
    print(f'Is DEPOT role: {user.role == RoleEnum.DEPOT}')
    print(f'Active: {user.is_active}')
    
    print(f'\n=== DEPOT INFO ===')
    depot = db.query(Depot).filter(Depot.manager_id == user.id).first()
    print(f'Depot exists: {depot is not None}')
    if depot:
        print(f'Depot name: {depot.name}')
        print(f'Depot ID: {depot.id}')
    
    print(f'\n=== PASSWORD TEST ===')
    print(f'depot123 works: {verify_password("depot123", user.hashed_password)}')
    print(f'password123 works: {verify_password("password123", user.hashed_password)}')

db.close()
