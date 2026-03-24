import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME = "Plateforme Nationale Gaz Butane"
    VERSION = "1.0.0"
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/gas_platform")
    
    # JWT
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 1440
    
    # CORS - Lire depuis variable d'environnement ou utiliser valeur par défaut
    _origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175,http://localhost:5176,http://localhost:5177")
    ALLOWED_ORIGINS = [origin.strip() for origin in _origins.split(",")]
    
    # Maps
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # Sage X3 integration
    SAGE_X3_BASE_URL = os.getenv("SAGE_X3_BASE_URL", "")
    SAGE_X3_API_KEY = os.getenv("SAGE_X3_API_KEY", "")
    SAGE_X3_PUSH_MODE = os.getenv("SAGE_X3_PUSH_MODE", "mock")
    SAGE_X3_TIMEOUT_SECONDS = int(os.getenv("SAGE_X3_TIMEOUT_SECONDS", "15"))
    INTEGRATION_OUTBOX_MAX_RETRIES = int(os.getenv("INTEGRATION_OUTBOX_MAX_RETRIES", "3"))
    SAGE_X3_AUTH_SCHEME = os.getenv("SAGE_X3_AUTH_SCHEME", "bearer")
    SAGE_X3_AUTH_HEADER = os.getenv("SAGE_X3_AUTH_HEADER", "Authorization")
    SAGE_X3_DELIVERY_ENDPOINT = os.getenv("SAGE_X3_DELIVERY_ENDPOINT", "/deliveries")
    SAGE_X3_STOCK_MOVEMENT_ENDPOINT = os.getenv("SAGE_X3_STOCK_MOVEMENT_ENDPOINT", "/stock-movements")
    SAGE_X3_HEALTH_ENDPOINT = os.getenv("SAGE_X3_HEALTH_ENDPOINT", "/health")

settings = Settings()