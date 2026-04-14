from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models import RoleEnum, DeliveryStatusEnum, PreorderStatusEnum, BottleTypeEnum, SageMissionStatusEnum, ProgramTypeEnum


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
    quartier: Optional[str] = None
    plv_code: Optional[str] = None
    maps_url: Optional[str] = None
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
    quartier: Optional[str] = None
    plv_code: Optional[str] = None
    maps_url: Optional[str] = None
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
    quartier: Optional[str]
    plv_code: Optional[str]
    maps_url: Optional[str]
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


class DriverMappingCreate(BaseModel):
    user_id: int
    sage_driver_code: str
    truck_code: str
    is_active: bool = True
    status: Optional[str] = None


class DriverMappingResponse(OrmModel):
    id: int
    user_id: int
    sage_driver_code: str
    truck_code: str
    is_active: bool
    status: str
    auto_created: bool
    source_program_code: Optional[str]
    created_at: datetime
    updated_at: datetime
    
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
    external_delivery_id: Optional[str]
    destination_name: Optional[str]
    destination_address: Optional[str]
    destination_latitude: Optional[float]
    destination_longitude: Optional[float]
    contact_name: Optional[str]
    contact_phone: Optional[str]
    depot_id: Optional[int]
    quantity_6kg: int
    quantity_12kg: int
    scheduled_date: Optional[datetime]
    external_status: Optional[SageMissionStatusEnum]
    external_sync_at: Optional[datetime]
    external_error: Optional[str]
    notes: Optional[str]
    created_at: datetime
    program_type: Optional[str] = None
    source_type: Optional[str] = None

class SageMissionApprovalResponse(BaseModel):
    """Réponse approbation"""
    success: bool
    message: str
    mission_id: Optional[int]
    delivery_id: Optional[int]


class PricingRuleCreate(BaseModel):
    product_code: str
    product_label: Optional[str] = None
    depot_id: Optional[int] = None
    unit_price: Decimal
    tax_rate: Decimal = Decimal("0")
    active: bool = True


class PricingRuleResponse(OrmModel):
    id: int
    product_code: str
    product_label: Optional[str]
    depot_id: Optional[int]
    unit_price: Decimal
    tax_rate: Decimal
    active: bool
    created_at: datetime
    updated_at: datetime


class ProgramLineInbound(BaseModel):
    line_code: Optional[str] = None
    external_line_id: Optional[str] = None
    client_id: Optional[str] = None
    client_code: Optional[str] = None
    client_name: str
    destination_address: Optional[str] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    product_code: str
    product_label: Optional[str] = None
    article: Optional[str] = None
    zone: Optional[str] = None
    quantity_planned: int = Field(default=0, ge=0)
    quantity_delivered: Optional[int] = Field(default=None, ge=0)
    quantity_collected: Optional[int] = Field(default=None, ge=0)
    unit_price: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    delivery_mode: Optional[str] = None
    collection_sheet: Optional[str] = None
    comment: Optional[str] = None


class SageProgramInbound(BaseModel):
    program_code: str
    program_type: ProgramTypeEnum = ProgramTypeEnum.DELIVERY
    site: Optional[str] = None
    date: date
    time: Optional[str] = None
    depot_id: int
    truck_id: Optional[int] = None
    driver_id: Optional[int] = None
    sage_driver_code: Optional[str] = None
    truck_code: Optional[str] = None
    transporter: Optional[str] = None
    status: str = "active"
    source_updated_at: Optional[datetime] = None
    sync_version: int = Field(default=1, ge=1)
    lines: list[ProgramLineInbound] = Field(default_factory=list)

    @field_validator("program_type", mode="before")
    @classmethod
    def normalize_program_type(cls, value):
        if isinstance(value, ProgramTypeEnum):
            return value
        normalized = str(value or ProgramTypeEnum.DELIVERY.value).strip().upper()
        if normalized in {"COLLECTION", "PCOL"}:
            return ProgramTypeEnum.COLLECTION
        if normalized in {"DELIVERY", "PRES"}:
            return ProgramTypeEnum.DELIVERY
        return value


class ProgramAmountResponse(BaseModel):
    quantity_delivered: int
    unit_price: Decimal
    tax_rate: Decimal
    subtotal_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class ProgramLineResponse(OrmModel):
    id: int
    line_code: str
    external_line_id: Optional[str]
    client_id: Optional[str]
    client_code: Optional[str]
    client_name: str
    destination_address: Optional[str]
    destination_latitude: Optional[float]
    destination_longitude: Optional[float]
    contact_name: Optional[str]
    contact_phone: Optional[str]
    product_code: str
    product_label: Optional[str]
    article: Optional[str]
    zone: Optional[str]
    quantity_planned: int
    quantity_delivered: int
    quantity_collected: int
    unit_price: Optional[Decimal]
    tax_rate: Optional[Decimal]
    subtotal_amount: Optional[Decimal]
    tax_amount: Optional[Decimal]
    total_amount: Optional[Decimal]
    delivery_mode: Optional[str]
    collection_sheet: Optional[str]
    comment: Optional[str]
    status: str
    delivery_id: Optional[int] = None


class ProgramResponse(OrmModel):
    id: int
    program_code: str
    program_type: ProgramTypeEnum
    site_code: Optional[str]
    program_date: datetime
    program_time: Optional[str]
    depot_id: int
    truck_id: Optional[int]
    driver_id: Optional[int]
    transporter_name: Optional[str]
    source_system: str
    source_updated_at: Optional[datetime]
    status: str
    sync_version: int
    created_at: datetime
    updated_at: datetime
    lines: list[ProgramLineResponse] = Field(default_factory=list)


class DriverProgramLineResponse(BaseModel):
    line_id: int
    line_code: str
    client_id: Optional[str] = None
    client_name: str
    destination_address: Optional[str] = None
    product_code: str
    product_label: Optional[str] = None
    article: Optional[str] = None
    zone: Optional[str] = None
    quantity_planned: int
    quantity_delivered: int
    quantity_collected: int = 0
    delivery_mode: Optional[str] = None
    collection_sheet: Optional[str] = None
    comment: Optional[str] = None
    status: str
    unit_price: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None
    delivery_id: Optional[int] = None


class DriverProgramResponse(BaseModel):
    program_code: str
    program_type: ProgramTypeEnum
    site_code: Optional[str] = None
    program_date: datetime
    program_time: Optional[str] = None
    depot_id: int
    depot_name: Optional[str] = None
    truck_id: Optional[int] = None
    truck_license_plate: Optional[str] = None
    transporter_name: Optional[str] = None
    status: str
    lines: list[DriverProgramLineResponse] = Field(default_factory=list)
    

