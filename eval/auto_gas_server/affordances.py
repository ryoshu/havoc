"""Affordance layer — computes valid actions from user role and resource states for auto dealership domain."""

from __future__ import annotations

from eval.auto_backend.context import AutoContext
from eval.auto_backend.models import (
    AutoRole,
    CreditStatus,
    DealStatus,
    OfferStatus,
    TestDriveStatus,
    TradeInStatus,
    VehicleStatus,
)
from eval.backend.models import Affordance


def compute_auto_affordances(
    ctx: AutoContext,
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
    role = user.role
    is_receptionist = role == AutoRole.receptionist
    is_salesperson = role == AutoRole.salesperson
    is_finance = role == AutoRole.finance
    is_manager = role == AutoRole.manager
    is_sales_plus = role in (AutoRole.salesperson, AutoRole.manager)
    is_finance_plus = role in (AutoRole.finance, AutoRole.manager)

    vehicles = ctx.db.get_session_vehicles(session_id)
    customers = ctx.db.get_session_customers(session_id)
    deals = ctx.db.get_session_deals(session_id)
    test_drives = ctx.db.get_session_test_drives(session_id)

    all_user_ids = [u.id for u in ctx.get_all_users()]

    # --- Read actions (all roles) ---

    for v in vehicles:
        affordances.append(Affordance(
            action="get_vehicle",
            description=f"View vehicle '{v.year} {v.make} {v.model}' ({v.status.value})",
            schema={"vehicle_id": {"type": "string", "const": v.id}},
        ))

    for c in customers:
        affordances.append(Affordance(
            action="get_customer",
            description=f"View customer '{c.name}' (credit: {c.credit_status.value})",
            schema={"customer_id": {"type": "string", "const": c.id}},
        ))

    for d in deals:
        offers = ctx.db.get_deal_offers(d.id)
        trade_ins = ctx.db.get_deal_trade_ins(d.id)
        offer_summary = f"{len(offers)} offer(s)"
        trade_in_summary = f"{len(trade_ins)} trade-in(s)"
        affordances.append(Affordance(
            action="get_deal",
            description=f"View deal '{d.id}' ({d.status.value}, {offer_summary}, {trade_in_summary})",
            schema={"deal_id": {"type": "string", "const": d.id}},
        ))

    # Collect all offers and trade-ins across deals
    all_offers = []
    all_trade_ins = []
    for d in deals:
        all_offers.extend(ctx.db.get_deal_offers(d.id))
        all_trade_ins.extend(ctx.db.get_deal_trade_ins(d.id))

    for o in all_offers:
        affordances.append(Affordance(
            action="get_offer",
            description=f"View offer '{o.id}' (${o.amount:.0f}, {o.status.value})",
            schema={"offer_id": {"type": "string", "const": o.id}},
        ))

    for ti in all_trade_ins:
        affordances.append(Affordance(
            action="get_trade_in",
            description=f"View trade-in '{ti.id}' ({ti.year} {ti.make} {ti.model}, {ti.status.value})",
            schema={"trade_in_id": {"type": "string", "const": ti.id}},
        ))

    for td in test_drives:
        affordances.append(Affordance(
            action="get_test_drive",
            description=f"View test drive '{td.id}' ({td.status.value})",
            schema={"test_drive_id": {"type": "string", "const": td.id}},
        ))

    affordances.append(Affordance(
        action="search_vehicles",
        description="Search vehicles by status, make, model, year",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in VehicleStatus]},
                    "make": {"type": "string"},
                    "model": {"type": "string"},
                    "year": {"type": "number"},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_customers",
        description="Search customers by name, email, or credit_status",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "credit_status": {"type": "string", "enum": [s.value for s in CreditStatus]},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_deals",
        description="Search deals by status, customer_id, or vehicle_id",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in DealStatus]},
                    "customer_id": {"type": "string"},
                    "vehicle_id": {"type": "string"},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_offers",
        description="Search offers by deal_id or status",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "status": {"type": "string", "enum": [s.value for s in OfferStatus]},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_trade_ins",
        description="Search trade-ins by deal_id or status",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "status": {"type": "string", "enum": [s.value for s in TradeInStatus]},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_test_drives",
        description="Search test drives by customer_id, vehicle_id, or status",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "vehicle_id": {"type": "string"},
                    "status": {"type": "string", "enum": [s.value for s in TestDriveStatus]},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="get_user",
        description="View user details",
        schema={"user_id": {"type": "string", "enum": all_user_ids}},
    ))

    # --- Receptionist: limited write actions, then return early ---

    if is_receptionist:
        # create_customer
        affordances.append(Affordance(
            action="create_customer",
            description="Create a new customer record",
            schema={
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "drivers_license": {"type": "string"},
            },
        ))

        # schedule_test_drive (available/reserved vehicles, customer has license)
        for v in vehicles:
            if v.status not in (VehicleStatus.available, VehicleStatus.reserved):
                continue
            for c in customers:
                if not c.drivers_license:
                    affordances.append(Affordance(
                        action="schedule_test_drive",
                        description=f"Schedule test drive for '{c.name}' in '{v.year} {v.make} {v.model}' (BLOCKED: no license)",
                        schema={
                            "vehicle_id": {"type": "string", "const": v.id},
                            "customer_id": {"type": "string", "const": c.id},
                            "scheduled_time": {"type": "string"},
                        },
                        constraints=["Customer must have a driver's license on file."],
                    ))
                else:
                    affordances.append(Affordance(
                        action="schedule_test_drive",
                        description=f"Schedule test drive for '{c.name}' in '{v.year} {v.make} {v.model}'",
                        schema={
                            "vehicle_id": {"type": "string", "const": v.id},
                            "customer_id": {"type": "string", "const": c.id},
                            "scheduled_time": {"type": "string"},
                        },
                    ))

        # complete_test_drive, cancel_test_drive (scheduled only)
        for td in test_drives:
            if td.status == TestDriveStatus.scheduled:
                affordances.append(Affordance(
                    action="complete_test_drive",
                    description=f"Complete test drive '{td.id}'",
                    schema={"test_drive_id": {"type": "string", "const": td.id}},
                ))
                affordances.append(Affordance(
                    action="cancel_test_drive",
                    description=f"Cancel test drive '{td.id}'",
                    schema={"test_drive_id": {"type": "string", "const": td.id}},
                ))

        return affordances

    # --- Salesperson / Manager write actions ---

    if is_sales_plus:
        # create_customer
        affordances.append(Affordance(
            action="create_customer",
            description="Create a new customer record",
            schema={
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "drivers_license": {"type": "string"},
            },
        ))

        # schedule_test_drive (vehicle available/reserved, customer has license)
        for v in vehicles:
            if v.status not in (VehicleStatus.available, VehicleStatus.reserved):
                continue
            for c in customers:
                if not c.drivers_license:
                    affordances.append(Affordance(
                        action="schedule_test_drive",
                        description=f"Schedule test drive for '{c.name}' in '{v.year} {v.make} {v.model}' (BLOCKED: no license)",
                        schema={
                            "vehicle_id": {"type": "string", "const": v.id},
                            "customer_id": {"type": "string", "const": c.id},
                            "scheduled_time": {"type": "string"},
                        },
                        constraints=["Customer must have a driver's license on file."],
                    ))
                else:
                    affordances.append(Affordance(
                        action="schedule_test_drive",
                        description=f"Schedule test drive for '{c.name}' in '{v.year} {v.make} {v.model}'",
                        schema={
                            "vehicle_id": {"type": "string", "const": v.id},
                            "customer_id": {"type": "string", "const": c.id},
                            "scheduled_time": {"type": "string"},
                        },
                    ))

        # complete_test_drive, cancel_test_drive (scheduled only)
        for td in test_drives:
            if td.status == TestDriveStatus.scheduled:
                affordances.append(Affordance(
                    action="complete_test_drive",
                    description=f"Complete test drive '{td.id}'",
                    schema={"test_drive_id": {"type": "string", "const": td.id}},
                ))
                affordances.append(Affordance(
                    action="cancel_test_drive",
                    description=f"Cancel test drive '{td.id}'",
                    schema={"test_drive_id": {"type": "string", "const": td.id}},
                ))

        # create_deal (vehicle available only)
        for v in vehicles:
            if v.status == VehicleStatus.available:
                for c in customers:
                    affordances.append(Affordance(
                        action="create_deal",
                        description=f"Create deal for '{c.name}' on '{v.year} {v.make} {v.model}'",
                        schema={
                            "vehicle_id": {"type": "string", "const": v.id},
                            "customer_id": {"type": "string", "const": c.id},
                        },
                    ))

        for d in deals:
            offers = ctx.db.get_deal_offers(d.id)
            trade_ins = ctx.db.get_deal_trade_ins(d.id)
            vehicle = ctx.db.get_vehicle(d.vehicle_id)

            # mark_deal_lost (not closed/lost)
            if d.status not in (DealStatus.closed, DealStatus.lost):
                affordances.append(Affordance(
                    action="mark_deal_lost",
                    description=f"Mark deal '{d.id}' as lost",
                    schema={"deal_id": {"type": "string", "const": d.id}},
                ))

            # make_offer (deal negotiating)
            if d.status == DealStatus.negotiating:
                affordances.append(Affordance(
                    action="make_offer",
                    description=f"Make offer on deal '{d.id}'",
                    schema={
                        "deal_id": {"type": "string", "const": d.id},
                        "amount": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                ))

            # accept_offer (pending offers)
            pending_offers = [o for o in offers if o.status == OfferStatus.pending]
            for o in pending_offers:
                invoice_price = vehicle.invoice_price if vehicle else 0.0
                if o.amount < invoice_price:
                    affordances.append(Affordance(
                        action="accept_offer",
                        description=f"Accept offer '{o.id}' (${o.amount:.0f}) (BLOCKED: below invoice price ${invoice_price:.0f})",
                        schema={"offer_id": {"type": "string", "const": o.id}},
                        constraints=[f"Offer amount ${o.amount:.0f} is below invoice price ${invoice_price:.0f}."],
                    ))
                elif o.amount < 1.05 * invoice_price and not is_manager:
                    # C10: near floor price, manager only
                    affordances.append(Affordance(
                        action="accept_offer",
                        description=f"Accept offer '{o.id}' (${o.amount:.0f}) (BLOCKED: near floor price, manager approval required)",
                        schema={"offer_id": {"type": "string", "const": o.id}},
                        constraints=["Offer is within 5% of invoice price; only a manager can accept."],
                    ))
                else:
                    affordances.append(Affordance(
                        action="accept_offer",
                        description=f"Accept offer '{o.id}' (${o.amount:.0f})",
                        schema={"offer_id": {"type": "string", "const": o.id}},
                    ))

            # reject_offer (pending offers)
            for o in pending_offers:
                affordances.append(Affordance(
                    action="reject_offer",
                    description=f"Reject offer '{o.id}' (${o.amount:.0f})",
                    schema={"offer_id": {"type": "string", "const": o.id}},
                ))

            # counter_offer (deal negotiating, has pending offer)
            if d.status == DealStatus.negotiating and pending_offers:
                affordances.append(Affordance(
                    action="counter_offer",
                    description=f"Counter offer on deal '{d.id}'",
                    schema={
                        "deal_id": {"type": "string", "const": d.id},
                        "amount": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                ))

            # add_trade_in (deal negotiating or financing)
            if d.status in (DealStatus.negotiating, DealStatus.financing):
                affordances.append(Affordance(
                    action="add_trade_in",
                    description=f"Add trade-in to deal '{d.id}'",
                    schema={
                        "deal_id": {"type": "string", "const": d.id},
                        "customer_id": {"type": "string", "const": d.customer_id},
                        "make": {"type": "string"},
                        "model": {"type": "string"},
                        "year": {"type": "number"},
                        "vin": {"type": "string"},
                        "mileage": {"type": "number"},
                        "condition": {"type": "string"},
                    },
                ))

            # Trade-in operations
            for ti in trade_ins:
                # appraise_trade_in (pending_appraisal)
                if ti.status == TradeInStatus.pending_appraisal:
                    affordances.append(Affordance(
                        action="appraise_trade_in",
                        description=f"Appraise trade-in '{ti.id}' ({ti.year} {ti.make} {ti.model})",
                        schema={
                            "trade_in_id": {"type": "string", "const": ti.id},
                            "appraised_value": {"type": "number"},
                        },
                    ))

                # accept_trade_in, decline_trade_in (appraised)
                if ti.status == TradeInStatus.appraised:
                    affordances.append(Affordance(
                        action="accept_trade_in",
                        description=f"Accept trade-in '{ti.id}' (appraised at ${ti.appraised_value:.0f})",
                        schema={"trade_in_id": {"type": "string", "const": ti.id}},
                    ))
                    affordances.append(Affordance(
                        action="decline_trade_in",
                        description=f"Decline trade-in '{ti.id}'",
                        schema={"trade_in_id": {"type": "string", "const": ti.id}},
                    ))

                # apply_trade_in_credit (accepted, deal negotiating — C3)
                if ti.status == TradeInStatus.accepted and d.status == DealStatus.negotiating:
                    affordances.append(Affordance(
                        action="apply_trade_in_credit",
                        description=f"Apply trade-in credit from '{ti.id}' (${ti.appraised_value:.0f}) to deal '{d.id}'",
                        schema={"trade_in_id": {"type": "string", "const": ti.id}},
                    ))
                elif ti.status == TradeInStatus.accepted and d.status != DealStatus.negotiating:
                    affordances.append(Affordance(
                        action="apply_trade_in_credit",
                        description=f"Apply trade-in credit from '{ti.id}' to deal '{d.id}' (BLOCKED: deal not negotiating)",
                        schema={"trade_in_id": {"type": "string", "const": ti.id}},
                        constraints=[f"Deal must be in 'negotiating' status to apply trade-in credit (is '{d.status.value}')."],
                    ))

            # move_to_financing (deal negotiating, has accepted offer — C8)
            accepted_offers = [o for o in offers if o.status == OfferStatus.accepted]
            if d.status == DealStatus.negotiating:
                if accepted_offers:
                    affordances.append(Affordance(
                        action="move_to_financing",
                        description=f"Move deal '{d.id}' to financing",
                        schema={"deal_id": {"type": "string", "const": d.id}},
                    ))
                else:
                    affordances.append(Affordance(
                        action="move_to_financing",
                        description=f"Move deal '{d.id}' to financing (BLOCKED: no accepted offer)",
                        schema={"deal_id": {"type": "string", "const": d.id}},
                        constraints=["An accepted offer is required before moving to financing."],
                    ))

    # --- Finance / Manager actions ---

    if is_finance_plus:
        for c in customers:
            # submit_credit_app (credit_status not_started)
            if c.credit_status == CreditStatus.not_started:
                affordances.append(Affordance(
                    action="submit_credit_app",
                    description=f"Submit credit application for '{c.name}'",
                    schema={
                        "customer_id": {"type": "string", "const": c.id},
                        "requested_amount": {"type": "number"},
                    },
                ))

            # approve_credit (credit_status submitted)
            if c.credit_status == CreditStatus.submitted:
                affordances.append(Affordance(
                    action="approve_credit",
                    description=f"Approve credit for '{c.name}'",
                    schema={
                        "customer_id": {"type": "string", "const": c.id},
                        "approved_amount": {"type": "number"},
                    },
                ))
                affordances.append(Affordance(
                    action="deny_credit",
                    description=f"Deny credit for '{c.name}'",
                    schema={"customer_id": {"type": "string", "const": c.id}},
                ))

        for d in deals:
            customer = ctx.db.get_customer(d.customer_id)

            # approve_deal (deal financing, credit approved/conditional — C4)
            if d.status == DealStatus.financing:
                if customer and customer.credit_status in (CreditStatus.approved, CreditStatus.conditional):
                    affordances.append(Affordance(
                        action="approve_deal",
                        description=f"Approve deal '{d.id}'",
                        schema={"deal_id": {"type": "string", "const": d.id}},
                    ))
                else:
                    credit_st = customer.credit_status.value if customer else "unknown"
                    affordances.append(Affordance(
                        action="approve_deal",
                        description=f"Approve deal '{d.id}' (BLOCKED: credit not approved)",
                        schema={"deal_id": {"type": "string", "const": d.id}},
                        constraints=[f"Customer credit must be 'approved' or 'conditional' (is '{credit_st}')."],
                    ))

            # close_deal (deal approved)
            if d.status == DealStatus.approved:
                affordances.append(Affordance(
                    action="close_deal",
                    description=f"Close deal '{d.id}'",
                    schema={
                        "deal_id": {"type": "string", "const": d.id},
                        "down_payment": {"type": "number"},
                    },
                ))

    return affordances
