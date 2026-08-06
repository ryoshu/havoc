"""Traditional server — N individual tools, no affordances, for automotive dealership eval."""

from __future__ import annotations

import json
from datetime import datetime

from eval.auto_backend.context import AutoContext
from eval.auto_backend.domain import AutoEngine
from eval.auto_backend.models import (
    DealStatus,
    OfferStatus,
    TestDriveStatus,
    TradeInStatus,
    VehicleStatus,
)
from eval.backend.domain import DomainError
from eval.backend.models import DecisionRecord, DomainEvent

from .tools_15 import AUTO_TOOLS_15
from .tools_30 import AUTO_TOOLS_30
from .tools_60 import AUTO_TOOLS_60

AUTO_TOOL_LEVELS: dict[int | str, list[dict]] = {
    15: AUTO_TOOLS_15,
    30: AUTO_TOOLS_30,
    60: AUTO_TOOLS_60,
}


class AutoTradRuntime:
    """Traditional runtime — one tool per operation, no affordances."""

    def __init__(self, db_path: str = ":memory:", tool_level: int | str = 15):
        self.ctx = AutoContext(db_path=db_path)
        self.engine = AutoEngine()
        self.tool_level = tool_level
        self.tools = AUTO_TOOL_LEVELS[tool_level]
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
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, session_id, tool_name, params, user):  # noqa: C901
        ctx = self.ctx
        engine = self.engine
        events: list[DomainEvent] = []

        # =====================================================================
        # 15-level core tools
        # =====================================================================

        if tool_name == "get_vehicle":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            return vehicle.model_dump(), []

        elif tool_name == "create_customer":
            customer, event = engine.create_customer(
                user,
                params["name"], params["email"],
                params["phone"], params["drivers_license"],
                session_id,
            )
            customer = ctx.db.create_customer(customer)
            return {
                "message": f"Created customer '{customer.name}'",
                "customer_id": customer.id,
            }, [event]

        elif tool_name == "schedule_test_drive":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            existing = ctx.db.search_test_drives(session_id, {})
            td, event = engine.schedule_test_drive(
                user, vehicle, customer,
                params["scheduled_time"], user.id, existing,
            )
            td = ctx.db.create_test_drive(td)
            return {
                "message": f"Scheduled test drive '{td.id}'",
                "test_drive_id": td.id,
            }, [event]

        elif tool_name == "create_deal":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            deal, event = engine.create_deal(
                user, vehicle, customer, user.id, session_id,
            )
            ctx.db.update_vehicle(vehicle)
            deal = ctx.db.create_deal(deal)
            return {
                "message": f"Created deal '{deal.id}'",
                "deal_id": deal.id,
            }, [event]

        elif tool_name == "make_offer":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            existing_offers = ctx.db.get_deal_offers(deal.id)
            offer, event = engine.make_offer(
                user, deal, float(params["amount"]), existing_offers,
            )
            # Persist expired offers
            for o in existing_offers:
                if o.status == OfferStatus.expired:
                    ctx.db.update_offer(o)
            offer = ctx.db.create_offer(offer)
            return {
                "message": f"Made offer '{offer.id}' for ${offer.amount:.2f}",
                "offer_id": offer.id,
            }, [event]

        elif tool_name == "accept_offer":
            offer = ctx.db.get_offer(params["offer_id"])
            if not offer:
                raise DomainError(f"Offer '{params['offer_id']}' not found.")
            deal = ctx.db.get_deal(offer.deal_id)
            if not deal:
                raise DomainError(f"Deal '{offer.deal_id}' not found.")
            vehicle = ctx.db.get_vehicle(deal.vehicle_id)
            if not vehicle:
                raise DomainError(f"Vehicle '{deal.vehicle_id}' not found.")
            event = engine.accept_offer(user, deal, offer, vehicle.invoice_price)
            ctx.db.update_offer(offer)
            return {"message": f"Accepted offer '{offer.id}'"}, [event]

        elif tool_name == "reject_offer":
            offer = ctx.db.get_offer(params["offer_id"])
            if not offer:
                raise DomainError(f"Offer '{params['offer_id']}' not found.")
            event = engine.reject_offer(user, offer)
            ctx.db.update_offer(offer)
            return {"message": f"Rejected offer '{offer.id}'"}, [event]

        elif tool_name == "add_trade_in":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            trade_in, event = engine.add_trade_in(
                user, deal, deal.customer_id,
                params["make"], params["model"], int(params["year"]),
                params["vin"], int(params["mileage"]), params["condition"],
                session_id,
            )
            trade_in = ctx.db.create_trade_in(trade_in)
            return {
                "message": f"Added trade-in '{trade_in.id}'",
                "trade_in_id": trade_in.id,
            }, [event]

        elif tool_name == "appraise_trade_in":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.appraise_trade_in(
                user, trade_in, float(params["appraised_value"]),
            )
            ctx.db.update_trade_in(trade_in)
            return {
                "message": f"Appraised trade-in '{trade_in.id}' at ${trade_in.appraised_value:.2f}",
            }, [event]

        elif tool_name == "submit_credit_app":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.submit_credit_app(
                user, customer, float(params["requested_amount"]),
            )
            ctx.db.update_customer(customer)
            return {"message": f"Submitted credit application for '{customer.name}'"}, [event]

        elif tool_name == "close_deal":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            vehicle = ctx.db.get_vehicle(deal.vehicle_id)
            if not vehicle:
                raise DomainError(f"Vehicle '{deal.vehicle_id}' not found.")
            # Find accepted offer amount
            offers = ctx.db.get_deal_offers(deal.id)
            accepted = [o for o in offers if o.status == OfferStatus.accepted]
            if not accepted:
                raise DomainError(f"Deal '{deal.id}' has no accepted offer.")
            accepted_amount = accepted[-1].amount
            event = engine.close_deal(
                user, deal, vehicle, accepted_amount, float(params["down_payment"]),
            )
            ctx.db.update_deal(deal)
            ctx.db.update_vehicle(vehicle)
            return {"message": f"Closed deal '{deal.id}'"}, [event]

        elif tool_name == "search_vehicles":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_vehicles(session_id, filters)
            return {"vehicles": [
                {"id": v.id, "make": v.make, "model": v.model, "year": v.year,
                 "trim": v.trim, "msrp": v.msrp, "condition": v.condition,
                 "status": v.status.value}
                for v in results
            ]}, []

        elif tool_name == "search_deals":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_deals(session_id, filters)
            return {"deals": [
                {"id": d.id, "customer_id": d.customer_id, "vehicle_id": d.vehicle_id,
                 "status": d.status.value, "final_price": d.final_price}
                for d in results
            ]}, []

        elif tool_name == "get_deal":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            offers = ctx.db.get_deal_offers(deal.id)
            trade_ins = ctx.db.get_deal_trade_ins(deal.id)
            return {
                **deal.model_dump(),
                "offers": [o.model_dump() for o in offers],
                "trade_ins": [t.model_dump() for t in trade_ins],
            }, []

        elif tool_name == "mark_deal_lost":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            vehicle = ctx.db.get_vehicle(deal.vehicle_id)
            if not vehicle:
                raise DomainError(f"Vehicle '{deal.vehicle_id}' not found.")
            event = engine.mark_deal_lost(user, deal, vehicle)
            ctx.db.update_deal(deal)
            ctx.db.update_vehicle(vehicle)
            return {"message": f"Marked deal '{deal.id}' as lost"}, [event]

        # =====================================================================
        # 30-level extra tools
        # =====================================================================

        elif tool_name == "get_customer":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            return customer.model_dump(), []

        elif tool_name == "update_customer":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            fields = {}
            for key in ("phone", "email", "drivers_license"):
                if key in params and params[key]:
                    fields[key] = params[key]
            if not fields:
                raise DomainError("No fields provided for update.")
            event = engine.update_customer(user, customer, **fields)
            ctx.db.update_customer(customer)
            return {"message": f"Updated customer '{customer.name}'"}, [event]

        elif tool_name == "counter_offer":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            pending = ctx.db.get_pending_offer(deal.id)
            if not pending:
                raise DomainError(f"No pending offer on deal '{deal.id}' to counter.")
            new_offer, event = engine.counter_offer(
                user, deal, pending, float(params["amount"]),
            )
            ctx.db.update_offer(pending)
            new_offer = ctx.db.create_offer(new_offer)
            return {
                "message": f"Countered with offer '{new_offer.id}' for ${new_offer.amount:.2f}",
                "offer_id": new_offer.id,
            }, [event]

        elif tool_name == "accept_trade_in":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.accept_trade_in(user, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {"message": f"Accepted trade-in '{trade_in.id}'"}, [event]

        elif tool_name == "decline_trade_in":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.decline_trade_in(user, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {"message": f"Declined trade-in '{trade_in.id}'"}, [event]

        elif tool_name == "apply_trade_in_credit":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            event = engine.apply_trade_in_credit(user, deal, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {
                "message": f"Applied trade-in credit of ${trade_in.appraised_value:.2f} to deal '{deal.id}'",
            }, [event]

        elif tool_name == "approve_credit":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.approve_credit(
                user, customer, float(params["approved_amount"]),
            )
            ctx.db.update_customer(customer)
            return {
                "message": f"Approved credit for '{customer.name}' at ${customer.pre_approved_amount:.2f}",
            }, [event]

        elif tool_name == "deny_credit":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.deny_credit(user, customer)
            ctx.db.update_customer(customer)
            return {"message": f"Denied credit for '{customer.name}'"}, [event]

        elif tool_name == "move_to_financing":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            offers = ctx.db.get_deal_offers(deal.id)
            has_accepted = any(o.status == OfferStatus.accepted for o in offers)
            event = engine.move_to_financing(user, deal, has_accepted)
            ctx.db.update_deal(deal)
            return {"message": f"Moved deal '{deal.id}' to financing"}, [event]

        elif tool_name == "approve_deal":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            customer = ctx.db.get_customer(deal.customer_id)
            if not customer:
                raise DomainError(f"Customer '{deal.customer_id}' not found.")
            event = engine.approve_deal(user, deal, customer)
            ctx.db.update_deal(deal)
            return {"message": f"Approved deal '{deal.id}'"}, [event]

        elif tool_name == "complete_test_drive":
            td = ctx.db.get_test_drive(params["test_drive_id"])
            if not td:
                raise DomainError(f"Test drive '{params['test_drive_id']}' not found.")
            event = engine.complete_test_drive(user, td)
            ctx.db.update_test_drive(td)
            return {"message": f"Completed test drive '{td.id}'"}, [event]

        elif tool_name == "cancel_test_drive":
            td = ctx.db.get_test_drive(params["test_drive_id"])
            if not td:
                raise DomainError(f"Test drive '{params['test_drive_id']}' not found.")
            event = engine.cancel_test_drive(user, td)
            ctx.db.update_test_drive(td)
            return {"message": f"Cancelled test drive '{td.id}'"}, [event]

        elif tool_name == "get_test_drive":
            td = ctx.db.get_test_drive(params["test_drive_id"])
            if not td:
                raise DomainError(f"Test drive '{params['test_drive_id']}' not found.")
            return td.model_dump(), []

        elif tool_name == "search_test_drives":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_test_drives(session_id, filters)
            return {"test_drives": [
                {"id": t.id, "customer_id": t.customer_id, "vehicle_id": t.vehicle_id,
                 "scheduled_time": t.scheduled_time, "status": t.status.value}
                for t in results
            ]}, []

        elif tool_name == "get_user":
            u = ctx.get_user(params["user_id"])
            if not u:
                raise DomainError(f"User '{params['user_id']}' not found.")
            return u.model_dump(), []

        # =====================================================================
        # 60-level extra tools
        # =====================================================================

        # --- Per-field customer updates (31-35) ---

        elif tool_name == "set_customer_phone":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.update_customer(user, customer, phone=params["phone"])
            ctx.db.update_customer(customer)
            return {"message": "Updated customer phone"}, [event]

        elif tool_name == "set_customer_email":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.update_customer(user, customer, email=params["email"])
            ctx.db.update_customer(customer)
            return {"message": "Updated customer email"}, [event]

        elif tool_name == "set_customer_license":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.update_customer(user, customer, drivers_license=params["drivers_license"])
            ctx.db.update_customer(customer)
            return {"message": "Updated customer driver's license"}, [event]

        elif tool_name == "set_customer_name":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            event = engine.update_customer(user, customer, name=params["name"])
            ctx.db.update_customer(customer)
            return {"message": "Updated customer name"}, [event]

        elif tool_name == "get_customer_credit_status":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            return {
                "customer_id": customer.id,
                "name": customer.name,
                "credit_status": customer.credit_status.value,
                "pre_approved_amount": customer.pre_approved_amount,
            }, []

        # --- Granular searches (36-40) ---

        elif tool_name == "search_vehicles_by_make":
            results = ctx.db.search_vehicles(session_id, {"make": params["make"]})
            return {"vehicles": [
                {"id": v.id, "make": v.make, "model": v.model, "year": v.year,
                 "msrp": v.msrp, "status": v.status.value}
                for v in results
            ]}, []

        elif tool_name == "search_vehicles_by_price_range":
            results = ctx.db.search_vehicles(session_id, {
                "min_price": float(params["min_price"]),
                "max_price": float(params["max_price"]),
            })
            return {"vehicles": [
                {"id": v.id, "make": v.make, "model": v.model, "year": v.year,
                 "msrp": v.msrp, "status": v.status.value}
                for v in results
            ]}, []

        elif tool_name == "search_deals_by_status":
            results = ctx.db.search_deals(session_id, {"status": params["status"]})
            return {"deals": [
                {"id": d.id, "customer_id": d.customer_id, "vehicle_id": d.vehicle_id,
                 "status": d.status.value}
                for d in results
            ]}, []

        elif tool_name == "search_test_drives_by_customer":
            results = ctx.db.search_test_drives(session_id, {"customer_id": params["customer_id"]})
            return {"test_drives": [
                {"id": t.id, "vehicle_id": t.vehicle_id, "scheduled_time": t.scheduled_time,
                 "status": t.status.value}
                for t in results
            ]}, []

        elif tool_name == "search_test_drives_by_vehicle":
            results = ctx.db.search_test_drives(session_id, {"vehicle_id": params["vehicle_id"]})
            return {"test_drives": [
                {"id": t.id, "customer_id": t.customer_id, "scheduled_time": t.scheduled_time,
                 "status": t.status.value}
                for t in results
            ]}, []

        # --- Analytics (41-45) ---

        elif tool_name == "get_deal_history":
            decisions = ctx.db.get_session_decisions(session_id)
            deal_decisions = [
                d for d in decisions
                if d.params.get("deal_id") == params["deal_id"]
                or params["deal_id"] in str(d.params)
            ]
            return {"history": [
                {"action": d.action, "by": d.actor_name, "at": d.timestamp,
                 "valid": d.was_valid, "summary": d.result_summary}
                for d in deal_decisions
            ]}, []

        elif tool_name == "get_vehicle_test_drive_history":
            results = ctx.db.search_test_drives(session_id, {"vehicle_id": params["vehicle_id"]})
            return {"test_drives": [
                {"id": t.id, "customer_id": t.customer_id, "scheduled_time": t.scheduled_time,
                 "status": t.status.value, "notes": t.notes}
                for t in results
            ]}, []

        elif tool_name == "get_customer_deals":
            results = ctx.db.search_deals(session_id, {"customer_id": params["customer_id"]})
            return {"deals": [
                {"id": d.id, "vehicle_id": d.vehicle_id, "status": d.status.value,
                 "final_price": d.final_price}
                for d in results
            ]}, []

        elif tool_name == "get_inventory_summary":
            vehicles = ctx.db.get_session_vehicles(session_id)
            by_status: dict[str, int] = {}
            by_condition: dict[str, int] = {}
            total_msrp = 0.0
            for v in vehicles:
                by_status.setdefault(v.status.value, 0)
                by_status[v.status.value] += 1
                by_condition.setdefault(v.condition, 0)
                by_condition[v.condition] += 1
                total_msrp += v.msrp
            return {
                "total_vehicles": len(vehicles),
                "by_status": by_status,
                "by_condition": by_condition,
                "average_msrp": total_msrp / len(vehicles) if vehicles else 0.0,
            }, []

        elif tool_name == "get_deal_offers":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            offers = ctx.db.get_deal_offers(deal.id)
            return {"offers": [o.model_dump() for o in offers]}, []

        # --- Workflow shortcuts (46-50) ---

        elif tool_name == "create_deal_and_offer":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            deal, evt_deal = engine.create_deal(
                user, vehicle, customer, user.id, session_id,
            )
            ctx.db.update_vehicle(vehicle)
            deal = ctx.db.create_deal(deal)
            existing_offers = ctx.db.get_deal_offers(deal.id)
            offer, evt_offer = engine.make_offer(
                user, deal, float(params["amount"]), existing_offers,
            )
            offer = ctx.db.create_offer(offer)
            return {
                "message": f"Created deal '{deal.id}' with offer '{offer.id}'",
                "deal_id": deal.id,
                "offer_id": offer.id,
            }, [evt_deal, evt_offer]

        elif tool_name == "schedule_and_complete_test_drive":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            existing = ctx.db.search_test_drives(session_id, {})
            td, evt_sched = engine.schedule_test_drive(
                user, vehicle, customer,
                params["scheduled_time"], user.id, existing,
            )
            td = ctx.db.create_test_drive(td)
            evt_complete = engine.complete_test_drive(user, td)
            ctx.db.update_test_drive(td)
            return {
                "message": f"Scheduled and completed test drive '{td.id}'",
                "test_drive_id": td.id,
            }, [evt_sched, evt_complete]

        elif tool_name == "full_trade_in_flow":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            trade_in, evt_add = engine.add_trade_in(
                user, deal, deal.customer_id,
                params["make"], params["model"], int(params["year"]),
                params["vin"], int(params["mileage"]), params["condition"],
                session_id,
            )
            trade_in = ctx.db.create_trade_in(trade_in)
            evt_appraise = engine.appraise_trade_in(
                user, trade_in, float(params["appraised_value"]),
            )
            ctx.db.update_trade_in(trade_in)
            evt_accept = engine.accept_trade_in(user, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {
                "message": f"Added, appraised (${trade_in.appraised_value:.2f}), and accepted trade-in '{trade_in.id}'",
                "trade_in_id": trade_in.id,
            }, [evt_add, evt_appraise, evt_accept]

        elif tool_name == "submit_and_approve_credit":
            customer = ctx.db.get_customer(params["customer_id"])
            if not customer:
                raise DomainError(f"Customer '{params['customer_id']}' not found.")
            evt_submit = engine.submit_credit_app(
                user, customer, float(params["requested_amount"]),
            )
            ctx.db.update_customer(customer)
            evt_approve = engine.approve_credit(
                user, customer, float(params["approved_amount"]),
            )
            ctx.db.update_customer(customer)
            return {
                "message": f"Submitted and approved credit for '{customer.name}' at ${customer.pre_approved_amount:.2f}",
            }, [evt_submit, evt_approve]

        elif tool_name == "accept_and_apply_trade_in":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            evt_accept = engine.accept_trade_in(user, trade_in)
            ctx.db.update_trade_in(trade_in)
            evt_apply = engine.apply_trade_in_credit(user, deal, trade_in)
            ctx.db.update_trade_in(trade_in)
            return {
                "message": f"Accepted and applied trade-in '{trade_in.id}' credit of ${trade_in.appraised_value:.2f}",
            }, [evt_accept, evt_apply]

        # --- Cross-entity queries (51-55) ---

        elif tool_name == "get_vehicle_deal":
            deal = ctx.db.get_vehicle_active_deal(session_id, params["vehicle_id"])
            if not deal:
                return {"message": f"No active deal for vehicle '{params['vehicle_id']}'"}, []
            return deal.model_dump(), []

        elif tool_name == "get_deal_trade_ins":
            deal = ctx.db.get_deal(params["deal_id"])
            if not deal:
                raise DomainError(f"Deal '{params['deal_id']}' not found.")
            trade_ins = ctx.db.get_deal_trade_ins(deal.id)
            return {"trade_ins": [t.model_dump() for t in trade_ins]}, []

        elif tool_name == "get_customer_test_drives":
            results = ctx.db.search_test_drives(session_id, {"customer_id": params["customer_id"]})
            return {"test_drives": [
                {"id": t.id, "vehicle_id": t.vehicle_id, "scheduled_time": t.scheduled_time,
                 "status": t.status.value}
                for t in results
            ]}, []

        elif tool_name == "get_offer_details":
            offer = ctx.db.get_offer(params["offer_id"])
            if not offer:
                raise DomainError(f"Offer '{params['offer_id']}' not found.")
            return offer.model_dump(), []

        elif tool_name == "get_trade_in_details":
            trade_in = ctx.db.get_trade_in(params["trade_in_id"])
            if not trade_in:
                raise DomainError(f"Trade-in '{params['trade_in_id']}' not found.")
            return trade_in.model_dump(), []

        # --- Bulk ops (56-58) ---

        elif tool_name == "bulk_mark_lost":
            evts = []
            for did in params["deal_ids"]:
                deal = ctx.db.get_deal(did)
                if not deal:
                    continue
                vehicle = ctx.db.get_vehicle(deal.vehicle_id)
                if not vehicle:
                    continue
                try:
                    evt = engine.mark_deal_lost(user, deal, vehicle)
                    ctx.db.update_deal(deal)
                    ctx.db.update_vehicle(vehicle)
                    evts.append(evt)
                except DomainError:
                    continue
            return {"message": f"Bulk marked {len(evts)} deals as lost"}, evts

        elif tool_name == "bulk_cancel_test_drives":
            evts = []
            for tid in params["test_drive_ids"]:
                td = ctx.db.get_test_drive(tid)
                if not td:
                    continue
                try:
                    evt = engine.cancel_test_drive(user, td)
                    ctx.db.update_test_drive(td)
                    evts.append(evt)
                except DomainError:
                    continue
            return {"message": f"Bulk cancelled {len(evts)} test drives"}, evts

        elif tool_name == "count_available_vehicles":
            filters: dict = {"status": VehicleStatus.available.value}
            if "make" in params and params["make"]:
                filters["make"] = params["make"]
            if "condition" in params and params["condition"]:
                filters["condition"] = params["condition"]
            results = ctx.db.search_vehicles(session_id, filters)
            return {"count": len(results)}, []

        # --- Status checks (59-60) ---

        elif tool_name == "check_test_drive_availability":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            if vehicle.status not in (VehicleStatus.available, VehicleStatus.reserved):
                return {
                    "vehicle_id": vehicle.id,
                    "available": False,
                    "reason": f"Vehicle is '{vehicle.status.value}'",
                }, []
            existing = ctx.db.search_test_drives(session_id, {"vehicle_id": vehicle.id})
            scheduled_time = params["scheduled_time"]
            try:
                new_time = datetime.fromisoformat(scheduled_time)
            except ValueError:
                raise DomainError(f"Invalid scheduled_time format: '{scheduled_time}'.")
            for td in existing:
                if td.status != TestDriveStatus.scheduled:
                    continue
                try:
                    existing_time = datetime.fromisoformat(td.scheduled_time)
                except ValueError:
                    continue
                diff_minutes = abs((new_time - existing_time).total_seconds()) / 60
                if diff_minutes < td.duration_minutes:
                    return {
                        "vehicle_id": vehicle.id,
                        "available": False,
                        "reason": f"Conflicts with test drive '{td.id}' at {td.scheduled_time}",
                    }, []
            return {
                "vehicle_id": vehicle.id,
                "available": True,
                "scheduled_time": scheduled_time,
            }, []

        elif tool_name == "check_vehicle_availability":
            vehicle = ctx.db.get_vehicle(params["vehicle_id"])
            if not vehicle:
                raise DomainError(f"Vehicle '{params['vehicle_id']}' not found.")
            return {
                "vehicle_id": vehicle.id,
                "make": vehicle.make,
                "model": vehicle.model,
                "status": vehicle.status.value,
                "available_for_sale": vehicle.status == VehicleStatus.available,
            }, []

        else:
            raise DomainError(f"Tool '{tool_name}' not implemented.")
