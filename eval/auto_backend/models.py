"""Pydantic models for the automotive dealership eval domain."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# --- Enums ---

class VehicleStatus(str, Enum):
    available = "available"
    reserved = "reserved"
    sold = "sold"
    unavailable = "unavailable"


class DealStatus(str, Enum):
    negotiating = "negotiating"
    financing = "financing"
    approved = "approved"
    closed = "closed"
    lost = "lost"


class OfferStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    countered = "countered"
    expired = "expired"


class TestDriveStatus(str, Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class TradeInStatus(str, Enum):
    pending_appraisal = "pending_appraisal"
    appraised = "appraised"
    accepted = "accepted"
    declined = "declined"
    applied = "applied"


class CreditStatus(str, Enum):
    not_started = "not_started"
    submitted = "submitted"
    approved = "approved"
    denied = "denied"
    conditional = "conditional"


class AutoRole(str, Enum):
    manager = "manager"
    salesperson = "salesperson"
    finance = "finance"
    receptionist = "receptionist"


# --- Templates (immutable, from JSON) ---

class AutoUserTemplate(BaseModel):
    id: str
    name: str
    email: str
    role: AutoRole


class VehicleTemplate(BaseModel):
    id: str
    make: str
    model: str
    year: int
    trim: str
    vin: str
    color: str
    msrp: float
    invoice_price: float
    mileage: int
    condition: str
    features: list[str] = Field(default_factory=list)


# --- Mutable State Models (stored in SQLite) ---

class VehicleState(BaseModel):
    id: str = ""
    session_id: str = ""
    template_id: str = ""
    make: str = ""
    model: str = ""
    year: int = 0
    trim: str = ""
    vin: str = ""
    color: str = ""
    msrp: float = 0.0
    invoice_price: float = 0.0
    mileage: int = 0
    condition: str = ""
    status: VehicleStatus = VehicleStatus.available
    features: list[str] = Field(default_factory=list)
    created_at: str = ""


class CustomerState(BaseModel):
    id: str = ""
    session_id: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    drivers_license: str = ""
    credit_score: int = 0
    credit_status: CreditStatus = CreditStatus.not_started
    pre_approved_amount: float = 0.0
    created_at: str = ""


class TestDriveState(BaseModel):
    id: str = ""
    session_id: str = ""
    customer_id: str = ""
    vehicle_id: str = ""
    scheduled_time: str = ""
    duration_minutes: int = 30
    salesperson_id: str = ""
    status: TestDriveStatus = TestDriveStatus.scheduled
    notes: str = ""
    created_at: str = ""


class TradeInState(BaseModel):
    id: str = ""
    session_id: str = ""
    deal_id: str = ""
    customer_id: str = ""
    make: str = ""
    model: str = ""
    year: int = 0
    vin: str = ""
    mileage: int = 0
    condition: str = ""
    appraised_value: float = 0.0
    status: TradeInStatus = TradeInStatus.pending_appraisal
    created_at: str = ""


class OfferState(BaseModel):
    id: str = ""
    session_id: str = ""
    deal_id: str = ""
    amount: float = 0.0
    offered_by: str = ""
    status: OfferStatus = OfferStatus.pending
    trade_in_credit: float = 0.0
    notes: str = ""
    created_at: str = ""


class DealState(BaseModel):
    id: str = ""
    session_id: str = ""
    customer_id: str = ""
    vehicle_id: str = ""
    salesperson_id: str = ""
    status: DealStatus = DealStatus.negotiating
    final_price: float = 0.0
    financing_amount: float = 0.0
    down_payment: float = 0.0
    created_at: str = ""
    updated_at: str = ""


class AutoSession(BaseModel):
    id: str = ""
    acting_user_id: str = ""
    created_at: str = ""


# Reuse Affordance, DomainEvent, DecisionRecord from eval.backend.models
# Import them from there to avoid duplication:
#   from eval.backend.models import Affordance, DomainEvent, DecisionRecord
