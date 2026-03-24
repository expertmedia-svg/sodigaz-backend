"""
Script de migration pour ajouter la table notification_subscriptions
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

DATABASE_URL = "sqlite:///./dev.db"
Base = declarative_base()

class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    
    id = Column(Integer, primary_key=True)
    phone = Column(String(20))
    latitude = Column(Float)
    longitude = Column(Float)
    radius_km = Column(Integer, default=5)
    bottle_type = Column(String(10))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    
    try:
        # Créer la table
        NotificationSubscription.__table__.create(bind=engine, checkfirst=True)
        print("✅ Table notification_subscriptions créée avec succès")
    except Exception as e:
        print(f"❌ Erreur lors de la migration: {e}")
