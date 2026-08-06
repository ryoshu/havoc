"""Oracle — deterministic success checker for automotive dealership eval tasks."""

from __future__ import annotations

from eval.auto_backend.context import AutoContext
from eval.auto_backend.models import (
    CreditStatus,
    DealStatus,
    OfferStatus,
    TestDriveStatus,
    TradeInStatus,
    VehicleStatus,
)


def check_auto_oracle(
    ctx: AutoContext,
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

        # vehicle_status: check vehicle state
        if check_type == "vehicle_status":
            vehicle_id = resolve_id(check["vehicle_id"])
            vehicle = ctx.db.get_vehicle(vehicle_id)
            if vehicle:
                expected = VehicleStatus(check["expected"])
                passed = vehicle.status == expected
                message = f"Vehicle '{vehicle_id}' status: {vehicle.status.value} (expected {expected.value})"
            else:
                message = f"Vehicle '{vehicle_id}' not found"

        # deal_status: check deal state
        elif check_type == "deal_status":
            deal_id = resolve_id(check["deal_id"])
            deal = ctx.db.get_deal(deal_id)
            if deal:
                expected = DealStatus(check["expected"])
                passed = deal.status == expected
                message = f"Deal '{deal_id}' status: {deal.status.value} (expected {expected.value})"
            else:
                message = f"Deal '{deal_id}' not found"

        # deal_exists: check deal exists with optional filters
        elif check_type == "deal_exists":
            deals = ctx.db.get_session_deals(session_id)
            if "customer_id" in check:
                cid = resolve_id(check["customer_id"])
                deals = [d for d in deals if d.customer_id == cid]
            if "vehicle_id" in check:
                vid = resolve_id(check["vehicle_id"])
                deals = [d for d in deals if d.vehicle_id == vid]
            if "status" in check:
                deals = [d for d in deals if d.status.value == check["status"]]
            passed = len(deals) > 0
            message = f"Deal exists matching filters: {passed} (found {len(deals)})"

        # offer_exists: check offer exists with optional filters
        elif check_type == "offer_exists":
            offers = ctx.db.get_session_offers(session_id)
            if "deal_id" in check:
                did = resolve_id(check["deal_id"])
                offers = [o for o in offers if o.deal_id == did]
            if "status" in check:
                offers = [o for o in offers if o.status.value == check["status"]]
            if "amount_gte" in check:
                offers = [o for o in offers if o.amount >= check["amount_gte"]]
            if "amount_lte" in check:
                offers = [o for o in offers if o.amount <= check["amount_lte"]]
            passed = len(offers) > 0
            message = f"Offer exists matching filters: {passed} (found {len(offers)})"

        # offer_status: specific offer status check
        elif check_type == "offer_status":
            offer_id = resolve_id(check["offer_id"])
            offer = ctx.db.get_offer(offer_id)
            if offer:
                expected = OfferStatus(check["expected"])
                passed = offer.status == expected
                message = f"Offer '{offer_id}' status: {offer.status.value} (expected {expected.value})"
            else:
                message = f"Offer '{offer_id}' not found"

        # offer_count: count offers on deal
        elif check_type == "offer_count":
            offers = ctx.db.get_session_offers(session_id)
            filters = check.get("filters", {})
            if "deal_id" in check:
                did = resolve_id(check["deal_id"])
                offers = [o for o in offers if o.deal_id == did]
            elif "deal_id" in filters:
                did = resolve_id(filters["deal_id"])
                offers = [o for o in offers if o.deal_id == did]
            if "status" in filters:
                offers = [o for o in offers if o.status.value == filters["status"]]
            op = check.get("op", "eq")
            expected = check["expected"]
            count = len(offers)
            if op == "eq":
                passed = count == expected
            elif op == "gte":
                passed = count >= expected
            elif op == "lte":
                passed = count <= expected
            message = f"Offer count ({op}): {count} vs {expected}"

        # trade_in_status: check trade-in status
        elif check_type == "trade_in_status":
            if "trade_in_id" in check:
                trade_in_id = resolve_id(check["trade_in_id"])
                trade_in = ctx.db.get_trade_in(trade_in_id)
                if trade_in:
                    expected = TradeInStatus(check["expected"])
                    passed = trade_in.status == expected
                    message = f"Trade-in '{trade_in_id}' status: {trade_in.status.value} (expected {expected.value})"
                else:
                    message = f"Trade-in '{trade_in_id}' not found"
            elif "deal_id" in check:
                did = resolve_id(check["deal_id"])
                trade_ins = ctx.db.get_session_trade_ins(session_id)
                trade_ins = [t for t in trade_ins if t.deal_id == did]
                if trade_ins:
                    expected = TradeInStatus(check["expected"])
                    passed = any(t.status == expected for t in trade_ins)
                    statuses = [t.status.value for t in trade_ins]
                    message = f"Trade-in on deal '{did}' statuses: {statuses} (expected {expected.value})"
                else:
                    message = f"No trade-ins found on deal '{did}'"

        # trade_in_value: check appraised value
        elif check_type == "trade_in_value":
            trade_in_id = resolve_id(check["trade_in_id"])
            trade_in = ctx.db.get_trade_in(trade_in_id)
            if trade_in:
                op = check.get("op", "eq")
                expected = check["expected"]
                actual = trade_in.appraised_value
                if op == "eq":
                    passed = actual == expected
                elif op == "gte":
                    passed = actual >= expected
                elif op == "lte":
                    passed = actual <= expected
                message = f"Trade-in '{trade_in_id}' value ({op}): {actual} vs {expected}"
            else:
                message = f"Trade-in '{trade_in_id}' not found"

        # credit_status: check customer credit status
        elif check_type == "credit_status":
            customer_id = resolve_id(check["customer_id"])
            customer = ctx.db.get_customer(customer_id)
            if customer:
                expected = CreditStatus(check["expected"])
                passed = customer.credit_status == expected
                message = f"Customer '{customer_id}' credit: {customer.credit_status.value} (expected {expected.value})"
            else:
                message = f"Customer '{customer_id}' not found"

        # test_drive_status: check test drive status
        elif check_type == "test_drive_status":
            test_drive_id = resolve_id(check["test_drive_id"])
            test_drive = ctx.db.get_test_drive(test_drive_id)
            if test_drive:
                expected = TestDriveStatus(check["expected"])
                passed = test_drive.status == expected
                message = f"Test drive '{test_drive_id}' status: {test_drive.status.value} (expected {expected.value})"
            else:
                message = f"Test drive '{test_drive_id}' not found"

        # test_drive_exists: check test drive exists with filters
        elif check_type == "test_drive_exists":
            test_drives = ctx.db.get_session_test_drives(session_id)
            if "customer_id" in check:
                cid = resolve_id(check["customer_id"])
                test_drives = [t for t in test_drives if t.customer_id == cid]
            if "vehicle_id" in check:
                vid = resolve_id(check["vehicle_id"])
                test_drives = [t for t in test_drives if t.vehicle_id == vid]
            if "status" in check:
                test_drives = [t for t in test_drives if t.status.value == check["status"]]
            passed = len(test_drives) > 0
            message = f"Test drive exists matching filters: {passed} (found {len(test_drives)})"

        # customer_exists: check customer exists with filters
        elif check_type == "customer_exists":
            customers = ctx.db.get_session_customers(session_id)
            if "name_contains" in check:
                needle = check["name_contains"].lower()
                customers = [c for c in customers if needle in c.name.lower()]
            if "email_contains" in check:
                needle = check["email_contains"].lower()
                customers = [c for c in customers if needle in c.email.lower()]
            passed = len(customers) > 0
            message = f"Customer exists matching filters: {passed} (found {len(customers)})"

        # deal_count: filtered count with operators
        elif check_type == "deal_count":
            deals = ctx.db.get_session_deals(session_id)
            filters = check.get("filters", {})
            if "status" in filters:
                deals = [d for d in deals if d.status.value == filters["status"]]
            if "customer_id" in filters:
                cid = resolve_id(filters["customer_id"])
                deals = [d for d in deals if d.customer_id == cid]
            if "vehicle_id" in filters:
                vid = resolve_id(filters["vehicle_id"])
                deals = [d for d in deals if d.vehicle_id == vid]
            op = check.get("op", "eq")
            expected = check["expected"]
            count = len(deals)
            if op == "eq":
                passed = count == expected
            elif op == "gte":
                passed = count >= expected
            elif op == "lte":
                passed = count <= expected
            message = f"Deal count ({op}): {count} vs {expected}"

        # no_backend_errors: no invalid decisions
        elif check_type == "no_backend_errors":
            decisions = ctx.db.get_session_decisions(session_id)
            invalid = [d for d in decisions if not d.was_valid]
            passed = len(invalid) == 0
            message = f"Backend errors: {len(invalid)}"

        # deal_final_price: check deal final price
        elif check_type == "deal_final_price":
            deal_id = resolve_id(check["deal_id"])
            deal = ctx.db.get_deal(deal_id)
            if deal:
                op = check.get("op", "eq")
                expected = check["expected"]
                actual = deal.final_price
                if op == "eq":
                    passed = actual == expected
                elif op == "gte":
                    passed = actual >= expected
                elif op == "lte":
                    passed = actual <= expected
                message = f"Deal '{deal_id}' final price ({op}): {actual} vs {expected}"
            else:
                message = f"Deal '{deal_id}' not found"

        else:
            message = f"Unknown check type: {check_type}"

        if not passed:
            all_passed = False
        details.append({"type": check_type, "passed": passed, "message": message})

    return all_passed, details
