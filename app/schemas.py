from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional
from app.models import RoleEnum, DeliveryStatusEnum, PreorderStatusEnum, BottleTypeEnum, SageMissionStatusEnum


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm(cls, obj):
        return cls.model_validate(obj)

# AUTH
class UserLogin(BaseModel):
    username: str
    password: str

class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: str
    role: RoleEnum = RoleEnum.USER

class UserResponse(OrmModel):
    id: int
    email: str
    username: Optional[str] = None
    full_name: str
    role: RoleEnum
    is_active: bool
    
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

# DEPOT
class DepotCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    capacity_6kg: Optional[int] = None
    capacity_12kg: Optional[int] = None
    capacity: Optional[float] = None
    address: str
    city: Optional[str] = None
    phone: str
    manager_id: Optional[int] = None

class DepotUpdate(BaseModel):
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    capacity_6kg: Optional[int] = None
    capacity_12kg: Optional[int] = None
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None

class DepotResponse(OrmModel):
    id: int
    name: str
    latitude: float
    longitude: float
    stock_6kg_plein: int
    stock_12kg_plein: int
    stock_6kg_vide: int
    stock_12kg_vide: int
    capacity_6kg: int
    capacity_12kg: int
    address: str
    city: Optional[str]
    phone: str
    is_active: bool
    
# TRUCK
class TruckCreate(BaseModel):
    license_plate: str
    driver_id: int
    capacity_6kg: int
    capacity_12kg: int

class TruckResponse(OrmModel):
    id: int
    license_plate: str
    driver_id: int
    capacity_6kg: int
    capacity_12kg: int
    current_load_6kg_plein: int
    current_load_12kg_plein: int
    current_load_6kg_vide: int
    current_load_12kg_vide: int
    is_active: bool
    
# DELIVERY
class DeliveryCreate(BaseModel):
    truck_id: int
    depot_id: int  # Dépôt de départ
    destination_name: str  # Nom de la boutique/client
    destination_address: str
    destination_latitude: float
    destination_longitude: float
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    quantity_6kg: int = 0
    quantity_12kg: int = 0
    scheduled_date: datetime
    notes: Optional[str] = None

class DeliveryUpdate(BaseModel):
    status: Optional[DeliveryStatusEnum] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    start_latitude: Optional[float] = None
    start_longitude: Optional[float] = None
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None

class DeliveryResponse(OrmModel):
    id: int
    truck_id: int
    depot_id: int
    destination_name: str
    destination_address: str
    destination_latitude: float
    destination_longitude: float
    contact_name: Optional[str]
    contact_phone: Optional[str]
    driver_id: Optional[int]
    quantity: float
    status: DeliveryStatusEnum
    scheduled_date: datetime
    actual_start: Optional[datetime]
    actual_end: Optional[datetime]
    start_latitude: Optional[float]
    start_longitude: Optional[float]
    end_latitude: Optional[float]
    end_longitude: Optional[float]
    notes: Optional[str]
    created_at: datetime
    
# GPS
class GPSLogCreate(BaseModel):
    truck_id: int
    delivery_id: Optional[int] = None
    latitude: float
    longitude: float
    accuracy: Optional[float] = None

class GPSLogResponse(OrmModel):
    id: int
    truck_id: int
    delivery_id: Optional[int]
    latitude: float
    longitude: float
    timestamp: datetime
    
# PREORDER
class PreorderCreate(BaseModel):
    depot_id: int
    quantity: float

class PreorderResponse(OrmModel):
    id: int
    user_id: int
    depot_id: int
    quantity: float
    status: PreorderStatusEnum
    created_at: datetime
    estimated_delivery: Optional[datetime]
    
# STOCK
class StockResponse(OrmModel):
    id: int
    depot_id: int
    quantity: float
    is_low_stock: bool
    is_out_of_stock: bool

# SAGE X3 MISSIONS
class SageMissionInbound(BaseModel):
    """Mission reçue de Sage X3 (cahier de charge)"""
    external_delivery_id: str  # Mission ID dans Sage
    destination_name: str
    destination_address: str
    destination_latitude: float
    destination_longitude: float
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    depot_id: int  # Dépôt de départ (résolu via ExternalMapping)
    quantity_6kg: int = 0
    quantity_12kg: int = 0
    scheduled_date: datetime
    notes: Optional[str] = None

class SageMissionResponse(OrmModel):
    """Réponse Sage mission avec statut d'approbation"""
    id: int
    external_delivery_id: str
    destination_name: str
    destination_address: str
    destination_latitude: float
    destination_longitude: float
    contact_name: Optional[str]
    contact_phone: Optional[str]
    depot_id: int
    quantity_6kg: int
    quantity_12kg: int
    scheduled_date: datetime
    external_status: SageMissionStatusEnum
    external_sync_at: Optional[datetime]
    external_error: Optional[str]
    notes: Optional[str]
    created_at: datetime

class SageMissionApprovalResponse(BaseModel):
    """Réponse approbation"""
    success: bool
    message: str
    mission_id: Optional[int]
    delivery_id: Optional[int]
    

