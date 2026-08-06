"""30 tools — extends the 15 baseline with 15 more specific operations."""

from __future__ import annotations

from .tools_15 import AUTO_TOOLS_15

AUTO_TOOLS_30_EXTRA = [
    # Customer lookup
    {"name": "get_customer", "description": "Get customer details by ID, including credit status and pre-approved amount.", "parameters": {"customer_id": {"type": "string", "description": "Customer ID"}}, "required": ["customer_id"]},
    # Customer update
    {"name": "update_customer", "description": "Update customer fields. At least one optional field must be provided. Only salesperson, finance, or manager.", "parameters": {"customer_id": {"type": "string", "description": "Customer ID"}, "phone": {"type": "string", "description": "New phone number"}, "email": {"type": "string", "description": "New email address"}, "drivers_license": {"type": "string", "description": "New driver's license number"}}, "required": ["customer_id"]},
    # Counter offer
    {"name": "counter_offer", "description": "Counter a pending offer with a new amount. The original offer is marked 'countered' and a new pending offer is created. Deal must be 'negotiating'. Only salesperson or manager.", "parameters": {"deal_id": {"type": "string", "description": "Deal ID"}, "amount": {"type": "number", "description": "Counter-offer amount"}}, "required": ["deal_id", "amount"]},
    # Trade-in acceptance/decline
    {"name": "accept_trade_in", "description": "Accept an appraised trade-in. Trade-in must be 'appraised'. Only salesperson or manager.", "parameters": {"trade_in_id": {"type": "string", "description": "Trade-in ID"}}, "required": ["trade_in_id"]},
    {"name": "decline_trade_in", "description": "Decline an appraised trade-in. Trade-in must be 'appraised'. Only salesperson or manager.", "parameters": {"trade_in_id": {"type": "string", "description": "Trade-in ID"}}, "required": ["trade_in_id"]},
    # Apply trade-in credit
    {"name": "apply_trade_in_credit", "description": "Apply an accepted trade-in's appraised value as credit on a deal. Trade-in must be 'accepted'. Deal must be 'negotiating'. Only salesperson or manager.", "parameters": {"deal_id": {"type": "string", "description": "Deal ID"}, "trade_in_id": {"type": "string", "description": "Trade-in ID"}}, "required": ["deal_id", "trade_in_id"]},
    # Credit decisions
    {"name": "approve_credit", "description": "Approve a submitted credit application. Sets pre-approved amount. Only finance or manager.", "parameters": {"customer_id": {"type": "string", "description": "Customer ID"}, "approved_amount": {"type": "number", "description": "Approved financing amount"}}, "required": ["customer_id", "approved_amount"]},
    {"name": "deny_credit", "description": "Deny a submitted credit application. Only finance or manager.", "parameters": {"customer_id": {"type": "string", "description": "Customer ID"}}, "required": ["customer_id"]},
    # Deal workflow
    {"name": "move_to_financing", "description": "Move a deal from 'negotiating' to 'financing'. Requires an accepted offer. Only salesperson or manager.", "parameters": {"deal_id": {"type": "string", "description": "Deal ID"}}, "required": ["deal_id"]},
    {"name": "approve_deal", "description": "Approve a deal in 'financing' status. Customer credit must be 'approved' or 'conditional'. Only finance or manager.", "parameters": {"deal_id": {"type": "string", "description": "Deal ID"}}, "required": ["deal_id"]},
    # Test drive lifecycle
    {"name": "complete_test_drive", "description": "Mark a scheduled test drive as completed.", "parameters": {"test_drive_id": {"type": "string", "description": "Test drive ID"}}, "required": ["test_drive_id"]},
    {"name": "cancel_test_drive", "description": "Cancel a scheduled test drive.", "parameters": {"test_drive_id": {"type": "string", "description": "Test drive ID"}}, "required": ["test_drive_id"]},
    {"name": "get_test_drive", "description": "Get test drive details by ID.", "parameters": {"test_drive_id": {"type": "string", "description": "Test drive ID"}}, "required": ["test_drive_id"]},
    # Test drive search
    {"name": "search_test_drives", "description": "Search test drives with optional filters: status, customer_id, vehicle_id.", "parameters": {"status": {"type": "string", "enum": ["scheduled", "completed", "cancelled", "no_show"], "description": "Test drive status filter"}, "customer_id": {"type": "string", "description": "Customer ID filter"}, "vehicle_id": {"type": "string", "description": "Vehicle ID filter"}}, "required": []},
    # User lookup
    {"name": "get_user", "description": "Get user (staff) details by ID, including role.", "parameters": {"user_id": {"type": "string", "description": "User ID"}}, "required": ["user_id"]},
]

AUTO_TOOLS_30 = AUTO_TOOLS_15 + AUTO_TOOLS_30_EXTRA
