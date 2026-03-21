"""Traditional server — N individual tools, no affordances, for cruise booking eval."""

from __future__ import annotations

import json

from eval.cruise_backend.context import CruiseContext
from eval.cruise_backend.domain import CruiseEngine
from eval.cruise_backend.models import (
    BookingStatus,
    PaymentStatus,
)
from eval.backend.domain import DomainError
from eval.backend.models import DecisionRecord, DomainEvent

from .tools_15 import CRUISE_TOOLS_15
from .tools_30 import CRUISE_TOOLS_30
from .tools_60 import CRUISE_TOOLS_60

CRUISE_TOOL_LEVELS: dict[int | str, list[dict]] = {
    15: CRUISE_TOOLS_15,
    30: CRUISE_TOOLS_30,
    60: CRUISE_TOOLS_60,
}


class CruiseTradRuntime:
    """Traditional runtime — one tool per operation, no affordances."""

    def __init__(self, db_path: str = ":memory:", tool_level: int | str = 15):
        self.ctx = CruiseContext(db_path=db_path)
        self.engine = CruiseEngine()
        self.tool_level = tool_level
        self.tools = CRUISE_TOOL_LEVELS[tool_level]
        self.name_map: dict[str, str] | None = None
        self.default_session_id: str = ""

    def create_session(self, acting_user_id: str) -> str:
        session = self.ctx.db.create_session(acting_user_id=acting_user_id)
        if not self.default_session_id:
            self.default_session_id = session.id
        return session.id

    def _sid(self, session_id: str) -> str:
        return session_id or self.default_session_id

    def get_tool_definitions(self) -> list[dict]:
        """Return OpenAI-format tool definitions for the current tool level."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            k: v for k, v in t["parameters"].items()
                        },
                        "required": t["required"],
                    },
                },
            }
            for t in self.tools
        ]

    def call_tool(self, tool_name: str, params: dict, session_id: str = "") -> str:
        """Execute a tool call. Returns JSON result (no affordances)."""
        sid = self._sid(session_id)
        session = self.ctx.get_session(sid)
        if not session:
            return json.dumps({"error": f"Session '{sid}' not found"})

        user = self.ctx.get_user(session.acting_user_id)
        if not user:
            return json.dumps({"error": f"Acting user '{session.acting_user_id}' not found"})

        # Validate tool exists at current level
        valid_names = {t["name"] for t in self.tools}
        if tool_name not in valid_names:
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=False,
                error_message=f"Unknown tool: {tool_name}",
            )
            self.ctx.db.record_decision(decision)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            result, events = self._dispatch(sid, tool_name, params, user)
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=True,
                result_summary=str(result.get("message", ""))[:200] if isinstance(result, dict) else "",
                events=[e.model_dump() for e in events],
            )
            self.ctx.db.record_decision(decision)
            response = {"data": result}
            if events:
                response["events"] = [e.model_dump() for e in events]
            return json.dumps(response, indent=2)

        except DomainError as e:
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=False,
                error_message=str(e),
            )
            self.ctx.db.record_decision(decision)
            return json.dumps({"error": str(e)})
        except Exception as e:
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=False,
                error_message=f"Runtime error: {e}",
            )
            self.ctx.db.record_decision(decision)
            return json.dumps({"error": f"Runtime error: {e}"})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_cruise_passports(self, session_id: str, cruise_id: str) -> set[str]:
        """Collect all passport numbers for passengers on a given cruise."""
        passengers = self.ctx.db.get_cruise_passengers(session_id, cruise_id)
        return {p.passport_number for p in passengers}

    def _get_cabin_capacity(self, cabin_type_id: str) -> int:
        ct = self.ctx.get_cabin_type(cabin_type_id)
        return ct.capacity if ct else 0

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, session_id, tool_name, params, user):  # noqa: C901
        ctx = self.ctx
        engine = self.engine
        events: list[DomainEvent] = []

        # =====================================================================
        # 15-level core tools
        # =====================================================================

        if tool_name == "get_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            passengers = ctx.db.get_booking_passengers(booking.id)
            payments = ctx.db.get_booking_payments(booking.id)
            return {
                **booking.model_dump(),
                "passengers": [p.model_dump() for p in passengers],
                "payments": [p.model_dump() for p in payments],
            }, []

        elif tool_name == "create_booking":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            cabin_type = ctx.get_cabin_type(params["cabin_type_id"])
            if not cabin_type:
                raise DomainError(f"Cabin type '{params['cabin_type_id']}' not found.")
            count = ctx.db.get_cabin_type_booking_count(
                session_id, cruise.id, cabin_type.id,
            )
            booking, event = engine.create_booking(user, cruise, cabin_type, count)
            booking = ctx.db.create_booking(booking)
            return {"message": f"Created booking '{booking.id}'", "booking_id": booking.id}, [event]

        elif tool_name == "cancel_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            event = engine.cancel_booking(user, booking, cruise)
            ctx.db.update_booking(booking)
            return {"message": f"Cancelled booking '{booking.id}'"}, [event]

        elif tool_name == "add_passenger":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise_passports = self._get_cruise_passports(session_id, booking.cruise_id)
            cabin_capacity = self._get_cabin_capacity(booking.cabin_type_id)
            current_count = len(ctx.db.get_booking_passengers(booking.id))
            passenger, event = engine.add_passenger(
                user, booking,
                params["name"], params["passport_number"],
                params.get("emergency_contact", ""),
                cruise_passports, cabin_capacity, current_count,
            )
            passenger = ctx.db.create_passenger(passenger)
            return {
                "message": f"Added passenger '{passenger.name}'",
                "passenger_id": passenger.id,
            }, [event]

        elif tool_name == "create_payment":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            payment, event = engine.create_payment(
                user, booking, float(params["amount"]), params["method"],
            )
            payment = ctx.db.create_payment(payment)
            return {
                "message": f"Created payment '{payment.id}'",
                "payment_id": payment.id,
            }, [event]

        elif tool_name == "capture_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.capture_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Captured payment '{payment.id}'"}, [event]

        elif tool_name == "confirm_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            passenger_count = len(ctx.db.get_booking_passengers(booking.id))
            event = engine.confirm_booking(user, booking, passenger_count)
            ctx.db.update_booking(booking)
            return {"message": f"Confirmed booking '{booking.id}'"}, [event]

        elif tool_name == "pay_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            payments = ctx.db.get_booking_payments(booking.id)
            captured_exists = any(p.status == PaymentStatus.captured for p in payments)
            event = engine.pay_booking(user, booking, captured_exists)
            ctx.db.update_booking(booking)
            return {"message": f"Marked booking '{booking.id}' as paid"}, [event]

        elif tool_name == "get_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            cabin_types = ctx.get_cabin_types_for_cruise(cruise.template_id)
            return {
                **cruise.model_dump(),
                "cabin_types": [ct.model_dump() for ct in cabin_types],
            }, []

        elif tool_name == "search_bookings":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_bookings(session_id, filters)
            return {"bookings": [
                {"id": b.id, "cruise_id": b.cruise_id, "cabin_type_id": b.cabin_type_id,
                 "status": b.status.value, "passenger_count": b.passenger_count}
                for b in results
            ]}, []

        elif tool_name == "search_passengers":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_passengers(session_id, filters)
            return {"passengers": [
                {"id": p.id, "booking_id": p.booking_id, "name": p.name,
                 "passport_number": p.passport_number}
                for p in results
            ]}, []

        elif tool_name == "refund_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.refund_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Refunded payment '{payment.id}'"}, [event]

        elif tool_name == "get_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            return payment.model_dump(), []

        elif tool_name == "board_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            bookings = ctx.db.get_cruise_bookings(cruise.id)
            held_count = sum(1 for b in bookings if b.status == BookingStatus.held)
            event = engine.board_cruise(user, cruise, held_count)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' is now boarding"}, [event]

        elif tool_name == "embark_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            event = engine.embark_booking(user, booking, cruise)
            ctx.db.update_booking(booking)
            return {"message": f"Embarked booking '{booking.id}'"}, [event]

        # =====================================================================
        # 30-level extra tools
        # =====================================================================

        elif tool_name == "authorize_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.authorize_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Authorized payment '{payment.id}'"}, [event]

        elif tool_name == "update_passenger":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            booking = ctx.db.get_booking(passenger.booking_id)
            if not booking:
                raise DomainError(f"Booking '{passenger.booking_id}' not found.")
            event = engine.update_passenger(
                user, booking, passenger,
                name=params.get("name"),
                emergency_contact=params.get("emergency_contact"),
            )
            ctx.db.update_passenger(passenger)
            return {"message": f"Updated passenger '{passenger.id}'"}, [event]

        elif tool_name == "remove_passenger":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            booking = ctx.db.get_booking(passenger.booking_id)
            if not booking:
                raise DomainError(f"Booking '{passenger.booking_id}' not found.")
            event = engine.remove_passenger(user, booking, passenger)
            # Delete from DB directly (no delete_passenger method on CruiseDB)
            ctx.db.conn.execute("DELETE FROM passengers WHERE id = ?", (passenger.id,))
            ctx.db.conn.commit()
            return {"message": f"Removed passenger '{passenger.name}'"}, [event]

        elif tool_name == "get_passenger":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            return passenger.model_dump(), []

        elif tool_name == "sail_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            event = engine.sail_cruise(user, cruise)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' is now sailing"}, [event]

        elif tool_name == "complete_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            event = engine.complete_cruise(user, cruise)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' is now completed"}, [event]

        elif tool_name == "cancel_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            event = engine.cancel_cruise(user, cruise)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cancelled cruise '{cruise.name}'"}, [event]

        elif tool_name == "search_payments":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_payments(session_id, filters)
            return {"payments": [
                {"id": p.id, "booking_id": p.booking_id, "amount": p.amount,
                 "status": p.status.value, "method": p.method}
                for p in results
            ]}, []

        elif tool_name == "list_cruises":
            cruises = ctx.db.get_session_cruises(session_id)
            return {"cruises": [
                {"id": c.id, "name": c.name, "ship": c.ship,
                 "departure_date": c.departure_date, "status": c.status.value}
                for c in cruises
            ]}, []

        elif tool_name == "list_users":
            users = ctx.get_all_users()
            if "role" in params and params["role"]:
                users = [u for u in users if u.role.value == params["role"]]
            return {"users": [
                {"id": u.id, "name": u.name, "email": u.email, "role": u.role.value}
                for u in users
            ]}, []

        elif tool_name == "get_user":
            u = ctx.get_user(params["user_id"])
            if not u:
                raise DomainError(f"User '{params['user_id']}' not found.")
            return u.model_dump(), []

        elif tool_name == "get_cabin_availability":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            cabin_types = ctx.get_cabin_types_for_cruise(cruise.template_id)
            availability = []
            for ct in cabin_types:
                booked = ctx.db.get_cabin_type_booking_count(session_id, cruise.id, ct.id)
                availability.append({
                    "cabin_type_id": ct.id,
                    "name": ct.name,
                    "capacity": ct.capacity,
                    "total_count": ct.total_count,
                    "booked": booked,
                    "available": ct.total_count - booked,
                    "price_per_passenger": ct.price_per_passenger,
                })
            return {"cruise_id": cruise.id, "cabin_availability": availability}, []

        elif tool_name == "get_booking_passengers":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            passengers = ctx.db.get_booking_passengers(booking.id)
            return {"passengers": [p.model_dump() for p in passengers]}, []

        elif tool_name == "get_booking_payments":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            payments = ctx.db.get_booking_payments(booking.id)
            return {"payments": [p.model_dump() for p in payments]}, []

        elif tool_name == "authorize_and_capture":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            evt_auth = engine.authorize_payment(user, payment)
            ctx.db.update_payment(payment)
            evt_cap = engine.capture_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Authorized and captured payment '{payment.id}'"}, [evt_auth, evt_cap]

        # =====================================================================
        # 60-level extra tools
        # =====================================================================

        # --- Per-field updates ---

        elif tool_name == "set_passenger_name":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            booking = ctx.db.get_booking(passenger.booking_id)
            if not booking:
                raise DomainError(f"Booking '{passenger.booking_id}' not found.")
            event = engine.update_passenger(user, booking, passenger, name=params["name"])
            ctx.db.update_passenger(passenger)
            return {"message": f"Updated passenger name"}, [event]

        elif tool_name == "set_passenger_emergency_contact":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            booking = ctx.db.get_booking(passenger.booking_id)
            if not booking:
                raise DomainError(f"Booking '{passenger.booking_id}' not found.")
            event = engine.update_passenger(
                user, booking, passenger, emergency_contact=params["emergency_contact"],
            )
            ctx.db.update_passenger(passenger)
            return {"message": f"Updated passenger emergency contact"}, [event]

        elif tool_name == "set_booking_cabin_type":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            if booking.status != BookingStatus.held:
                raise DomainError(
                    f"Can only change cabin type on held bookings "
                    f"(booking is '{booking.status.value}')."
                )
            cabin_type = ctx.get_cabin_type(params["cabin_type_id"])
            if not cabin_type:
                raise DomainError(f"Cabin type '{params['cabin_type_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            count = ctx.db.get_cabin_type_booking_count(
                session_id, cruise.id, cabin_type.id,
            )
            if count >= cabin_type.total_count:
                raise DomainError(
                    f"No cabins available for type '{cabin_type.name}' "
                    f"({count}/{cabin_type.total_count} booked)."
                )
            booking.cabin_type_id = cabin_type.id
            ctx.db.update_booking(booking)
            return {"message": f"Changed cabin type to '{cabin_type.name}'"}, [
                DomainEvent(type="BookingCabinTypeChanged", data={
                    "booking": booking.id, "cabin_type": cabin_type.name, "by": user.name,
                })
            ]

        # --- Status-specific search ---

        elif tool_name == "search_bookings_by_status":
            results = ctx.db.search_bookings(session_id, {"status": params["status"]})
            return {"bookings": [
                {"id": b.id, "cruise_id": b.cruise_id, "status": b.status.value}
                for b in results
            ]}, []

        elif tool_name == "search_bookings_by_cruise":
            results = ctx.db.search_bookings(session_id, {"cruise_id": params["cruise_id"]})
            return {"bookings": [
                {"id": b.id, "cabin_type_id": b.cabin_type_id, "status": b.status.value}
                for b in results
            ]}, []

        elif tool_name == "search_bookings_by_cabin_type":
            results = ctx.db.search_bookings(session_id, {"cabin_type_id": params["cabin_type_id"]})
            return {"bookings": [
                {"id": b.id, "cruise_id": b.cruise_id, "status": b.status.value}
                for b in results
            ]}, []

        elif tool_name == "search_passengers_by_booking":
            results = ctx.db.search_passengers(session_id, {"booking_id": params["booking_id"]})
            return {"passengers": [
                {"id": p.id, "name": p.name, "passport_number": p.passport_number}
                for p in results
            ]}, []

        elif tool_name == "search_passengers_by_passport":
            results = ctx.db.search_passengers(session_id, {"passport_number": params["passport_number"]})
            return {"passengers": [
                {"id": p.id, "booking_id": p.booking_id, "name": p.name}
                for p in results
            ]}, []

        elif tool_name == "search_payments_by_status":
            results = ctx.db.search_payments(session_id, {"status": params["status"]})
            return {"payments": [
                {"id": p.id, "booking_id": p.booking_id, "amount": p.amount, "status": p.status.value}
                for p in results
            ]}, []

        elif tool_name == "search_payments_by_booking":
            results = ctx.db.search_payments(session_id, {"booking_id": params["booking_id"]})
            return {"payments": [
                {"id": p.id, "amount": p.amount, "status": p.status.value, "method": p.method}
                for p in results
            ]}, []

        # --- Bulk operations ---

        elif tool_name == "bulk_cancel_bookings":
            evts = []
            for bid in params["booking_ids"]:
                booking = ctx.db.get_booking(bid)
                if not booking:
                    continue
                cruise = ctx.db.get_cruise(booking.cruise_id)
                if not cruise:
                    continue
                evt = engine.cancel_booking(user, booking, cruise)
                ctx.db.update_booking(booking)
                evts.append(evt)
            return {"message": f"Bulk cancelled {len(evts)} bookings"}, evts

        elif tool_name == "bulk_embark":
            evts = []
            for bid in params["booking_ids"]:
                booking = ctx.db.get_booking(bid)
                if not booking:
                    continue
                cruise = ctx.db.get_cruise(booking.cruise_id)
                if not cruise:
                    continue
                evt = engine.embark_booking(user, booking, cruise)
                ctx.db.update_booking(booking)
                evts.append(evt)
            return {"message": f"Bulk embarked {len(evts)} bookings"}, evts

        # --- Analytics ---

        elif tool_name == "get_cruise_stats":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            bookings = ctx.db.get_cruise_bookings(cruise.id)
            by_status: dict[str, int] = {}
            for b in bookings:
                by_status.setdefault(b.status.value, 0)
                by_status[b.status.value] += 1
            # Revenue from captured payments on this cruise's bookings
            total_revenue = 0.0
            total_passengers = 0
            for b in bookings:
                payments = ctx.db.get_booking_payments(b.id)
                total_revenue += sum(
                    p.amount for p in payments if p.status == PaymentStatus.captured
                )
                total_passengers += len(ctx.db.get_booking_passengers(b.id))
            return {
                "cruise": cruise.name,
                "total_bookings": len(bookings),
                "by_status": by_status,
                "total_revenue": total_revenue,
                "total_passengers": total_passengers,
            }, []

        elif tool_name == "get_revenue_summary":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            bookings = ctx.db.get_cruise_bookings(cruise.id)
            captured = 0.0
            refunded = 0.0
            pending = 0.0
            for b in bookings:
                payments = ctx.db.get_booking_payments(b.id)
                for p in payments:
                    if p.status == PaymentStatus.captured:
                        captured += p.amount
                    elif p.status == PaymentStatus.refunded:
                        refunded += p.amount
                    elif p.status in (PaymentStatus.pending, PaymentStatus.authorized):
                        pending += p.amount
            return {
                "cruise": cruise.name,
                "captured": captured,
                "refunded": refunded,
                "pending": pending,
                "net": captured - refunded,
            }, []

        elif tool_name == "get_cruise_manifest":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            passengers = ctx.db.get_cruise_passengers(session_id, cruise.id)
            manifest = []
            for p in passengers:
                manifest.append({
                    "passenger_id": p.id,
                    "name": p.name,
                    "passport_number": p.passport_number,
                    "booking_id": p.booking_id,
                    "emergency_contact": p.emergency_contact,
                })
            return {"cruise": cruise.name, "passenger_count": len(manifest), "manifest": manifest}, []

        # --- Audit ---

        elif tool_name == "get_booking_history":
            decisions = ctx.db.get_session_decisions(session_id)
            booking_decisions = [
                d for d in decisions
                if d.params.get("booking_id") == params["booking_id"]
                or params["booking_id"] in str(d.params)
            ]
            return {"history": [
                {"action": d.action, "by": d.actor_name, "at": d.timestamp,
                 "valid": d.was_valid, "summary": d.result_summary}
                for d in booking_decisions
            ]}, []

        elif tool_name == "get_payment_history":
            decisions = ctx.db.get_session_decisions(session_id)
            payment_decisions = [
                d for d in decisions
                if d.params.get("payment_id") == params["payment_id"]
                or params["payment_id"] in str(d.params)
            ]
            return {"history": [
                {"action": d.action, "by": d.actor_name, "at": d.timestamp,
                 "valid": d.was_valid, "summary": d.result_summary}
                for d in payment_decisions
            ]}, []

        # --- Partial refund (full refund — same domain constraint) ---

        elif tool_name == "partial_refund":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.refund_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Refunded payment '{payment.id}'"}, [event]

        # --- Workflow shortcuts ---

        elif tool_name == "full_checkin":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            event = engine.embark_booking(user, booking, cruise)
            ctx.db.update_booking(booking)
            return {"message": f"Checked in booking '{booking.id}'"}, [event]

        elif tool_name == "create_and_authorize_payment":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            payment, evt_create = engine.create_payment(
                user, booking, float(params["amount"]), params["method"],
            )
            payment = ctx.db.create_payment(payment)
            evt_auth = engine.authorize_payment(user, payment)
            ctx.db.update_payment(payment)
            return {
                "message": f"Created and authorized payment '{payment.id}'",
                "payment_id": payment.id,
            }, [evt_create, evt_auth]

        # --- Cross-entity queries ---

        elif tool_name == "get_passenger_booking":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            booking = ctx.db.get_booking(passenger.booking_id)
            if not booking:
                raise DomainError(f"Booking '{passenger.booking_id}' not found.")
            return booking.model_dump(), []

        elif tool_name == "get_booking_cruise":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            return cruise.model_dump(), []

        # --- Session info ---

        elif tool_name == "get_session":
            session = ctx.get_session(session_id)
            if not session:
                raise DomainError(f"Session '{session_id}' not found.")
            return session.model_dump(), []

        # --- Inventory checks ---

        elif tool_name == "check_cabin_availability":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            cabin_type = ctx.get_cabin_type(params["cabin_type_id"])
            if not cabin_type:
                raise DomainError(f"Cabin type '{params['cabin_type_id']}' not found.")
            booked = ctx.db.get_cabin_type_booking_count(
                session_id, cruise.id, cabin_type.id,
            )
            available = cabin_type.total_count - booked
            return {
                "cabin_type_id": cabin_type.id,
                "name": cabin_type.name,
                "total_count": cabin_type.total_count,
                "booked": booked,
                "available": available,
                "has_availability": available > 0,
            }, []

        elif tool_name == "get_cabin_type_details":
            cabin_type = ctx.get_cabin_type(params["cabin_type_id"])
            if not cabin_type:
                raise DomainError(f"Cabin type '{params['cabin_type_id']}' not found.")
            return cabin_type.model_dump(), []

        # --- Duplicate check ---

        elif tool_name == "check_passport_duplicate":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            passports = self._get_cruise_passports(session_id, cruise.id)
            is_duplicate = params["passport_number"] in passports
            return {
                "passport_number": params["passport_number"],
                "cruise_id": cruise.id,
                "is_duplicate": is_duplicate,
            }, []

        # --- Count queries ---

        elif tool_name == "count_bookings":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_bookings(session_id, filters)
            return {"count": len(results)}, []

        elif tool_name == "count_passengers":
            passengers = ctx.db.get_booking_passengers(params["booking_id"])
            return {"count": len(passengers)}, []

        elif tool_name == "count_payments":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_payments(session_id, filters)
            return {"count": len(results)}, []

        # --- Combined view ---

        elif tool_name == "list_booking_passengers_and_payments":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            passengers = ctx.db.get_booking_passengers(booking.id)
            payments = ctx.db.get_booking_payments(booking.id)
            return {
                "booking_id": booking.id,
                "passengers": [p.model_dump() for p in passengers],
                "payments": [p.model_dump() for p in payments],
            }, []

        else:
            raise DomainError(f"Tool '{tool_name}' not implemented.")
