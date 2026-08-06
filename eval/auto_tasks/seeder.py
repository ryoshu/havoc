"""Seeder — populates AutoContext from a task's setup dict."""

from __future__ import annotations

from eval.auto_backend.context import AutoContext
from eval.auto_backend.models import (
    CustomerState,
    CreditStatus,
    DealState,
    DealStatus,
    OfferState,
    OfferStatus,
    TestDriveState,
    TestDriveStatus,
    TradeInState,
    TradeInStatus,
    VehicleState,
    VehicleStatus,
)


def seed_auto_task(ctx: AutoContext, session_id: str, setup: dict) -> dict:
    """Seed auto context from task setup. Returns alias->real ID map."""
    id_map: dict[str, str] = {}

    # Seed vehicles
    for veh_def in setup.get("vehicles", []):
        if "template_id" in veh_def:
            vehicle = ctx.create_vehicle_from_template(
                session_id,
                veh_def["template_id"],
                vehicle_id=veh_def.get("id", ""),
            )
        else:
            vehicle = VehicleState(
                session_id=session_id,
                make=veh_def.get("make", ""),
                model=veh_def.get("model", ""),
                year=veh_def.get("year", 0),
                trim=veh_def.get("trim", ""),
                vin=veh_def.get("vin", ""),
                color=veh_def.get("color", ""),
                msrp=veh_def.get("msrp", 0.0),
                invoice_price=veh_def.get("invoice_price", 0.0),
                mileage=veh_def.get("mileage", 0),
                condition=veh_def.get("condition", ""),
                status=VehicleStatus(veh_def.get("status", "available")),
            )
            if veh_def.get("id"):
                vehicle.id = veh_def["id"]
            vehicle = ctx.db.create_vehicle(vehicle)
        id_map[veh_def.get("alias", vehicle.id)] = vehicle.id
        if veh_def.get("template_id"):
            id_map[veh_def["template_id"]] = vehicle.id
        if veh_def.get("id"):
            id_map[veh_def["id"]] = vehicle.id

    # Seed customers
    for cust_def in setup.get("customers", []):
        customer = CustomerState(
            session_id=session_id,
            name=cust_def.get("name", ""),
            email=cust_def.get("email", ""),
            phone=cust_def.get("phone", ""),
            drivers_license=cust_def.get("drivers_license", ""),
            credit_score=cust_def.get("credit_score", 0),
            credit_status=CreditStatus(cust_def.get("credit_status", "not_started")),
            pre_approved_amount=cust_def.get("pre_approved_amount", 0.0),
        )
        if cust_def.get("id"):
            customer.id = cust_def["id"]
        customer = ctx.db.create_customer(customer)
        id_map[cust_def.get("alias", customer.id)] = customer.id
        if cust_def.get("id"):
            id_map[cust_def["id"]] = customer.id

    # Seed test drives
    for td_def in setup.get("test_drives", []):
        raw_customer = td_def.get("customer_alias") or td_def.get("customer_id", "")
        customer_id = id_map.get(raw_customer, raw_customer)
        raw_vehicle = td_def.get("vehicle_alias") or td_def.get("vehicle_id", "")
        vehicle_id = id_map.get(raw_vehicle, raw_vehicle)
        test_drive = TestDriveState(
            session_id=session_id,
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            scheduled_time=td_def.get("scheduled_time", ""),
            duration_minutes=td_def.get("duration_minutes", 30),
            salesperson_id=td_def.get("salesperson_id", ""),
            status=TestDriveStatus(td_def.get("status", "scheduled")),
            notes=td_def.get("notes", ""),
        )
        if td_def.get("id"):
            test_drive.id = td_def["id"]
        test_drive = ctx.db.create_test_drive(test_drive)
        id_map[td_def.get("alias", test_drive.id)] = test_drive.id
        if td_def.get("id"):
            id_map[td_def["id"]] = test_drive.id

    # Seed deals
    for deal_def in setup.get("deals", []):
        raw_customer = deal_def.get("customer_alias") or deal_def.get("customer_id", "")
        customer_id = id_map.get(raw_customer, raw_customer)
        raw_vehicle = deal_def.get("vehicle_alias") or deal_def.get("vehicle_id", "")
        vehicle_id = id_map.get(raw_vehicle, raw_vehicle)
        deal = DealState(
            session_id=session_id,
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            salesperson_id=deal_def.get("salesperson_id", ""),
            status=DealStatus(deal_def.get("status", "negotiating")),
            final_price=deal_def.get("final_price", 0.0),
            financing_amount=deal_def.get("financing_amount", 0.0),
            down_payment=deal_def.get("down_payment", 0.0),
        )
        if deal_def.get("id"):
            deal.id = deal_def["id"]
        deal = ctx.db.create_deal(deal)
        id_map[deal_def.get("alias", deal.id)] = deal.id
        if deal_def.get("id"):
            id_map[deal_def["id"]] = deal.id

    # Seed offers
    for off_def in setup.get("offers", []):
        raw_deal = off_def.get("deal_alias") or off_def.get("deal_id", "")
        deal_id = id_map.get(raw_deal, raw_deal)
        offer = OfferState(
            session_id=session_id,
            deal_id=deal_id,
            amount=off_def.get("amount", 0.0),
            offered_by=off_def.get("offered_by", ""),
            status=OfferStatus(off_def.get("status", "pending")),
            trade_in_credit=off_def.get("trade_in_credit", 0.0),
            notes=off_def.get("notes", ""),
        )
        if off_def.get("id"):
            offer.id = off_def["id"]
        offer = ctx.db.create_offer(offer)
        id_map[off_def.get("alias", offer.id)] = offer.id
        if off_def.get("id"):
            id_map[off_def["id"]] = offer.id

    # Seed trade-ins
    for ti_def in setup.get("trade_ins", []):
        raw_deal = ti_def.get("deal_alias") or ti_def.get("deal_id", "")
        deal_id = id_map.get(raw_deal, raw_deal)
        raw_customer = ti_def.get("customer_alias") or ti_def.get("customer_id", "")
        customer_id = id_map.get(raw_customer, raw_customer)
        trade_in = TradeInState(
            session_id=session_id,
            deal_id=deal_id,
            customer_id=customer_id,
            make=ti_def.get("make", ""),
            model=ti_def.get("model", ""),
            year=ti_def.get("year", 0),
            vin=ti_def.get("vin", ""),
            mileage=ti_def.get("mileage", 0),
            condition=ti_def.get("condition", ""),
            appraised_value=ti_def.get("appraised_value", 0.0),
            status=TradeInStatus(ti_def.get("status", "pending_appraisal")),
        )
        if ti_def.get("id"):
            trade_in.id = ti_def["id"]
        trade_in = ctx.db.create_trade_in(trade_in)
        id_map[ti_def.get("alias", trade_in.id)] = trade_in.id
        if ti_def.get("id"):
            id_map[ti_def["id"]] = trade_in.id

    return id_map
