from datetime import datetime, timedelta
from jose import jwt, JWTError
from app.config import settings

# Simulate token creation (like in auth.py)
user_id = 1
expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
to_encode = {"sub": user_id, "exp": expire}

print("Creating token...")
print(f"Data to encode: {to_encode}")
print(f"SECRET_KEY: {settings.SECRET_KEY}")
print(f"ALGORITHM: {settings.ALGORITHM}")

token = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
print(f"\nToken created: {token}")

# Simulate token validation (like in get_current_user)
print("\nValidating token...")
try:
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    print(f"Token decoded successfully!")
    print(f"Payload: {payload}")
    user_id_from_token = payload.get("sub")
    print(f"User ID from token: {user_id_from_token} (type: {type(user_id_from_token)})")
except JWTError as e:
    print(f"ERROR decoding token: {e}")
