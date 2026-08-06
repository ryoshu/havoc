"""15 baseline tools for the automotive dealership traditional server."""

from __future__ import annotations

AUTO_TOOLS_15 = [
    {
        "name": "get_vehicle",
        "description": "Get vehicle details by ID. Returns make, model, year, trim, VIN, color, MSRP, invoice price, mileage, condition, status, and features.",
        "parameters": {"vehicle_id": {"type": "string", "description": "Vehicle ID"}},
        "required": ["vehicle_id"],
    },
    {
        "name": "create_customer",
        "description": "Register a new customer. Requires name, email, phone, and driver's license number.",
        "parameters": {
            "name": {"type": "string", "description": "Customer full name"},
            "email": {"type": "string", "description": "Customer email address"},
            "phone": {"type": "string", "description": "Customer phone number"},
            "drivers_license": {"type": "string", "description": "Driver's license number"},
        },
        "required": ["name", "email", "phone", "drivers_license"],
    },
    {
        "name": "schedule_test_drive",
        "description": "Schedule a test drive. Vehicle must be available or reserved. Customer must have a driver's license on file. Cannot double-book a vehicle or customer at the same time.",
        "parameters": {
            "vehicle_id": {"type": "string", "description": "Vehicle ID"},
            "customer_id": {"type": "string", "description": "Customer ID"},
            "scheduled_time": {"type": "string", "description": "ISO 8601 datetime for the test drive"},
        },
        "required": ["vehicle_id", "customer_id", "scheduled_time"],
    },
    {
        "name": "create_deal",
        "description": "Start a new deal for a customer on a vehicle. Vehicle must be available (will be reserved). Only salesperson or manager.",
        "parameters": {
            "customer_id": {"type": "string", "description": "Customer ID"},
            "vehicle_id": {"type": "string", "description": "Vehicle ID"},
        },
        "required": ["customer_id", "vehicle_id"],
    },
    {
        "name": "make_offer",
        "description": "Make a dealer offer on a deal. Deal must be in 'negotiating' status. Any previous pending offers on the deal are auto-expired. Only salesperson or manager.",
        "parameters": {
            "deal_id": {"type": "string", "description": "Deal ID"},
            "amount": {"type": "number", "description": "Offer amount in dollars"},
        },
        "required": ["deal_id", "amount"],
    },
    {
        "name": "accept_offer",
        "description": "Accept a pending offer. Offer must be 'pending'. Cannot accept below invoice price. Near-floor offers (<105% of invoice) require manager role.",
        "parameters": {
            "offer_id": {"type": "string", "description": "Offer ID"},
        },
        "required": ["offer_id"],
    },
    {
        "name": "reject_offer",
        "description": "Reject a pending offer. Offer must be 'pending'. Only salesperson or manager.",
        "parameters": {
            "offer_id": {"type": "string", "description": "Offer ID"},
        },
        "required": ["offer_id"],
    },
    {
        "name": "add_trade_in",
        "description": "Add a trade-in vehicle to a deal. Starts in 'pending_appraisal' status. Only salesperson or manager.",
        "parameters": {
            "deal_id": {"type": "string", "description": "Deal ID"},
            "make": {"type": "string", "description": "Trade-in vehicle make"},
            "model": {"type": "string", "description": "Trade-in vehicle model"},
            "year": {"type": "integer", "description": "Trade-in vehicle year"},
            "vin": {"type": "string", "description": "Trade-in vehicle VIN"},
            "mileage": {"type": "integer", "description": "Trade-in vehicle mileage"},
            "condition": {"type": "string", "description": "Trade-in condition (excellent/good/fair/poor)"},
        },
        "required": ["deal_id", "make", "model", "year", "vin", "mileage", "condition"],
    },
    {
        "name": "appraise_trade_in",
        "description": "Set the appraised value of a trade-in. Trade-in must be 'pending_appraisal'. Only salesperson or manager.",
        "parameters": {
            "trade_in_id": {"type": "string", "description": "Trade-in ID"},
            "appraised_value": {"type": "number", "description": "Appraised value in dollars"},
        },
        "required": ["trade_in_id", "appraised_value"],
    },
    {
        "name": "submit_credit_app",
        "description": "Submit a credit application for a customer. Customer credit status must be 'not_started'. Only finance or manager.",
        "parameters": {
            "customer_id": {"type": "string", "description": "Customer ID"},
            "requested_amount": {"type": "number", "description": "Requested financing amount"},
        },
        "required": ["customer_id", "requested_amount"],
    },
    {
        "name": "close_deal",
        "description": "Finalize and close a deal. Deal must be 'approved'. Vehicle is marked as sold. Only finance or manager.",
        "parameters": {
            "deal_id": {"type": "string", "description": "Deal ID"},
            "down_payment": {"type": "number", "description": "Down payment amount"},
        },
        "required": ["deal_id", "down_payment"],
    },
    {
        "name": "search_vehicles",
        "description": "Search inventory with optional filters: status, make, condition.",
        "parameters": {
            "status": {"type": "string", "enum": ["available", "reserved", "sold", "unavailable"], "description": "Vehicle status filter"},
            "make": {"type": "string", "description": "Vehicle make filter"},
            "condition": {"type": "string", "enum": ["new", "used"], "description": "Vehicle condition filter"},
        },
        "required": [],
    },
    {
        "name": "search_deals",
        "description": "Search deals with optional filters: status, customer_id.",
        "parameters": {
            "status": {"type": "string", "enum": ["negotiating", "financing", "approved", "closed", "lost"], "description": "Deal status filter"},
            "customer_id": {"type": "string", "description": "Customer ID filter"},
        },
        "required": [],
    },
    {
        "name": "get_deal",
        "description": "Get deal details by ID, including associated offers and trade-ins.",
        "parameters": {
            "deal_id": {"type": "string", "description": "Deal ID"},
        },
        "required": ["deal_id"],
    },
    {
        "name": "mark_deal_lost",
        "description": "Mark a deal as lost. Cannot mark closed or already-lost deals. Vehicle returns to available status.",
        "parameters": {
            "deal_id": {"type": "string", "description": "Deal ID"},
        },
        "required": ["deal_id"],
    },
]
