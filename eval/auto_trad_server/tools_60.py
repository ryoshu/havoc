"""60 tools — extends 30 with per-field updates, analytics, bulk ops, granular search."""

from __future__ import annotations

from .tools_30 import AUTO_TOOLS_30

AUTO_TOOLS_60_EXTRA = [
    # --- 31-35: Per-field customer updates ---
    {"name": "set_customer_phone", "description": "Set customer phone number.", "parameters": {"customer_id": {"type": "string"}, "phone": {"type": "string"}}, "required": ["customer_id", "phone"]},
    {"name": "set_customer_email", "description": "Set customer email address.", "parameters": {"customer_id": {"type": "string"}, "email": {"type": "string"}}, "required": ["customer_id", "email"]},
    {"name": "set_customer_license", "description": "Set customer driver's license number.", "parameters": {"customer_id": {"type": "string"}, "drivers_license": {"type": "string"}}, "required": ["customer_id", "drivers_license"]},
    {"name": "set_customer_name", "description": "Set customer name.", "parameters": {"customer_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["customer_id", "name"]},
    {"name": "get_customer_credit_status", "description": "Get just the credit status and pre-approved amount for a customer.", "parameters": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},

    # --- 36-40: Granular searches ---
    {"name": "search_vehicles_by_make", "description": "Find all vehicles of a specific make.", "parameters": {"make": {"type": "string"}}, "required": ["make"]},
    {"name": "search_vehicles_by_price_range", "description": "Find vehicles within a price range.", "parameters": {"min_price": {"type": "number"}, "max_price": {"type": "number"}}, "required": ["min_price", "max_price"]},
    {"name": "search_deals_by_status", "description": "Find all deals with a specific status.", "parameters": {"status": {"type": "string", "enum": ["negotiating", "financing", "approved", "closed", "lost"]}}, "required": ["status"]},
    {"name": "search_test_drives_by_customer", "description": "Find all test drives for a specific customer.", "parameters": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
    {"name": "search_test_drives_by_vehicle", "description": "Find all test drives for a specific vehicle.", "parameters": {"vehicle_id": {"type": "string"}}, "required": ["vehicle_id"]},

    # --- 41-45: Analytics ---
    {"name": "get_deal_history", "description": "Get the full decision/action history for a deal.", "parameters": {"deal_id": {"type": "string"}}, "required": ["deal_id"]},
    {"name": "get_vehicle_test_drive_history", "description": "Get all test drives for a vehicle.", "parameters": {"vehicle_id": {"type": "string"}}, "required": ["vehicle_id"]},
    {"name": "get_customer_deals", "description": "Get all deals for a customer.", "parameters": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
    {"name": "get_inventory_summary", "description": "Get inventory summary: counts by status, average MSRP, count by condition.", "parameters": {}, "required": []},
    {"name": "get_deal_offers", "description": "Get all offers for a deal, ordered by creation time.", "parameters": {"deal_id": {"type": "string"}}, "required": ["deal_id"]},

    # --- 46-50: Workflow shortcuts ---
    {"name": "create_deal_and_offer", "description": "Create a deal and immediately make an offer in one step.", "parameters": {"customer_id": {"type": "string"}, "vehicle_id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["customer_id", "vehicle_id", "amount"]},
    {"name": "schedule_and_complete_test_drive", "description": "Schedule a test drive and immediately mark it completed.", "parameters": {"vehicle_id": {"type": "string"}, "customer_id": {"type": "string"}, "scheduled_time": {"type": "string"}}, "required": ["vehicle_id", "customer_id", "scheduled_time"]},
    {"name": "full_trade_in_flow", "description": "Add, appraise, and accept a trade-in in one step.", "parameters": {"deal_id": {"type": "string"}, "make": {"type": "string"}, "model": {"type": "string"}, "year": {"type": "integer"}, "vin": {"type": "string"}, "mileage": {"type": "integer"}, "condition": {"type": "string"}, "appraised_value": {"type": "number"}}, "required": ["deal_id", "make", "model", "year", "vin", "mileage", "condition", "appraised_value"]},
    {"name": "submit_and_approve_credit", "description": "Submit a credit application and immediately approve it.", "parameters": {"customer_id": {"type": "string"}, "requested_amount": {"type": "number"}, "approved_amount": {"type": "number"}}, "required": ["customer_id", "requested_amount", "approved_amount"]},
    {"name": "accept_and_apply_trade_in", "description": "Accept an appraised trade-in and apply its credit to the deal in one step.", "parameters": {"deal_id": {"type": "string"}, "trade_in_id": {"type": "string"}}, "required": ["deal_id", "trade_in_id"]},

    # --- 51-55: Cross-entity queries ---
    {"name": "get_vehicle_deal", "description": "Get the active deal (if any) for a vehicle.", "parameters": {"vehicle_id": {"type": "string"}}, "required": ["vehicle_id"]},
    {"name": "get_deal_trade_ins", "description": "Get all trade-ins for a deal.", "parameters": {"deal_id": {"type": "string"}}, "required": ["deal_id"]},
    {"name": "get_customer_test_drives", "description": "Get all test drives for a customer.", "parameters": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
    {"name": "get_offer_details", "description": "Get offer details by ID.", "parameters": {"offer_id": {"type": "string"}}, "required": ["offer_id"]},
    {"name": "get_trade_in_details", "description": "Get trade-in details by ID.", "parameters": {"trade_in_id": {"type": "string"}}, "required": ["trade_in_id"]},

    # --- 56-58: Bulk ops ---
    {"name": "bulk_mark_lost", "description": "Mark multiple deals as lost at once.", "parameters": {"deal_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["deal_ids"]},
    {"name": "bulk_cancel_test_drives", "description": "Cancel multiple scheduled test drives at once.", "parameters": {"test_drive_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["test_drive_ids"]},
    {"name": "count_available_vehicles", "description": "Count the number of available vehicles, optionally filtered by make or condition.", "parameters": {"make": {"type": "string"}, "condition": {"type": "string", "enum": ["new", "used"]}}, "required": []},

    # --- 59-60: Status checks ---
    {"name": "check_test_drive_availability", "description": "Check if a vehicle is available for a test drive at a given time.", "parameters": {"vehicle_id": {"type": "string"}, "scheduled_time": {"type": "string"}}, "required": ["vehicle_id", "scheduled_time"]},
    {"name": "check_vehicle_availability", "description": "Check if a vehicle is available for sale (not reserved/sold/unavailable).", "parameters": {"vehicle_id": {"type": "string"}}, "required": ["vehicle_id"]},
]

AUTO_TOOLS_60 = AUTO_TOOLS_30 + AUTO_TOOLS_60_EXTRA
