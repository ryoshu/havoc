"""Seeder — populates CruiseContext from a task's setup dict."""

from __future__ import annotations

from eval.cruise_backend.context import CruiseContext
from eval.cruise_backend.models import (
    BookingState,
    BookingStatus,
    CruiseState,
    CruiseStatus,
    PassengerState,
    PaymentState,
    PaymentStatus,
)


def seed_cruise_task(ctx: CruiseContext, session_id: str, setup: dict) -> dict:
    """Seed cruise context from task setup. Returns alias→real ID map."""
    id_map: dict[str, str] = {}

    # Seed cruises
    for cr_def in setup.get("cruises", []):
        if "template_id" in cr_def:
            cruise = ctx.create_cruise_from_template(
                session_id,
                cr_def["template_id"],
                cruise_id=cr_def.get("id", ""),
            )
        else:
            cruise = CruiseState(
                session_id=session_id,
                name=cr_def["name"],
                ship=cr_def.get("ship", ""),
                departure_date=cr_def.get("departure_date", ""),
                status=CruiseStatus(cr_def.get("status", "scheduled")),
            )
            if cr_def.get("id"):
                cruise.id = cr_def["id"]
            cruise = ctx.db.create_cruise(cruise)
        id_map[cr_def.get("alias", cruise.id)] = cruise.id
        if cr_def.get("template_id"):
            id_map[cr_def["template_id"]] = cruise.id
        if cr_def.get("id"):
            id_map[cr_def["id"]] = cruise.id

    # Seed bookings
    for bk_def in setup.get("bookings", []):
        raw_cruise = bk_def.get("cruise_alias") or bk_def.get("cruise_id", "")
        cruise_id = id_map.get(raw_cruise, raw_cruise)
        raw_cabin = bk_def.get("cabin_type_alias") or bk_def.get("cabin_type_id", "")
        cabin_type_id = id_map.get(raw_cabin, raw_cabin)
        booking = BookingState(
            session_id=session_id,
            cruise_id=cruise_id,
            cabin_type_id=cabin_type_id,
            cabin_number=bk_def.get("cabin_number", ""),
            status=BookingStatus(bk_def.get("status", "held")),
            lead_passenger_id=bk_def.get("lead_passenger_id", ""),
            passenger_count=bk_def.get("passenger_count", 0),
        )
        if bk_def.get("id"):
            booking.id = bk_def["id"]
        booking = ctx.db.create_booking(booking)
        id_map[bk_def.get("alias", booking.id)] = booking.id
        if bk_def.get("id"):
            id_map[bk_def["id"]] = booking.id

    # Seed passengers
    for px_def in setup.get("passengers", []):
        raw_booking = px_def.get("booking_alias") or px_def.get("booking_id", "")
        booking_id = id_map.get(raw_booking, raw_booking)
        passenger = PassengerState(
            session_id=session_id,
            booking_id=booking_id,
            name=px_def.get("name", ""),
            passport_number=px_def.get("passport_number", ""),
            emergency_contact=px_def.get("emergency_contact", ""),
            checked_in=px_def.get("checked_in", False),
        )
        if px_def.get("id"):
            passenger.id = px_def["id"]
        passenger = ctx.db.create_passenger(passenger)
        id_map[px_def.get("alias", passenger.id)] = passenger.id
        if px_def.get("id"):
            id_map[px_def["id"]] = passenger.id

    # Seed payments
    for pay_def in setup.get("payments", []):
        raw_booking = pay_def.get("booking_alias") or pay_def.get("booking_id", "")
        booking_id = id_map.get(raw_booking, raw_booking)
        payment = PaymentState(
            session_id=session_id,
            booking_id=booking_id,
            amount=pay_def.get("amount", 0.0),
            status=PaymentStatus(pay_def.get("status", "pending")),
            method=pay_def.get("method", ""),
        )
        if pay_def.get("id"):
            payment.id = pay_def["id"]
        payment = ctx.db.create_payment(payment)
        id_map[pay_def.get("alias", payment.id)] = payment.id
        if pay_def.get("id"):
            id_map[pay_def["id"]] = payment.id

    return id_map
