"""Pydantic models for the cruise booking eval domain."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# --- Enums ---

class CruiseStatus(str, Enum):
    scheduled = "scheduled"
    boarding = "boarding"
    sailing = "sailing"
    completed = "completed"
    cancelled = "cancelled"


class BookingStatus(str, Enum):
    held = "held"
    confirmed = "confirmed"
    paid = "paid"
    cancelled = "cancelled"
    embarked = "embarked"


class PaymentStatus(str, Enum):
    pending = "pending"
    authorized = "authorized"
    captured = "captured"
    refunded = "refunded"
    failed = "failed"


class CruiseRole(str, Enum):
    admin = "admin"
    agent = "agent"
    desk = "desk"
    viewer = "viewer"


# --- Templates (immutable, from JSON) ---

class CruiseUserTemplate(BaseModel):
    id: str
    name: str
    email: str
    role: CruiseRole


class CabinTypeTemplate(BaseModel):
    id: str
    cruise_id: str
    name: str
    capacity: int  # max passengers per booking for this cabin type
    total_count: int  # total cabins of this type available
    price_per_passenger: float


class CruiseTemplate(BaseModel):
    id: str
    name: str
    ship: str
    departure_date: str
    status: CruiseStatus = CruiseStatus.scheduled
    cabin_types: list[CabinTypeTemplate] = Field(default_factory=list)


# --- Mutable State Models (stored in SQLite) ---

class CruiseState(BaseModel):
    id: str = ""
    session_id: str = ""
    template_id: str = ""
    name: str = ""
    ship: str = ""
    departure_date: str = ""
    status: CruiseStatus = CruiseStatus.scheduled
    created_at: str = ""


class BookingState(BaseModel):
    id: str = ""
    session_id: str = ""
    cruise_id: str = ""
    cabin_type_id: str = ""
    cabin_number: str = ""
    status: BookingStatus = BookingStatus.held
    lead_passenger_id: str = ""
    passenger_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class PassengerState(BaseModel):
    id: str = ""
    session_id: str = ""
    booking_id: str = ""
    name: str = ""
    passport_number: str = ""
    emergency_contact: str = ""
    checked_in: bool = False
    created_at: str = ""


class PaymentState(BaseModel):
    id: str = ""
    session_id: str = ""
    booking_id: str = ""
    amount: float = 0.0
    status: PaymentStatus = PaymentStatus.pending
    method: str = ""
    created_at: str = ""


class CruiseSession(BaseModel):
    id: str = ""
    acting_user_id: str = ""
    created_at: str = ""


# Reuse Affordance, DomainEvent, DecisionRecord from eval.backend.models
# Import them from there to avoid duplication:
#   from eval.backend.models import Affordance, DomainEvent, DecisionRecord
