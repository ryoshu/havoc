"""GAS server — 3 generic tools (get, search, act) for the automotive dealership eval."""

from __future__ import annotations

import json

from eval.auto_backend.context import AutoContext
from eval.auto_backend.domain import AutoEngine
from eval.auto_backend.models import (
    DealStatus,
    OfferStatus,
    TradeInStatus,
    VehicleStatus,
)
from eval.backend.domain import DomainError
from eval.backend.models import Affordance, DecisionRecord

from .affordances import compute_auto_affordances


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
    """Collapse ``{"type": "string", "const": "x"}`` -> ``"x"`` etc."""
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


class AutoGasRuntime:
    """Encapsulates auto dealership eval state for a single runtime instance."""

    def __init__(self, db_path: str = ":memory:"):
        self.ctx = AutoContext(db_path=db_path)
        self.engine = AutoEngine()
        self.default_session_id: str = ""

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
            if resource_type == "vehicle":
                vehicle = self.ctx.db.get_vehicle(id)
                if not vehicle:
                    return json.dumps({"error": f"Vehicle '{id}' not found"})
                active_deal = self.ctx.db.get_vehicle_active_deal(sid, id)
                data = {**vehicle.model_dump()}
                if active_deal:
                    data["active_deal"] = {
                        "id": active_deal.id,
                        "status": active_deal.status.value,
                        "customer_id": active_deal.customer_id,
                    }
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "customer":
                customer = self.ctx.db.get_customer(id)
                if not customer:
                    return json.dumps({"error": f"Customer '{id}' not found"})
                data = {
                    **customer.model_dump(),
                    "credit_info": {
                        "status": customer.credit_status.value,
                        "score": customer.credit_score,
                        "pre_approved_amount": customer.pre_approved_amount,
                    },
                }
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "deal":
                deal = self.ctx.db.get_deal(id)
                if not deal:
                    return json.dumps({"error": f"Deal '{id}' not found"})
                offers = self.ctx.db.get_deal_offers(deal.id)
                trade_ins = self.ctx.db.get_deal_trade_ins(deal.id)
                data = {
                    **deal.model_dump(),
                    "offers": [o.model_dump() for o in offers],
                    "trade_ins": [ti.model_dump() for ti in trade_ins],
                }
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "offer":
                offer = self.ctx.db.get_offer(id)
                if not offer:
                    return json.dumps({"error": f"Offer '{id}' not found"})
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(offer, affs), indent=2)

            elif resource_type == "trade_in":
                trade_in = self.ctx.db.get_trade_in(id)
                if not trade_in:
                    return json.dumps({"error": f"Trade-in '{id}' not found"})
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(trade_in, affs), indent=2)

            elif resource_type == "test_drive":
                test_drive = self.ctx.db.get_test_drive(id)
                if not test_drive:
                    return json.dumps({"error": f"Test drive '{id}' not found"})
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(test_drive, affs), indent=2)

            elif resource_type == "user":
                user = self.ctx.get_user(id)
                if not user:
                    return json.dumps({"error": f"User '{id}' not found"})
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(user, affs), indent=2)

            elif resource_type == "session":
                session = self.ctx.get_session(id or sid)
                if not session:
                    return json.dumps({"error": f"Session '{id or sid}' not found"})
                affs = compute_auto_affordances(self.ctx, sid)
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
            if resource_type == "vehicles":
                results = self.ctx.db.search_vehicles(sid, parsed)
                data = [
                    {"id": v.id, "make": v.make, "model": v.model, "year": v.year,
                     "trim": v.trim, "status": v.status.value, "msrp": v.msrp}
                    for v in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "customers":
                results = self.ctx.db.search_customers(sid, parsed)
                data = [
                    {"id": c.id, "name": c.name, "email": c.email,
                     "phone": c.phone, "credit_status": c.credit_status.value}
                    for c in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "deals":
                results = self.ctx.db.search_deals(sid, parsed)
                data = [
                    {"id": d.id, "customer_id": d.customer_id,
                     "vehicle_id": d.vehicle_id, "status": d.status.value,
                     "salesperson_id": d.salesperson_id}
                    for d in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "offers":
                results = self.ctx.db.search_offers(sid, parsed)
                data = [
                    {"id": o.id, "deal_id": o.deal_id,
                     "amount": o.amount, "status": o.status.value}
                    for o in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "trade_ins":
                results = self.ctx.db.search_trade_ins(sid, parsed)
                data = [
                    {"id": ti.id, "deal_id": ti.deal_id,
                     "make": ti.make, "model": ti.model, "year": ti.year,
                     "status": ti.status.value, "appraised_value": ti.appraised_value}
                    for ti in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "test_drives":
                results = self.ctx.db.search_test_drives(sid, parsed)
                data = [
                    {"id": td.id, "customer_id": td.customer_id,
                     "vehicle_id": td.vehicle_id, "status": td.status.value,
                     "scheduled_time": td.scheduled_time}
                    for td in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "users":
                results = self.ctx.get_all_users()
                if "role" in parsed:
                    results = [u for u in results if u.role.value == parsed["role"]]
                data = [
                    {"id": u.id, "name": u.name, "role": u.role.value}
                    for u in results
                ]
                affs = compute_auto_affordances(self.ctx, sid)
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
        pre_affordances = compute_auto_affordances(self.ctx, sid)
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

            affs = compute_auto_affordances(self.ctx, sid)
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

            affs = compute_auto_affordances(self.ctx, sid)
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

            affs = compute_auto_affordances(self.ctx, sid)
            return json.dumps({
                "error": f"Runtime error: {e}",
                "affordances": _compact_affordances(affs),
            }, indent=2)

    def _dispatch(self, session_id, action, params, user):
        ctx = self.ctx
        engine = self.engine

        # --- Customer actions ---
        if action == "create_customer":
            customer, event = engine.create_customer(
                user,
                name=params["name"],
                email=params.get("email", ""),
                phone=params.get("phone", ""),
                drivers_license=params.get("drivers_license", ""),
                session_id=session_id,
            )
            customer = ctx.db.create_customer(customer)
            return {"message": f"Created customer '{customer.name}'", "customer_id": customer.id}, [event]

        elif action == "update_customer":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            fields = {k: v for k, v in params.items() if k != "customer_id" and v is not None}
            event = engine.update_customer(user, customer, **fields)
            ctx.db.update_customer(customer)
            return {"message": f"Updated customer '{customer.name}'"}, [event]

        # --- Test drive actions ---
        elif action == "schedule_test_drive":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            existing_drives = ctx.db.search_test_drives(session_id, {})
            test_drive, event = engine.schedule_test_drive(
                user, vehicle, customer,
                scheduled_time=params.get("scheduled_time", ""),
                salesperson_id=user.id,
                existing_drives=existing_drives,
            )
            test_drive = ctx.db.create_test_drive(test_drive)
            return {
                "message": f"Scheduled test drive '{test_drive.id}' for '{customer.name}'",
                "test_drive_id": test_drive.id,
            }, [event]

        elif action == "complete_test_drive":
            test_drive = ctx.db.get_test_drive(params["test_drive_id"])
            if not test_drive:
                raise DomainError(f"Test drive '{params['test_drive_id']}' not found.")
            event = engine.complete_test_drive(user, test_drive)
            ctx.db.update_test_drive(test_drive)
            return {"message": f"Completed test drive '{test_drive.id}'"}, [event]

        elif action == "cancel_test_drive":
            test_drive = ctx.db.get_test_drive(params["test_drive_id"])
            if not test_drive:
                raise DomainError(f"Test drive '{params['test_drive_id']}' not found.")
            event = engine.cancel_test_drive(user, test_drive)
            ctx.db.update_test_drive(test_drive)
            return {"message": f"Cancelled test drive '{test_drive.id}'"}, [event]

        # --- Deal actions ---
        elif action == "create_deal":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            deal, event = engine.create_deal(
                user, vehicle, customer,
                salesperson_id=user.id,
                session_id=session_id,
            )
            ctx.db.update_vehicle(vehicle)
            deal = ctx.db.create_deal(deal)
            return {"message": f"Created deal '{deal.id}'", "deal_id": deal.id}, [event]

        elif action == "mark_deal_lost":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            vehicle = ctx.db.get_vehicle(deal.vehicle_id)
            if not vehicle:
                raise DomainError(f"Vehicle '{deal.vehicle_id}' not found.")
            event = engine.mark_deal_lost(user, deal, vehicle)
            ctx.db.update_deal(deal)
            ctx.db.update_vehicle(vehicle)
            return {"message": f"Deal '{deal.id}' marked as lost"}, [event]

        elif action == "move_to_financing":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            offers = ctx.db.get_deal_offers(deal.id)
            has_accepted = any(o.status == OfferStatus.accepted for o in offers)
            event = engine.move_to_financing(user, deal, has_accepted)
            ctx.db.update_deal(deal)
            return {"message": f"Deal '{deal.id}' moved to financing"}, [event]

        elif action == "approve_deal":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            customer = ctx.db.get_customer(deal.customer_id)
            if not customer:
                raise DomainError(f"Customer '{deal.customer_id}' not found.")
            event = engine.approve_deal(user, deal, customer)
            ctx.db.update_deal(deal)
            return {"message": f"Deal '{deal.id}' approved"}, [event]

        elif action == "close_deal":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            vehicle = ctx.db.get_vehicle(deal.vehicle_id)
            if not vehicle:
                raise DomainError(f"Vehicle '{deal.vehicle_id}' not found.")
            offers = ctx.db.get_deal_offers(deal.id)
            accepted_offer = next(
                (o for o in offers if o.status == OfferStatus.accepted), None,
            )
            offer_amount = accepted_offer.amount if accepted_offer else 0.0
            down_payment = float(params.get("down_payment", 0.0))
            event = engine.close_deal(user, deal, vehicle, offer_amount, down_payment)
            ctx.db.update_deal(deal)
            ctx.db.update_vehicle(vehicle)
            return {"message": f"Deal '{deal.id}' closed at ${deal.final_price:.2f}"}, [event]

        # --- Offer actions ---
        elif action == "make_offer":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            existing_offers = ctx.db.get_deal_offers(deal.id)
            offer, event = engine.make_offer(
                user, deal,
                amount=float(params["amount"]),
                existing_pending_offers=existing_offers,
                offered_by=params.get("offered_by", "dealer"),
            )
            # Persist expired offers
            for o in existing_offers:
                if o.status == OfferStatus.expired:
                    ctx.db.update_offer(o)
            offer = ctx.db.create_offer(offer)
            return {"message": f"Made offer '{offer.id}' for ${offer.amount:.2f}", "offer_id": offer.id}, [event]

        elif action == "accept_offer":
            offer = ctx.db.get_offer(params["offer_id"])
            if not offer:
                raise DomainError(f"Offer '{params['offer_id']}' not found.")
            deal = ctx.db.get_deal(offer.deal_id)
            if not deal:
                raise DomainError(f"Deal '{offer.deal_id}' not found.")
            vehicle = ctx.db.get_vehicle(deal.vehicle_id)
            invoice_price = vehicle.invoice_price if vehicle else 0.0
            event = engine.accept_offer(user, deal, offer, invoice_price)
            ctx.db.update_offer(offer)
            return {"message": f"Accepted offer '{offer.id}' (${offer.amount:.2f})"}, [event]

        elif action == "reject_offer":
            offer = ctx.db.get_offer(params["offer_id"])
            if not offer:
                raise DomainError(f"Offer '{params['offer_id']}' not found.")
            event = engine.reject_offer(user, offer)
            ctx.db.update_offer(offer)
            return {"message": f"Rejected offer '{offer.id}'"}, [event]

        elif action == "counter_offer":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            pending = ctx.db.get_pending_offer(deal.id)
            if not pending:
                raise DomainError(f"No pending offer on deal '{deal.id}' to counter.")
            counter, event = engine.counter_offer(
                user, deal, pending,
                amount=float(params["amount"]),
                offered_by=params.get("offered_by", "dealer"),
            )
            ctx.db.update_offer(pending)
            counter = ctx.db.create_offer(counter)
            return {"message": f"Counter offer '{counter.id}' for ${counter.amount:.2f}", "offer_id": counter.id}, [event]

        # --- Trade-in actions ---
        elif action == "add_trade_in":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            trade_in, event = engine.add_trade_in(
                user, deal,
                customer_id=params.get("customer_id", deal.customer_id),
                make=params.get("make", ""),
                model=params.get("model", ""),
                year=int(params.get("year", 0)),
                vin=params.get("vin", ""),
                mileage=int(params.get("mileage", 0)),
                condition=params.get("condition", ""),
                session_id=session_id,
            )
            trade_in = ctx.db.create_trade_in(trade_in)
            return {"message": f"Added trade-in '{trade_in.id}'", "trade_in_id": trade_in.id}, [event]

        elif action == "appraise_trade_in":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.appraise_trade_in(
                user, trade_in,
                appraised_value=float(params["appraised_value"]),
            )
            ctx.db.update_trade_in(trade_in)
            return {"message": f"Appraised trade-in '{trade_in.id}' at ${trade_in.appraised_value:.2f}"}, [event]

        elif action == "accept_trade_in":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.accept_trade_in(user, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {"message": f"Accepted trade-in '{trade_in.id}'"}, [event]

        elif action == "decline_trade_in":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.decline_trade_in(user, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {"message": f"Declined trade-in '{trade_in.id}'"}, [event]

        elif action == "apply_trade_in_credit":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            deal = ctx.db.get_deal(trade_in.deal_id)
            if not deal:
                raise DomainError(f"Deal '{trade_in.deal_id}' not found.")
            event = engine.apply_trade_in_credit(user, deal, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {"message": f"Applied trade-in credit from '{trade_in.id}' (${trade_in.appraised_value:.2f})"}, [event]

        # --- Credit actions ---
        elif action == "submit_credit_app":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.submit_credit_app(
                user, customer,
                requested_amount=float(params.get("requested_amount", 0.0)),
            )
            ctx.db.update_customer(customer)
            return {"message": f"Submitted credit application for '{customer.name}'"}, [event]

        elif action == "approve_credit":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.approve_credit(
                user, customer,
                approved_amount=float(params.get("approved_amount", 0.0)),
            )
            ctx.db.update_customer(customer)
            return {"message": f"Approved credit for '{customer.name}'"}, [event]

        elif action == "deny_credit":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.deny_credit(user, customer)
            ctx.db.update_customer(customer)
            return {"message": f"Denied credit for '{customer.name}'"}, [event]

        else:
            raise DomainError(f"Unknown action: {action}")
