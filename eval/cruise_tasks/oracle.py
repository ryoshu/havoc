"""Oracle — deterministic success checker for cruise eval tasks."""

from __future__ import annotations

from eval.cruise_backend.context import CruiseContext
from eval.cruise_backend.models import BookingStatus, CruiseStatus, PaymentStatus


def check_cruise_oracle(
    ctx: CruiseContext,
    session_id: str,
    checks: list[dict],
    id_map: dict[str, str] | None = None,
) -> tuple[bool, list[dict]]:
    """Run oracle checks against current state. Returns (all_passed, details)."""
    id_map = id_map or {}

    def resolve_id(value: str) -> str:
        if not value:
            return value
        return id_map.get(value, value)

    details = []
    all_passed = True

    for check in checks:
        check_type = check["type"]
        passed = False
        message = ""

        # booking_status: check booking state
        if check_type == "booking_status":
            booking_id = resolve_id(check["booking_id"])
            booking = ctx.db.get_booking(booking_id)
            if booking:
                expected = BookingStatus(check["expected"])
                passed = booking.status == expected
                message = f"Booking '{booking_id}' status: {booking.status.value} (expected {expected.value})"
            else:
                message = f"Booking '{booking_id}' not found"

        # booking_exists: check booking exists with optional filters
        elif check_type == "booking_exists":
            bookings = ctx.db.get_session_bookings(session_id)
            if "cruise_id" in check:
                cruise_id = resolve_id(check["cruise_id"])
                bookings = [b for b in bookings if b.cruise_id == cruise_id]
            if "cabin_type_id" in check:
                bookings = [b for b in bookings if b.cabin_type_id == check["cabin_type_id"]]
            if "status" in check:
                bookings = [b for b in bookings if b.status.value == check["status"]]
            passed = len(bookings) > 0
            message = f"Booking exists matching filters: {passed} (found {len(bookings)})"

        # passenger_exists: check passenger exists
        elif check_type == "passenger_exists":
            passengers = ctx.db.search_passengers(session_id, {})
            if "booking_id" in check:
                bid = resolve_id(check["booking_id"])
                passengers = [p for p in passengers if p.booking_id == bid]
            if "passport_number" in check:
                passengers = [p for p in passengers if p.passport_number == check["passport_number"]]
            if "name_contains" in check:
                needle = check["name_contains"].lower()
                passengers = [p for p in passengers if needle in p.name.lower()]
            passed = len(passengers) > 0
            message = f"Passenger exists matching filters: {passed} (found {len(passengers)})"

        # passenger_count: count passengers on a booking
        elif check_type == "passenger_count":
            booking_id = resolve_id(check["booking_id"])
            passengers = ctx.db.get_booking_passengers(booking_id)
            op = check.get("op", "eq")
            expected = check["expected"]
            count = len(passengers)
            if op == "eq":
                passed = count == expected
            elif op == "gte":
                passed = count >= expected
            elif op == "lte":
                passed = count <= expected
            message = f"Passenger count for booking '{booking_id}' ({op}): {count} vs {expected}"

        # payment_status: check payment state
        elif check_type == "payment_status":
            payment_id = resolve_id(check["payment_id"])
            payment = ctx.db.get_payment(payment_id)
            if payment:
                expected = PaymentStatus(check["expected"])
                passed = payment.status == expected
                message = f"Payment '{payment_id}' status: {payment.status.value} (expected {expected.value})"
            else:
                message = f"Payment '{payment_id}' not found"

        # payment_exists: check payment exists
        elif check_type == "payment_exists":
            payments = ctx.db.search_payments(session_id, {})
            if "booking_id" in check:
                bid = resolve_id(check["booking_id"])
                payments = [p for p in payments if p.booking_id == bid]
            if "status" in check:
                payments = [p for p in payments if p.status.value == check["status"]]
            passed = len(payments) > 0
            message = f"Payment exists matching filters: {passed} (found {len(payments)})"

        # cruise_status: check cruise state
        elif check_type == "cruise_status":
            cruise_id = resolve_id(check["cruise_id"])
            cruise = ctx.db.get_cruise(cruise_id)
            if cruise:
                expected = CruiseStatus(check["expected"])
                passed = cruise.status == expected
                message = f"Cruise '{cruise.name}' status: {cruise.status.value} (expected {expected.value})"
            else:
                message = f"Cruise '{cruise_id}' not found"

        # cabin_availability: check remaining capacity
        elif check_type == "cabin_availability":
            cruise_id = resolve_id(check["cruise_id"])
            cabin_type_id = check["cabin_type_id"]
            cabin_type = ctx.get_cabin_type(cabin_type_id)
            if cabin_type:
                booked = ctx.db.get_cabin_type_booking_count(session_id, cruise_id, cabin_type_id)
                available = cabin_type.total_count - booked
                op = check.get("op", "gte")
                expected = check["expected"]
                if op == "eq":
                    passed = available == expected
                elif op == "gte":
                    passed = available >= expected
                elif op == "lte":
                    passed = available <= expected
                elif op == "lt":
                    passed = available < expected
                message = f"Cabin availability '{cabin_type.name}' ({op}): {available} vs {expected}"
            else:
                message = f"Cabin type '{cabin_type_id}' not found"

        # no_backend_errors: check no invalid decisions
        elif check_type == "no_backend_errors":
            decisions = ctx.db.get_session_decisions(session_id)
            invalid = [d for d in decisions if not d.was_valid]
            passed = len(invalid) == 0
            message = f"Backend errors: {len(invalid)}"

        # booking_count: filtered count with operators
        elif check_type == "booking_count":
            bookings = ctx.db.get_session_bookings(session_id)
            filters = check.get("filters", {})
            if "status" in filters:
                bookings = [b for b in bookings if b.status.value == filters["status"]]
            if "cruise_id" in filters:
                cruise_id = resolve_id(filters["cruise_id"])
                bookings = [b for b in bookings if b.cruise_id == cruise_id]
            if "cabin_type_id" in filters:
                bookings = [b for b in bookings if b.cabin_type_id == filters["cabin_type_id"]]
            op = check.get("op", "eq")
            expected = check["expected"]
            count = len(bookings)
            if op == "eq":
                passed = count == expected
            elif op == "gte":
                passed = count >= expected
            elif op == "lte":
                passed = count <= expected
            message = f"Booking count ({op}): {count} vs {expected}"

        # payment_count: count payments
        elif check_type == "payment_count":
            payments = ctx.db.search_payments(session_id, {})
            filters = check.get("filters", {})
            if "booking_id" in filters:
                bid = resolve_id(filters["booking_id"])
                payments = [p for p in payments if p.booking_id == bid]
            if "status" in filters:
                payments = [p for p in payments if p.status.value == filters["status"]]
            op = check.get("op", "eq")
            expected = check["expected"]
            count = len(payments)
            if op == "eq":
                passed = count == expected
            elif op == "gte":
                passed = count >= expected
            message = f"Payment count ({op}): {count} vs {expected}"

        # passenger_not_exists: verify passenger was removed or doesn't exist
        elif check_type == "passenger_not_exists":
            passengers = ctx.db.search_passengers(session_id, {})
            if "passport_number" in check:
                passengers = [p for p in passengers if p.passport_number == check["passport_number"]]
            if "booking_id" in check:
                bid = resolve_id(check["booking_id"])
                passengers = [p for p in passengers if p.booking_id == bid]
            passed = len(passengers) == 0
            message = f"Passenger not exists: {passed} (found {len(passengers)})"

        else:
            message = f"Unknown check type: {check_type}"

        if not passed:
            all_passed = False
        details.append({"type": check_type, "passed": passed, "message": message})

    return all_passed, details
