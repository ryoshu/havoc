"""GAS server — 3 generic tools (get, search, act) for the cruise booking eval."""

from __future__ import annotations

import json

from eval.cruise_backend.context import CruiseContext
from eval.cruise_backend.domain import CruiseEngine
from eval.cruise_backend.models import (
    BookingStatus,
    PaymentStatus,
)
from eval.backend.domain import DomainError
from eval.backend.models import Affordance, DecisionRecord

from .affordances import compute_cruise_affordances
from eval.gas_server.contracts import EnforcedGasMixin


def _compact_affordances(affordances: list[Affordance]) -> list[dict]:
    """Compact affordances by grouping per action type.

    Instead of N per-entity entries with repeated schemas, produces one entry
    per action type with a ``targets`` list of applicable entity IDs and a
    shared ``params`` dict for non-const parameters.

    Singleton affordances (only one instance of an action) are emitted inline
    without a ``targets`` wrapper.
    """
    from collections import OrderedDict

    groups: OrderedDict[str, list[Affordance]] = OrderedDict()
    for a in affordances:
        groups.setdefault(a.action, []).append(a)

    result: list[dict] = []
    for action, items in groups.items():
        if len(items) == 1:
            # Singleton — emit inline (no batching overhead)
            a = items[0]
            entry: dict = {"action": a.action, "description": a.description}
            if a.schema_:
                entry["params"] = _simplify_schema(a.schema_)
            if a.constraints:
                entry["constraints"] = a.constraints
            result.append(entry)
            continue

        # Multiple instances — batch by action type.
        # Separate const params (vary per entity) from shared params (same across all).
        const_keys: list[str] = []
        shared_params: dict = {}
        sample = items[0].schema_

        for key, spec in sample.items():
            if isinstance(spec, dict) and "const" in spec:
                const_keys.append(key)
            else:
                shared_params[key] = _simplify_param(spec)

        entry = {"action": action}

        # Build compact targets list
        targets: list[dict] = []
        for a in items:
            target: dict = {}
            for ck in const_keys:
                target[ck] = a.schema_[ck]["const"]
            # Include per-entity description as label
            target["_desc"] = a.description
            # Per-entity enum overrides (e.g., different valid values per entity)
            for key, spec in a.schema_.items():
                if key in const_keys:
                    continue
                if isinstance(spec, dict) and "enum" in spec:
                    shared_val = sample.get(key, {})
                    if isinstance(shared_val, dict) and spec.get("enum") != shared_val.get("enum"):
                        target[key] = spec["enum"]
            if a.constraints:
                target["constraints"] = a.constraints
            targets.append(target)

        # Merge targets sharing the same primary entity key.
        if len(const_keys) > 1:
            primary = const_keys[0]
            merged: OrderedDict[str, dict] = OrderedDict()
            for t in targets:
                pk = t[primary]
                if pk not in merged:
                    merged[pk] = dict(t)
                else:
                    # Merge the non-primary const values into lists
                    existing = merged[pk]
                    for ck in const_keys[1:]:
                        old_val = existing.get(ck)
                        new_val = t.get(ck)
                        if old_val is None:
                            existing[ck] = new_val
                        elif isinstance(old_val, list):
                            existing[ck].append(new_val)
                        else:
                            existing[ck] = [old_val, new_val]
                    # Merge descriptions
                    if "_desc" in t:
                        old_desc = existing.get("_desc", "")
                        if isinstance(old_desc, list):
                            old_desc.append(t["_desc"])
                        else:
                            existing["_desc"] = [old_desc, t["_desc"]]
            targets = list(merged.values())

        entry["targets"] = targets
        if shared_params:
            entry["params"] = shared_params
        result.append(entry)

    return result


def _simplify_schema(schema: dict) -> dict:
    """Simplify a parameter schema by stripping redundant JSON Schema wrappers."""
    out = {}
    for key, spec in schema.items():
        out[key] = _simplify_param(spec)
    return out


def _simplify_param(spec) -> str | list | dict:
    """Collapse ``{"type": "string", "const": "x"}`` → ``"x"`` etc."""
    if not isinstance(spec, dict):
        return spec
    if "const" in spec:
        return spec["const"]
    if "enum" in spec:
        return spec["enum"]
    if spec.get("type") == "object" and "properties" in spec:
        return {k: _simplify_param(v) for k, v in spec["properties"].items()}
    if spec.get("type") == "string":
        return "string"
    if spec.get("type") == "number":
        return "number"
    return spec


class CruiseGasRuntime(EnforcedGasMixin):
    """Encapsulates cruise eval state for a single runtime instance."""

    def __init__(self, db_path: str = ":memory:", mode: str = "gas-advisory"):
        self.ctx = CruiseContext(db_path=db_path)
        self.engine = CruiseEngine()
        self.mode = mode
        self._contract_revisions: dict[str, int] = {}
        self.default_session_id: str = ""

    def _contract_affordances(self, session_id: str):
        return compute_cruise_affordances(self.ctx, session_id)

    def create_session(self, acting_user_id: str) -> str:
        session = self.ctx.db.create_session(acting_user_id=acting_user_id)
        if not self.default_session_id:
            self.default_session_id = session.id
        return session.id

    def _sid(self, session_id: str) -> str:
        return session_id or self.default_session_id

    def _format(self, data, affordances) -> dict:
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        return {"data": data, "affordances": _compact_affordances(affordances)}

    # --- get ---

    def get(self, resource_type: str, id: str = "", session_id: str = "") -> str:
        sid = self._sid(session_id)
        try:
            if resource_type == "cruise":
                cruise = self.ctx.db.get_cruise(id)
                if not cruise:
                    return json.dumps({"error": f"Cruise '{id}' not found"})
                cruise_bookings = self.ctx.db.get_cruise_bookings(cruise.id)
                data = {
                    **cruise.model_dump(),
                    "bookings": [
                        {"id": b.id, "status": b.status.value,
                         "cabin_type_id": b.cabin_type_id, "passenger_count": b.passenger_count}
                        for b in cruise_bookings
                    ],
                }
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "booking":
                booking = self.ctx.db.get_booking(id)
                if not booking:
                    return json.dumps({"error": f"Booking '{id}' not found"})
                passengers = self.ctx.db.get_booking_passengers(booking.id)
                payments = self.ctx.db.get_booking_payments(booking.id)
                data = {
                    **booking.model_dump(),
                    "passengers": [p.model_dump() for p in passengers],
                    "payments": [p.model_dump() for p in payments],
                }
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "passenger":
                passenger = self.ctx.db.get_passenger(id)
                if not passenger:
                    return json.dumps({"error": f"Passenger '{id}' not found"})
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(passenger, affs), indent=2)

            elif resource_type == "payment":
                payment = self.ctx.db.get_payment(id)
                if not payment:
                    return json.dumps({"error": f"Payment '{id}' not found"})
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(payment, affs), indent=2)

            elif resource_type == "user":
                user = self.ctx.get_user(id)
                if not user:
                    return json.dumps({"error": f"User '{id}' not found"})
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(user, affs), indent=2)

            elif resource_type == "session":
                session = self.ctx.get_session(id or sid)
                if not session:
                    return json.dumps({"error": f"Session '{id or sid}' not found"})
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(session, affs), indent=2)

            else:
                return json.dumps({"error": f"Unknown resource type: {resource_type}"})

        except Exception as e:
            return json.dumps({"error": str(e)})

    # --- search ---

    def search(self, resource_type: str, filters: str = "{}", session_id: str = "") -> str:
        sid = self._sid(session_id)
        try:
            parsed = json.loads(filters) if isinstance(filters, str) else filters
        except json.JSONDecodeError:
            parsed = {}

        try:
            if resource_type == "cruises":
                results = self.ctx.db.get_session_cruises(sid)
                data = [
                    {"id": c.id, "name": c.name, "status": c.status.value, "ship": c.ship}
                    for c in results
                ]
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "bookings":
                results = self.ctx.db.search_bookings(sid, parsed)
                data = [
                    {"id": b.id, "cruise_id": b.cruise_id,
                     "cabin_type_id": b.cabin_type_id, "status": b.status.value,
                     "passenger_count": b.passenger_count}
                    for b in results
                ]
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "passengers":
                results = self.ctx.db.search_passengers(sid, parsed)
                data = [
                    {"id": p.id, "booking_id": p.booking_id,
                     "name": p.name, "passport_number": p.passport_number}
                    for p in results
                ]
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "payments":
                results = self.ctx.db.search_payments(sid, parsed)
                data = [
                    {"id": p.id, "booking_id": p.booking_id,
                     "amount": p.amount, "status": p.status.value}
                    for p in results
                ]
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "users":
                results = self.ctx.get_all_users()
                if "role" in parsed:
                    results = [u for u in results if u.role.value == parsed["role"]]
                data = [
                    {"id": u.id, "name": u.name, "role": u.role.value}
                    for u in results
                ]
                affs = compute_cruise_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            else:
                return json.dumps({"error": f"Unknown search type: {resource_type}"})

        except Exception as e:
            return json.dumps({"error": str(e)})

    # --- act ---

    def act(self, action: str, params: str = "{}", session_id: str = "") -> str:
        sid = self._sid(session_id)
        try:
            parsed = json.loads(params) if isinstance(params, str) else params
        except json.JSONDecodeError:
            parsed = {}

        session = self.ctx.get_session(sid)
        if not session:
            return json.dumps({"error": f"Session '{sid}' not found"})

        user = self.ctx.get_user(session.acting_user_id)
        if not user:
            return json.dumps({"error": f"Acting user '{session.acting_user_id}' not found"})

        # Snapshot affordances before action
        pre_affordances = compute_cruise_affordances(self.ctx, sid)
        affordances_snapshot = [
            {"action": a.action, "description": a.description}
            for a in pre_affordances
        ]
        affordances_not_taken = [
            a.action for a in pre_affordances if a.action != action
        ]

        try:
            result, events = self._dispatch(sid, action, parsed, user)

            decision = DecisionRecord(
                session_id=sid,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                result_summary=str(result.get("message", ""))[:200] if isinstance(result, dict) else "",
                events=[e.model_dump() for e in events],
                was_valid=True,
            )
            self.ctx.db.record_decision(decision)

            affs = compute_cruise_affordances(self.ctx, sid)
            response = self._format(result, affs)
            if events:
                response["events"] = [e.model_dump() for e in events]
            return json.dumps(response, indent=2)

        except DomainError as e:
            decision = DecisionRecord(
                session_id=sid,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                was_valid=False,
                error_message=str(e),
            )
            self.ctx.db.record_decision(decision)

            affs = compute_cruise_affordances(self.ctx, sid)
            return json.dumps({
                "error": str(e),
                "affordances": _compact_affordances(affs),
            }, indent=2)
        except Exception as e:
            decision = DecisionRecord(
                session_id=sid,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                was_valid=False,
                error_message=f"Runtime error: {e}",
            )
            self.ctx.db.record_decision(decision)

            affs = compute_cruise_affordances(self.ctx, sid)
            return json.dumps({
                "error": f"Runtime error: {e}",
                "affordances": _compact_affordances(affs),
            }, indent=2)

    def _dispatch(self, session_id, action, params, user):
        ctx = self.ctx
        engine = self.engine
        events = []

        # --- Booking actions ---
        if action == "create_booking":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            cabin_type = ctx.get_cabin_type(params["cabin_type_id"])
            if not cabin_type:
                raise DomainError(f"Cabin type '{params['cabin_type_id']}' not found.")
            booked = ctx.db.get_cabin_type_booking_count(
                session_id, cruise.id, cabin_type.id,
            )
            booking, event = engine.create_booking(user, cruise, cabin_type, booked)
            booking = ctx.db.create_booking(booking)
            return {"message": f"Created booking '{booking.id}'", "booking_id": booking.id}, [event]

        elif action == "add_passenger":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            cruise_passengers = ctx.db.get_cruise_passengers(session_id, booking.cruise_id) if cruise else []
            cruise_passports = {p.passport_number for p in cruise_passengers}
            cabin_type = ctx.get_cabin_type(booking.cabin_type_id)
            capacity = cabin_type.capacity if cabin_type else 0
            current_passengers = ctx.db.get_booking_passengers(booking.id)
            passenger, event = engine.add_passenger(
                user, booking,
                params["name"], params["passport_number"],
                params.get("emergency_contact", ""),
                cruise_passports, capacity, len(current_passengers),
            )
            passenger = ctx.db.create_passenger(passenger)
            booking.passenger_count = len(current_passengers) + 1
            ctx.db.update_booking(booking)
            return {
                "message": f"Added passenger '{passenger.name}' to booking '{booking.id}'",
                "passenger_id": passenger.id,
            }, [event]

        elif action == "update_passenger":
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
            return {"message": f"Updated passenger '{passenger.name}'"}, [event]

        elif action == "remove_passenger":
            passenger = ctx.db.get_passenger(params["passenger_id"])
            if not passenger:
                raise DomainError(f"Passenger '{params['passenger_id']}' not found.")
            booking = ctx.db.get_booking(passenger.booking_id)
            if not booking:
                raise DomainError(f"Booking '{passenger.booking_id}' not found.")
            event = engine.remove_passenger(user, booking, passenger)
            # Delete from DB directly (no delete_passenger method, use conn)
            ctx.db.conn.execute("DELETE FROM passengers WHERE id = ?", (passenger.id,))
            ctx.db.conn.commit()
            booking.passenger_count = max(0, booking.passenger_count - 1)
            ctx.db.update_booking(booking)
            return {"message": f"Removed passenger '{passenger.name}' from booking '{booking.id}'"}, [event]

        elif action == "confirm_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            passengers = ctx.db.get_booking_passengers(booking.id)
            event = engine.confirm_booking(user, booking, len(passengers))
            ctx.db.update_booking(booking)
            return {"message": f"Confirmed booking '{booking.id}'"}, [event]

        elif action == "create_payment":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            payment, event = engine.create_payment(
                user, booking,
                float(params["amount"]), params.get("method", ""),
            )
            payment = ctx.db.create_payment(payment)
            return {
                "message": f"Created payment '{payment.id}' for booking '{booking.id}'",
                "payment_id": payment.id,
            }, [event]

        elif action == "authorize_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.authorize_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Authorized payment '{payment.id}'"}, [event]

        elif action == "capture_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.capture_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Captured payment '{payment.id}'"}, [event]

        elif action == "pay_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            payments = ctx.db.get_booking_payments(booking.id)
            has_captured = any(p.status == PaymentStatus.captured for p in payments)
            event = engine.pay_booking(user, booking, has_captured)
            ctx.db.update_booking(booking)
            return {"message": f"Booking '{booking.id}' marked as paid"}, [event]

        elif action == "embark_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            event = engine.embark_booking(user, booking, cruise)
            ctx.db.update_booking(booking)
            return {"message": f"Embarked booking '{booking.id}'"}, [event]

        elif action == "cancel_booking":
            booking = ctx.db.get_booking(params["booking_id"])
            if not booking:
                raise DomainError(f"Booking '{params['booking_id']}' not found.")
            cruise = ctx.db.get_cruise(booking.cruise_id)
            if not cruise:
                raise DomainError(f"Cruise '{booking.cruise_id}' not found.")
            event = engine.cancel_booking(user, booking, cruise)
            ctx.db.update_booking(booking)
            return {"message": f"Cancelled booking '{booking.id}'"}, [event]

        elif action == "refund_payment":
            payment = ctx.db.get_payment(params["payment_id"])
            if not payment:
                raise DomainError(f"Payment '{params['payment_id']}' not found.")
            event = engine.refund_payment(user, payment)
            ctx.db.update_payment(payment)
            return {"message": f"Refunded payment '{payment.id}'"}, [event]

        # --- Cruise lifecycle actions ---
        elif action == "board_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            cruise_bookings = ctx.db.get_cruise_bookings(cruise.id)
            held_count = sum(1 for b in cruise_bookings if b.status == BookingStatus.held)
            event = engine.board_cruise(user, cruise, held_count)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' is now boarding"}, [event]

        elif action == "sail_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            event = engine.sail_cruise(user, cruise)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' has set sail"}, [event]

        elif action == "complete_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            event = engine.complete_cruise(user, cruise)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' completed"}, [event]

        elif action == "cancel_cruise":
            cruise = ctx.db.get_cruise(params["cruise_id"])
            if not cruise:
                raise DomainError(f"Cruise '{params['cruise_id']}' not found.")
            event = engine.cancel_cruise(user, cruise)
            ctx.db.update_cruise(cruise)
            return {"message": f"Cruise '{cruise.name}' cancelled"}, [event]

        elif action == "get_cabin_availability":
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
                    "price_per_passenger": ct.price_per_passenger,
                    "total_count": ct.total_count,
                    "booked": booked,
                    "available": ct.total_count - booked,
                })
            return {"cruise_id": cruise.id, "cruise_name": cruise.name, "cabin_availability": availability}, events

        else:
            raise DomainError(f"Unknown action: {action}")
