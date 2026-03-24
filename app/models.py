from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, Numeric, Enum, JSON
from sqlalchemy.orm import relationship
import enum
from app.database import Base
from app.time_utils import utc_now

class RoleEnum(str, enum.Enum):
    ADMIN = "admin"
    RAVITAILLEUR = "ravitailleur"
    DEPOT = "depot"
    USER = "user"

class BottleTypeEnum(str, enum.Enum):
    B6KG = "6kg"
    B12KG = "12kg"

class DeliveryStatusEnum(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PreorderStatusEnum(str, enum.Enum):
    ATTENTE = "attente"
    CONFIRMEE = "confirmee"
    LIVREE = "livree"
    ANNULEE = "annulee"

class SageMissionStatusEnum(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"  # Mission reçue de Sage, en attente d'approbation
    APPROVED = "approved"  # Approuvée par admin, création Delivery en cours
    REJECTED = "rejected"  # Rejetée par admin
    SYNCED = "synced"  # Confirmée à Sage X3
    FAILED = "failed"  # Erreur de sync

class MovementTypeEnum(str, enum.Enum):
    RECEPTION = "reception"
    DELIVERY_IN = "delivery_in"
    DELIVERY_OUT = "delivery_out"
    PREORDER = "preorder"
    ADJUSTMENT = "adjustment"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True)
    username = Column(String(255), unique=True, index=True)
    hashed_password = Column(String(255))
    full_name = Column(String(255))
    phone = Column(String(50), nullable=True)
    role = Column(Enum(RoleEnum), default=RoleEnum.USER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    depots = relationship("Depot", back_populates="manager")
    trucks = relationship("Truck", back_populates="driver")
    deliveries = relationship("Delivery", back_populates="driver")
    preorders = relationship("Preorder", back_populates="user", foreign_keys="[Preorder.user_id]")

class Depot(Base):
    __tablename__ = "depots"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    manager_id = Column(Integer, ForeignKey("users.id"))
    latitude = Column(Float)
    longitude = Column(Float)
    
    # Stock bouteilles pleines
    stock_6kg_plein = Column(Integer, default=0)
    stock_12kg_plein = Column(Integer, default=0)
    
    # Stock bouteilles vides
    stock_6kg_vide = Column(Integer, default=0)
    stock_12kg_vide = Column(Integer, default=0)
    
    # Capacités maximales
    capacity_6kg = Column(Integer, default=0)
    capacity_12kg = Column(Integer, default=0)
    
    address = Column(String(500))
    city = Column(String(255))
    phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    manager = relationship("User", back_populates="depots")
    deliveries = relationship("Delivery", back_populates="depot")
    stocks = relationship("Stock", back_populates="depot")
    preorders = relationship("Preorder", back_populates="depot")

class Truck(Base):
    __tablename__ = "trucks"
    
    id = Column(Integer, primary_key=True)
    license_plate = Column(String(50), unique=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"))
    
    # Capacités en nombre de bouteilles
    capacity_6kg = Column(Integer, default=0)
    capacity_12kg = Column(Integer, default=0)
    
    # Charge actuelle en nombre de bouteilles pleines
    current_load_6kg_plein = Column(Integer, default=0)
    current_load_12kg_plein = Column(Integer, default=0)
    
    # Bouteilles vides récupérées
    current_load_6kg_vide = Column(Integer, default=0)
    current_load_12kg_vide = Column(Integer, default=0)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    
    driver = relationship("User", back_populates="trucks")
    deliveries = relationship("Delivery", back_populates="truck")
    gps_logs = relationship("GPSLog", back_populates="truck")

class Delivery(Base):
    __tablename__ = "deliveries"
    
    id = Column(Integer, primary_key=True)
    truck_id = Column(Integer, ForeignKey("trucks.id"))
    depot_id = Column(Integer, ForeignKey("depots.id"))  # Dépôt de départ
    destination_name = Column(String(255))  # Nom boutique/client
    destination_address = Column(Text)
    destination_latitude = Column(Float)
    destination_longitude = Column(Float)
    contact_name = Column(String(255))
    contact_phone = Column(String(50))
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Auto-rempli du truck.driver_id
    
    # Quantités par type de bouteille
    quantity_6kg = Column(Integer, default=0)
    quantity_12kg = Column(Integer, default=0)
    quantity = Column(Integer, default=0)
    
    # Échange effectué (vide récupéré)
    echange_effectue = Column(Boolean, default=False)
    quantity_6kg_vide_recupere = Column(Integer, default=0)
    quantity_12kg_vide_recupere = Column(Integer, default=0)
    
    status = Column(Enum(DeliveryStatusEnum), default=DeliveryStatusEnum.PENDING)
    
    # Tracking Sage X3 integration
    source_type = Column(String(50), default="user_created")  # user_created or sage_inbound
    external_delivery_id = Column(String(100), nullable=True, index=True)  # Sage X3 mission ID
    external_status = Column(Enum(SageMissionStatusEnum), nullable=True)  # pending_approval, approved, rejected, synced
    external_sync_at = Column(DateTime, nullable=True)  # Last sync timestamp with Sage
    external_error = Column(Text, nullable=True)  # Error message from Sage sync
    
    scheduled_date = Column(DateTime)
    actual_start = Column(DateTime)
    actual_end = Column(DateTime)
    start_latitude = Column(Float)
    start_longitude = Column(Float)
    end_latitude = Column(Float)
    end_longitude = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    
    truck = relationship("Truck", back_populates="deliveries")
    depot = relationship("Depot", back_populates="deliveries")  # Renommé de destination_depot
    driver = relationship("User", back_populates="deliveries")
    gps_logs = relationship("GPSLog", back_populates="delivery")

class Stock(Base):
    __tablename__ = "stocks"
    
    id = Column(Integer, primary_key=True)
    depot_id = Column(Integer, ForeignKey("depots.id"))
    
    # Stock par type de bouteille
    bottle_type = Column(Enum(BottleTypeEnum))
    quantity_plein = Column(Integer, default=0)
    quantity_vide = Column(Integer, default=0)
    
    last_updated = Column(DateTime, default=utc_now)
    is_low_stock = Column(Boolean, default=False)
    is_out_of_stock = Column(Boolean, default=False)
    
    depot = relationship("Depot", back_populates="stocks")

class Preorder(Base):
    __tablename__ = "preorders"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    depot_id = Column(Integer, ForeignKey("depots.id"))
    
    # Précommande par type de bouteille
    bottle_type = Column(Enum(BottleTypeEnum))
    quantity = Column(Integer)
    
    status = Column(Enum(PreorderStatusEnum), default=PreorderStatusEnum.ATTENTE)
    created_at = Column(DateTime, default=utc_now)
    estimated_delivery = Column(DateTime)
    
    # Confirmation fields
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    user = relationship("User", back_populates="preorders", foreign_keys="[Preorder.user_id]")
    depot = relationship("Depot", back_populates="preorders")
    confirmed_by = relationship("User", foreign_keys="[Preorder.confirmed_by_id]")

class GPSLog(Base):
    __tablename__ = "gps_logs"
    
    id = Column(Integer, primary_key=True)
    truck_id = Column(Integer, ForeignKey("trucks.id"))
    delivery_id = Column(Integer, ForeignKey("deliveries.id"))
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float)
    timestamp = Column(DateTime, default=utc_now, index=True)
    
    truck = relationship("Truck", back_populates="gps_logs")
    delivery = relationship("Delivery", back_populates="gps_logs")

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(255))
    message = Column(Text)
    type = Column(String(50))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    
    id = Column(Integer, primary_key=True)
    phone = Column(String(20))  # Téléphone pour identification sans auth
    latitude = Column(Float)  # Position utilisateur
    longitude = Column(Float)
    radius_km = Column(Integer, default=5)  # Rayon en km
    bottle_type = Column(String(10))  # "6kg", "12kg", ou "both"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)

class StockMovement(Base):
    __tablename__ = "stock_movements"
    
    id = Column(Integer, primary_key=True)
    depot_id = Column(Integer, ForeignKey("depots.id"), nullable=False)
    type = Column(Enum(MovementTypeEnum), nullable=False)
    quantity_6kg_plein = Column(Integer, default=0)
    quantity_6kg_vide = Column(Integer, default=0)
    quantity_12kg_plein = Column(Integer, default=0)
    quantity_12kg_vide = Column(Integer, default=0)
    description = Column(Text)
    created_by_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utc_now, index=True)
    
    depot = relationship("Depot")
    created_by = relationship("User")

class SyncBatch(Base):
    __tablename__ = "sync_batches"

    id = Column(Integer, primary_key=True)
    batch_id = Column(String(100), unique=True, index=True, nullable=False)
    device_id = Column(String(100), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sent_at = Column(DateTime, nullable=False)
    received_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    total_operations = Column(Integer, default=0)
    processed_operations = Column(Integer, default=0)
    accepted_operations = Column(Integer, default=0)
    conflict_operations = Column(Integer, default=0)
    rejected_operations = Column(Integer, default=0)
    status = Column(String(30), default="received", nullable=False)
    response_payload = Column(JSON, nullable=True)

    driver = relationship("User")

class SyncIdempotencyKey(Base):
    __tablename__ = "sync_idempotency_keys"

    id = Column(Integer, primary_key=True)
    idempotency_key = Column(String(150), unique=True, index=True, nullable=False)
    operation_type = Column(String(50), nullable=False)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False)
    response_payload = Column(JSON, nullable=True)
    first_seen_at = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at = Column(DateTime, default=utc_now, nullable=False)

    delivery = relationship("Delivery")
    driver = relationship("User")

class DeliveryConfirmationEvent(Base):
    __tablename__ = "delivery_confirmation_events"

    id = Column(Integer, primary_key=True)
    confirmation_id = Column(String(100), unique=True, index=True, nullable=False)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(100), nullable=False, index=True)
    source = Column(String(30), default="offline_sync", nullable=False)
    idempotency_key = Column(String(150), unique=True, index=True, nullable=False)
    product_type = Column(String(50), nullable=False)
    quantity_delivered = Column(Integer, nullable=False, default=0)
    quantity_empty_collected = Column(Integer, nullable=False, default=0)
    confirmation_mode = Column(String(30), nullable=False)
    customer_reference = Column(String(100), nullable=True)
    confirmed_by = Column(String(255), nullable=True)
    customer_phone = Column(String(50), nullable=True)
    signature = Column(Text, nullable=True)
    confirmation_code = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    gps_latitude = Column(Float, nullable=True)
    gps_longitude = Column(Float, nullable=True)
    gps_accuracy = Column(Float, nullable=True)
    delivered_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    delivery = relationship("Delivery")
    driver = relationship("User")

class SyncConflict(Base):
    __tablename__ = "sync_conflicts"

    id = Column(Integer, primary_key=True)
    aggregate_type = Column(String(50), nullable=False)
    aggregate_id = Column(String(100), nullable=False, index=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=True, index=True)
    batch_id = Column(String(100), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    device_id = Column(String(100), nullable=True)
    idempotency_key = Column(String(150), nullable=True, index=True)
    conflict_type = Column(String(50), nullable=False)
    local_payload = Column(JSON, nullable=False)
    server_state = Column(JSON, nullable=True)
    resolution_status = Column(String(30), default="open", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    delivery = relationship("Delivery", foreign_keys=[delivery_id])
    driver = relationship("User", foreign_keys=[driver_id])
    resolver = relationship("User", foreign_keys=[resolved_by])

class ExternalMapping(Base):
    __tablename__ = "external_mappings"

    id = Column(Integer, primary_key=True)
    system_name = Column(String(50), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    internal_id = Column(String(100), nullable=False, index=True)
    external_code = Column(String(100), nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class IntegrationOutbox(Base):
    __tablename__ = "integration_outbox"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False, index=True)
    direction = Column(String(20), nullable=False, default="outbound")
    system_name = Column(String(50), nullable=False, default="sage_x3", index=True)
    aggregate_type = Column(String(50), nullable=False, index=True)
    aggregate_id = Column(String(100), nullable=False, index=True)
    external_message_id = Column(String(100), unique=True, index=True, nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    payload_json = Column(JSON, nullable=False)
    response_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    last_attempt_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)


class IntegrationHealthCheck(Base):
    __tablename__ = "integration_health_checks"

    id = Column(Integer, primary_key=True)
    system_name = Column(String(50), nullable=False, default="sage_x3", index=True)
    mode = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, index=True)
    detail = Column(Text, nullable=True)
    base_url = Column(String(255), nullable=True)
    health_url = Column(String(255), nullable=True)
    status_code = Column(Integer, nullable=True)
    response_json = Column(JSON, nullable=True)
    checked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    checker = relationship("User", foreign_keys=[checked_by])
