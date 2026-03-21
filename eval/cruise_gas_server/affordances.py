"""Affordance layer — computes valid actions from user role and resource states for cruise domain."""

from __future__ import annotations

from eval.cruise_backend.context import CruiseContext
from eval.cruise_backend.models import (
    BookingStatus,
    CruiseRole,
    CruiseStatus,
    PaymentStatus,
)
from eval.backend.models import Affordance


def compute_cruise_affordances(
    ctx: CruiseContext,
    session_id: str,
) -> list[Affordance]:
    """Compute available actions based on acting user's role and resource states."""
    session = ctx.get_session(session_id)
    if not session:
        return []

    user = ctx.get_user(session.acting_user_id)
    if not user:
        return []

    affordances: list[Affordance] = []
    is_viewer = user.role == CruiseRole.viewer
    is_agent_plus = user.role in (CruiseRole.agent, CruiseRole.admin)
    is_desk_plus = user.role in (CruiseRole.desk, CruiseRole.agent, CruiseRole.admin)
    is_admin = user.role == CruiseRole.admin

    cruises = ctx.db.get_session_cruises(session_id)
    bookings = ctx.db.get_session_bookings(session_id)

    all_user_ids = [u.id for u in ctx.get_all_users()]

    # --- Read actions (always available) ---

    for cruise in cruises:
        affordances.append(Affordance(
            action="get_cruise",
            description=f"View cruise '{cruise.name}' details",
            schema={"cruise_id": {"type": "string", "const": cruise.id}},
        ))

    for booking in bookings:
        affordances.append(Affordance(
            action="get_booking",
            description=f"View booking '{booking.id}' ({booking.status.value})",
            schema={"booking_id": {"type": "string", "const": booking.id}},
        ))

    affordances.append(Affordance(
        action="search_bookings",
        description="Search bookings by status, cruise_id, or cabin_type_id",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in BookingStatus]},
                    "cruise_id": {"type": "string"},
                    "cabin_type_id": {"type": "string"},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_passengers",
        description="Search passengers by booking_id or passport_number",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "passport_number": {"type": "string"},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_payments",
        description="Search payments by booking_id or status",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "status": {"type": "string", "enum": [s.value for s in PaymentStatus]},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="get_user",
        description="View user details",
        schema={"user_id": {"type": "string", "enum": all_user_ids}},
    ))

    for cruise in cruises:
        affordances.append(Affordance(
            action="get_cabin_availability",
            description=f"View cabin availability for cruise '{cruise.name}'",
            schema={"cruise_id": {"type": "string", "const": cruise.id}},
        ))

    if is_viewer:
        return affordances

    # --- Write actions (agent+ unless noted) ---

    if is_agent_plus:
        # create_booking: for each non-cancelled/completed cruise, for each cabin type with availability
        for cruise in cruises:
            if cruise.status in (CruiseStatus.cancelled, CruiseStatus.completed):
                continue
            cabin_types = ctx.get_cabin_types_for_cruise(cruise.template_id)
            for ct in cabin_types:
                booked = ctx.db.get_cabin_type_booking_count(session_id, cruise.id, ct.id)
                if booked < ct.total_count:
                    affordances.append(Affordance(
                        action="create_booking",
                        description=f"Create booking on '{cruise.name}' — {ct.name} ({ct.total_count - booked} available)",
                        schema={
                            "cruise_id": {"type": "string", "const": cruise.id},
                            "cabin_type_id": {"type": "string", "const": ct.id},
                            "description": {"type": "string"},
                        },
                    ))

        # Per-booking write actions
        for booking in bookings:
            cruise = ctx.db.get_cruise(booking.cruise_id)
            passengers = ctx.db.get_booking_passengers(booking.id)
            payments = ctx.db.get_booking_payments(booking.id)

            # add_passenger
            if booking.status not in (BookingStatus.embarked, BookingStatus.cancelled):
                cabin_type = ctx.get_cabin_type(booking.cabin_type_id)
                capacity = cabin_type.capacity if cabin_type else 0
                if len(passengers) < capacity:
                    affordances.append(Affordance(
                        action="add_passenger",
                        description=f"Add passenger to booking '{booking.id}'",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                            "name": {"type": "string"},
                            "passport_number": {"type": "string"},
                            "emergency_contact": {"type": "string"},
                        },
                    ))

            # update_passenger
            if booking.status != BookingStatus.embarked:
                for pax in passengers:
                    affordances.append(Affordance(
                        action="update_passenger",
                        description=f"Update passenger '{pax.name}' on booking '{booking.id}'",
                        schema={
                            "passenger_id": {"type": "string", "const": pax.id},
                            "name": {"type": "string"},
                            "emergency_contact": {"type": "string"},
                        },
                    ))

            # remove_passenger
            if booking.status not in (BookingStatus.embarked, BookingStatus.cancelled):
                for pax in passengers:
                    affordances.append(Affordance(
                        action="remove_passenger",
                        description=f"Remove passenger '{pax.name}' from booking '{booking.id}'",
                        schema={
                            "passenger_id": {"type": "string", "const": pax.id},
                        },
                    ))

            # confirm_booking
            if booking.status == BookingStatus.held:
                if len(passengers) >= 1:
                    affordances.append(Affordance(
                        action="confirm_booking",
                        description=f"Confirm booking '{booking.id}'",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                    ))
                else:
                    affordances.append(Affordance(
                        action="confirm_booking",
                        description=f"Confirm booking '{booking.id}' (needs passengers first)",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                        constraints=["At least one passenger must be added before confirming."],
                    ))

            # create_payment
            if booking.status not in (BookingStatus.cancelled, BookingStatus.embarked):
                affordances.append(Affordance(
                    action="create_payment",
                    description=f"Create payment for booking '{booking.id}'",
                    schema={
                        "booking_id": {"type": "string", "const": booking.id},
                        "amount": {"type": "number"},
                        "method": {"type": "string"},
                    },
                ))

            # authorize_payment
            for pay in payments:
                if pay.status == PaymentStatus.pending:
                    affordances.append(Affordance(
                        action="authorize_payment",
                        description=f"Authorize payment '{pay.id}'",
                        schema={
                            "payment_id": {"type": "string", "const": pay.id},
                        },
                    ))

            # capture_payment
            for pay in payments:
                if pay.status == PaymentStatus.authorized:
                    affordances.append(Affordance(
                        action="capture_payment",
                        description=f"Capture payment '{pay.id}'",
                        schema={
                            "payment_id": {"type": "string", "const": pay.id},
                        },
                    ))

            # pay_booking
            if booking.status == BookingStatus.confirmed:
                has_captured = any(p.status == PaymentStatus.captured for p in payments)
                if has_captured:
                    affordances.append(Affordance(
                        action="pay_booking",
                        description=f"Mark booking '{booking.id}' as paid",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                    ))
                else:
                    affordances.append(Affordance(
                        action="pay_booking",
                        description=f"Mark booking '{booking.id}' as paid (needs captured payment)",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                        constraints=["A captured payment is required before marking as paid."],
                    ))

            # cancel_booking
            if booking.status in (BookingStatus.held, BookingStatus.confirmed):
                affordances.append(Affordance(
                    action="cancel_booking",
                    description=f"Cancel booking '{booking.id}'",
                    schema={
                        "booking_id": {"type": "string", "const": booking.id},
                    },
                ))
            elif booking.status == BookingStatus.paid:
                if cruise and cruise.status not in (
                    CruiseStatus.boarding, CruiseStatus.sailing, CruiseStatus.completed,
                ):
                    affordances.append(Affordance(
                        action="cancel_booking",
                        description=f"Cancel paid booking '{booking.id}'",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                    ))
                else:
                    cruise_name = cruise.name if cruise else "unknown"
                    affordances.append(Affordance(
                        action="cancel_booking",
                        description=f"Cancel paid booking '{booking.id}' (BLOCKED: cruise '{cruise_name}' is {cruise.status.value if cruise else 'unknown'})",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                        constraints=[f"Cannot cancel paid booking while cruise is '{cruise.status.value if cruise else 'unknown'}'."],
                    ))

            # refund_payment
            for pay in payments:
                if pay.status == PaymentStatus.captured:
                    affordances.append(Affordance(
                        action="refund_payment",
                        description=f"Refund payment '{pay.id}'",
                        schema={
                            "payment_id": {"type": "string", "const": pay.id},
                        },
                    ))

    # --- Desk+ actions (desk, agent, admin) ---

    if is_desk_plus:
        for booking in bookings:
            if booking.status == BookingStatus.paid:
                cruise = ctx.db.get_cruise(booking.cruise_id)
                if cruise and cruise.status == CruiseStatus.boarding:
                    affordances.append(Affordance(
                        action="embark_booking",
                        description=f"Embark booking '{booking.id}'",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                    ))
                elif cruise:
                    affordances.append(Affordance(
                        action="embark_booking",
                        description=f"Embark booking '{booking.id}' (BLOCKED: cruise not boarding)",
                        schema={
                            "booking_id": {"type": "string", "const": booking.id},
                        },
                        constraints=[f"Cruise '{cruise.name}' must be 'boarding' (is '{cruise.status.value}')."],
                    ))

    # --- Admin-only actions ---

    if is_admin:
        for cruise in cruises:
            if cruise.status == CruiseStatus.scheduled:
                # Check for held bookings
                cruise_bookings = ctx.db.get_cruise_bookings(cruise.id)
                held_count = sum(1 for b in cruise_bookings if b.status == BookingStatus.held)
                if held_count > 0:
                    affordances.append(Affordance(
                        action="board_cruise",
                        description=f"Begin boarding cruise '{cruise.name}' (BLOCKED: {held_count} held booking(s))",
                        schema={
                            "cruise_id": {"type": "string", "const": cruise.id},
                        },
                        constraints=[f"{held_count} booking(s) still in 'held' status must be confirmed or cancelled first."],
                    ))
                else:
                    affordances.append(Affordance(
                        action="board_cruise",
                        description=f"Begin boarding cruise '{cruise.name}'",
                        schema={
                            "cruise_id": {"type": "string", "const": cruise.id},
                        },
                    ))

            if cruise.status == CruiseStatus.boarding:
                affordances.append(Affordance(
                    action="sail_cruise",
                    description=f"Set sail on cruise '{cruise.name}'",
                    schema={
                        "cruise_id": {"type": "string", "const": cruise.id},
                    },
                ))

            if cruise.status == CruiseStatus.sailing:
                affordances.append(Affordance(
                    action="complete_cruise",
                    description=f"Complete cruise '{cruise.name}'",
                    schema={
                        "cruise_id": {"type": "string", "const": cruise.id},
                    },
                ))

            if cruise.status == CruiseStatus.scheduled:
                affordances.append(Affordance(
                    action="cancel_cruise",
                    description=f"Cancel cruise '{cruise.name}'",
                    schema={
                        "cruise_id": {"type": "string", "const": cruise.id},
                    },
                ))

    return affordances
