"""15 baseline tools for the cruise booking traditional server."""

from __future__ import annotations

CRUISE_TOOLS_15 = [
    {
        "name": "get_booking",
        "description": "Get booking details by ID. Returns booking data including status, cabin type, passengers, and payments.",
        "parameters": {"booking_id": {"type": "string", "description": "Booking ID"}},
        "required": ["booking_id"],
    },
    {
        "name": "create_booking",
        "description": "Create a new booking on a cruise. Requires cruise_id and cabin_type_id. Cannot book on cancelled/completed cruises. Must have cabin availability. Only agents and admins.",
        "parameters": {
            "cruise_id": {"type": "string", "description": "Cruise ID"},
            "cabin_type_id": {"type": "string", "description": "Cabin type ID"},
        },
        "required": ["cruise_id", "cabin_type_id"],
    },
    {
        "name": "cancel_booking",
        "description": "Cancel a booking. Cannot cancel embarked bookings. Cannot cancel paid bookings if cruise is boarding or later. Only agents and admins.",
        "parameters": {"booking_id": {"type": "string", "description": "Booking ID to cancel"}},
        "required": ["booking_id"],
    },
    {
        "name": "add_passenger",
        "description": "Add a passenger to a booking. Cannot exceed cabin capacity. Cannot add duplicate passport numbers on the same cruise. Booking must not be embarked or cancelled. Only agents and admins.",
        "parameters": {
            "booking_id": {"type": "string", "description": "Booking ID"},
            "name": {"type": "string", "description": "Passenger full name"},
            "passport_number": {"type": "string", "description": "Passport number"},
            "emergency_contact": {"type": "string", "description": "Emergency contact info"},
        },
        "required": ["booking_id", "name", "passport_number"],
    },
    {
        "name": "create_payment",
        "description": "Create a payment for a booking. Payment starts in 'pending' status. Only agents and admins.",
        "parameters": {
            "booking_id": {"type": "string", "description": "Booking ID"},
            "amount": {"type": "number", "description": "Payment amount"},
            "method": {"type": "string", "description": "Payment method (e.g., 'credit_card', 'bank_transfer')"},
        },
        "required": ["booking_id", "amount", "method"],
    },
    {
        "name": "capture_payment",
        "description": "Capture an authorized payment. Payment must be in 'authorized' status. Only agents and admins.",
        "parameters": {"payment_id": {"type": "string", "description": "Payment ID"}},
        "required": ["payment_id"],
    },
    {
        "name": "confirm_booking",
        "description": "Confirm a held booking. Booking must have at least one passenger. Only agents and admins.",
        "parameters": {"booking_id": {"type": "string", "description": "Booking ID to confirm"}},
        "required": ["booking_id"],
    },
    {
        "name": "pay_booking",
        "description": "Mark a confirmed booking as paid. Requires a captured payment to exist. Only agents and admins.",
        "parameters": {"booking_id": {"type": "string", "description": "Booking ID"}},
        "required": ["booking_id"],
    },
    {
        "name": "get_cruise",
        "description": "Get cruise details by ID, including name, ship, departure date, status, and cabin types.",
        "parameters": {"cruise_id": {"type": "string", "description": "Cruise ID"}},
        "required": ["cruise_id"],
    },
    {
        "name": "search_bookings",
        "description": "Search bookings with filters. Available filters: status, cruise_id, cabin_type_id.",
        "parameters": {
            "status": {"type": "string", "enum": ["held", "confirmed", "paid", "cancelled", "embarked"]},
            "cruise_id": {"type": "string"},
            "cabin_type_id": {"type": "string"},
        },
        "required": [],
    },
    {
        "name": "search_passengers",
        "description": "Search passengers with filters. Available filters: booking_id, passport_number.",
        "parameters": {
            "booking_id": {"type": "string"},
            "passport_number": {"type": "string"},
        },
        "required": [],
    },
    {
        "name": "refund_payment",
        "description": "Refund a captured payment. Payment must be in 'captured' status. Only agents and admins.",
        "parameters": {"payment_id": {"type": "string", "description": "Payment ID"}},
        "required": ["payment_id"],
    },
    {
        "name": "get_payment",
        "description": "Get payment details by ID.",
        "parameters": {"payment_id": {"type": "string", "description": "Payment ID"}},
        "required": ["payment_id"],
    },
    {
        "name": "board_cruise",
        "description": "Transition cruise to boarding status. All bookings must be confirmed, paid, or cancelled (no held bookings). Only admins.",
        "parameters": {"cruise_id": {"type": "string", "description": "Cruise ID"}},
        "required": ["cruise_id"],
    },
    {
        "name": "embark_booking",
        "description": "Check in / embark a booking. Booking must be paid. Cruise must be in boarding status. Desk staff, agents, and admins.",
        "parameters": {"booking_id": {"type": "string", "description": "Booking ID"}},
        "required": ["booking_id"],
    },
]
