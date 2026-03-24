from app.database import SessionLocal
from app.models import User, RoleEnum
from app.auth import hash_password

def seed_test_users():
    db = SessionLocal()
    for i in range(1, 6):
        email = f"user{i}@test.com"
        if not db.query(User).filter_by(email=email).first():
            user = User(
                email=email,
                username=f"user{i}",
                full_name=f"Utilisateur {i}",
                hashed_password=hash_password("password123"),
                role=RoleEnum.USER,
                is_active=True
            )
            db.add(user)
    db.commit()
    db.close()
    print("✅ Comptes test frontend-user créés (user1-5@test.com / password123)")

if __name__ == "__main__":
    seed_test_users()
