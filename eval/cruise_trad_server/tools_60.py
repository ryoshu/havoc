"""60 tools — extends 30 with per-field updates, analytics, bulk ops, granular search."""

from __future__ import annotations

from .tools_30 import CRUISE_TOOLS_30

CRUISE_TOOLS_60_EXTRA = [
    # Per-field passenger updates
    {"name": "set_passenger_name", "description": "Set passenger name.", "parameters": {"passenger_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["passenger_id", "name"]},
    {"name": "set_passenger_emergency_contact", "description": "Set passenger emergency contact.", "parameters": {"passenger_id": {"type": "string"}, "emergency_contact": {"type": "string"}}, "required": ["passenger_id", "emergency_contact"]},
    {"name": "set_booking_cabin_type", "description": "Change the cabin type of a held booking.", "parameters": {"booking_id": {"type": "string"}, "cabin_type_id": {"type": "string"}}, "required": ["booking_id", "cabin_type_id"]},
    # Status-specific search
    {"name": "search_bookings_by_status", "description": "Find all bookings with a specific status.", "parameters": {"status": {"type": "string", "enum": ["held", "confirmed", "paid", "cancelled", "embarked"]}}, "required": ["status"]},
    {"name": "search_bookings_by_cruise", "description": "Find all bookings for a specific cruise.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    {"name": "search_bookings_by_cabin_type", "description": "Find all bookings for a specific cabin type.", "parameters": {"cabin_type_id": {"type": "string"}}, "required": ["cabin_type_id"]},
    {"name": "search_passengers_by_booking", "description": "Find all passengers for a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    {"name": "search_passengers_by_passport", "description": "Find passengers by passport number.", "parameters": {"passport_number": {"type": "string"}}, "required": ["passport_number"]},
    {"name": "search_payments_by_status", "description": "Find payments by status.", "parameters": {"status": {"type": "string", "enum": ["pending", "authorized", "captured", "refunded", "failed"]}}, "required": ["status"]},
    {"name": "search_payments_by_booking", "description": "Find payments by booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    # Bulk operations
    {"name": "bulk_cancel_bookings", "description": "Cancel multiple bookings at once.", "parameters": {"booking_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["booking_ids"]},
    {"name": "bulk_embark", "description": "Embark multiple paid bookings at once.", "parameters": {"booking_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["booking_ids"]},
    # Analytics
    {"name": "get_cruise_stats", "description": "Get cruise statistics: booking counts by status, revenue, passenger count.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    {"name": "get_revenue_summary", "description": "Get revenue summary: total captured, refunded, pending for a cruise.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    {"name": "get_cruise_manifest", "description": "Get full passenger manifest for a cruise.", "parameters": {"cruise_id": {"type": "string"}}, "required": ["cruise_id"]},
    # Audit
    {"name": "get_booking_history", "description": "Get decision/action history for a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    {"name": "get_payment_history", "description": "Get decision/action history for a payment.", "parameters": {"payment_id": {"type": "string"}}, "required": ["payment_id"]},
    # Partial operations
    {"name": "partial_refund", "description": "Refund a partial amount from a captured payment.", "parameters": {"payment_id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["payment_id", "amount"]},
    # Workflow shortcuts
    {"name": "full_checkin", "description": "Combined operation: verify booking is paid, embark booking. Requires cruise in boarding status.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    {"name": "create_and_authorize_payment", "description": "Create and authorize a payment in one step.", "parameters": {"booking_id": {"type": "string"}, "amount": {"type": "number"}, "method": {"type": "string"}}, "required": ["booking_id", "amount", "method"]},
    # Cross-entity queries
    {"name": "get_passenger_booking", "description": "Get the booking associated with a passenger.", "parameters": {"passenger_id": {"type": "string"}}, "required": ["passenger_id"]},
    {"name": "get_booking_cruise", "description": "Get the cruise associated with a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    # Session info
    {"name": "get_session", "description": "Get current session details.", "parameters": {}, "required": []},
    # Inventory check
    {"name": "check_cabin_availability", "description": "Check if a specific cabin type has availability.", "parameters": {"cruise_id": {"type": "string"}, "cabin_type_id": {"type": "string"}}, "required": ["cruise_id", "cabin_type_id"]},
    {"name": "get_cabin_type_details", "description": "Get details of a cabin type including capacity and price.", "parameters": {"cabin_type_id": {"type": "string"}}, "required": ["cabin_type_id"]},
    # Duplicate check
    {"name": "check_passport_duplicate", "description": "Check if a passport number is already registered on a cruise.", "parameters": {"cruise_id": {"type": "string"}, "passport_number": {"type": "string"}}, "required": ["cruise_id", "passport_number"]},
    # Count queries
    {"name": "count_bookings", "description": "Count bookings matching filters.", "parameters": {"cruise_id": {"type": "string"}, "status": {"type": "string", "enum": ["held", "confirmed", "paid", "cancelled", "embarked"]}, "cabin_type_id": {"type": "string"}}, "required": []},
    {"name": "count_passengers", "description": "Count passengers on a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    {"name": "count_payments", "description": "Count payments matching filters.", "parameters": {"booking_id": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "authorized", "captured", "refunded", "failed"]}}, "required": []},
    {"name": "list_booking_passengers_and_payments", "description": "Combined view: list passengers and payments for a booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
]

CRUISE_TOOLS_60 = CRUISE_TOOLS_30 + CRUISE_TOOLS_60_EXTRA
