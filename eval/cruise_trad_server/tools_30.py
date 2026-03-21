"""30 tools — extends the 15 baseline with 15 more specific operations."""

from __future__ import annotations

from .tools_15 import CRUISE_TOOLS_15

CRUISE_TOOLS_30_EXTRA = [
    # Authorize payment step
    {"name": "authorize_payment", "description": "Authorize a pending payment. Payment must be in 'pending' status.", "parameters": {"payment_id": {"type": "string"}}, "required": ["payment_id"]},
    # Passenger management
    {"name": "update_passenger", "description": "Update passenger details (name, emergency_contact). Booking must not be embarked.", "parameters": {"passenger_id": {"type": "string"}, "name": {"type": "string"}, "emergency_contact": {"type": "string"}}, "required": ["passenger_id"]},
    {"name": "remove_passenger", "description": "Remove a passenger from a booking. Booking must not be embarked or cancelled.", "parameters": {"passenger_id": {"type": "string"}}, "required": ["passenger_id"]},
    {"name": "get_passenger", "description": "Get passenger details by ID.", "parameters": {"passenger_id": {"type": "string"}}, "required": ["passenger_id"]},
    # Cruise lifecycle
    {"name": "sail_cruise", "description": "Transition cruise from boarding to sailing. Only admins.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    {"name": "complete_cruise", "description": "Transition cruise from sailing to completed. Only admins.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    {"name": "cancel_cruise", "description": "Cancel a scheduled cruise. Only admins.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    # Search and listing
    {"name": "search_payments", "description": "Search payments by booking_id or status.", "parameters": {"booking_id": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "authorized", "captured", "refunded", "failed"]}}, "required": []},
    {"name": "list_cruises", "description": "List all cruises in the session.", "parameters": {}, "required": []},
    {"name": "list_users", "description": "List all users, optionally filtered by role.", "parameters": {"role": {"type": "string", "enum": ["admin", "agent", "desk", "viewer"]}}, "required": []},
    {"name": "get_user", "description": "Get user details by ID.", "parameters": {"user_id": {"type": "string"}}, "required": ["user_id"]},
    # Cabin availability
    {"name": "get_cabin_availability", "description": "Get cabin availability for a cruise, showing booked vs total for each cabin type.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    # Booking passengers/payments lookup
    {"name": "get_booking_passengers", "description": "List all passengers on a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    {"name": "get_booking_payments", "description": "List all payments for a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    # Authorize and capture shortcut
    {"name": "authorize_and_capture", "description": "Authorize and immediately capture a pending payment in one step.", "parameters": {"payment_id": {"type": "string"}}, "required": ["payment_id"]},
]

CRUISE_TOOLS_30 = CRUISE_TOOLS_15 + CRUISE_TOOLS_30_EXTRA
