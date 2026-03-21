"""Domain logic — CruiseEngine for the cruise booking eval domain."""

from __future__ import annotations

from .models import (
    BookingState,
    BookingStatus,
    CruiseRole,
    CruiseState,
    CruiseStatus,
    CruiseUserTemplate,
    CabinTypeTemplate,
    PassengerState,
    PaymentState,
    PaymentStatus,
)
from eval.backend.domain import DomainError
from eval.backend.models import DomainEvent


# Valid status transitions
BOOKING_TRANSITIONS: dict[BookingStatus, list[BookingStatus]] = {
    BookingStatus.held: [BookingStatus.confirmed, BookingStatus.cancelled],
    BookingStatus.confirmed: [BookingStatus.paid, BookingStatus.cancelled],
    BookingStatus.paid: [BookingStatus.embarked, BookingStatus.cancelled],
    BookingStatus.embarked: [],
    BookingStatus.cancelled: [],
}

CRUISE_TRANSITIONS: dict[CruiseStatus, list[CruiseStatus]] = {
    CruiseStatus.scheduled: [CruiseStatus.boarding, CruiseStatus.cancelled],
    CruiseStatus.boarding: [CruiseStatus.sailing],
    CruiseStatus.sailing: [CruiseStatus.completed],
    CruiseStatus.completed: [],
    CruiseStatus.cancelled: [],
}

PAYMENT_TRANSITIONS: dict[PaymentStatus, list[PaymentStatus]] = {
    PaymentStatus.pending: [PaymentStatus.authorized, PaymentStatus.failed],
    PaymentStatus.authorized: [PaymentStatus.captured, PaymentStatus.failed],
    PaymentStatus.captured: [PaymentStatus.refunded],
    PaymentStatus.refunded: [],
    PaymentStatus.failed: [],
}


class CruiseEngine:
    """Implements cruise booking business rules."""

    # --- Permission checks ---

    @staticmethod
    def check_not_viewer(user: CruiseUserTemplate) -> None:
        if user.role == CruiseRole.viewer:
            raise DomainError(f"{user.name} is a viewer and cannot modify resources.")

    @staticmethod
    def check_agent_or_above(user: CruiseUserTemplate) -> None:
        if user.role not in (CruiseRole.agent, CruiseRole.admin):
            raise DomainError(
                f"{user.name} must be agent or admin for this operation."
            )

    @staticmethod
    def check_admin(user: CruiseUserTemplate) -> None:
        if user.role != CruiseRole.admin:
            raise DomainError(f"{user.name} must be admin for this operation.")

    @staticmethod
    def check_desk_or_above(user: CruiseUserTemplate) -> None:
        if user.role not in (CruiseRole.desk, CruiseRole.agent, CruiseRole.admin):
            raise DomainError(
                f"{user.name} must be desk, agent, or admin for this operation."
            )

    # --- Booking Operations ---

    @staticmethod
    def create_booking(
        user: CruiseUserTemplate,
        cruise: CruiseState,
        cabin_type_template: CabinTypeTemplate,
        booking_count_for_cabin_type: int,
    ) -> tuple[BookingState, DomainEvent]:
        CruiseEngine.check_agent_or_above(user)

        if cruise.status in (CruiseStatus.cancelled, CruiseStatus.completed):
            raise DomainError(
                f"Cannot create bookings for cruise '{cruise.name}' "
                f"with status '{cruise.status.value}'."
            )

        if booking_count_for_cabin_type >= cabin_type_template.total_count:
            raise DomainError(
                f"No cabins available for type '{cabin_type_template.name}' "
                f"on cruise '{cruise.name}' "
                f"({booking_count_for_cabin_type}/{cabin_type_template.total_count} booked)."
            )

        booking = BookingState(
            session_id=cruise.session_id,
            cruise_id=cruise.id,
            cabin_type_id=cabin_type_template.id,
            status=BookingStatus.held,
        )
        event = DomainEvent(
            type="BookingCreated",
            data={
                "cruise": cruise.name,
                "cabin_type": cabin_type_template.name,
                "by": user.name,
            },
        )
        return booking, event

    @staticmethod
    def confirm_booking(
        user: CruiseUserTemplate,
        booking: BookingState,
        passenger_count: int,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if booking.status != BookingStatus.held:
            raise DomainError(
                f"Booking '{booking.id}' must be 'held' to confirm "
                f"(is '{booking.status.value}')."
            )

        if passenger_count < 1:
            raise DomainError(
                "At least one passenger (lead passenger) is required to confirm a booking."
            )

        old_status = booking.status
        booking.status = BookingStatus.confirmed
        booking.passenger_count = passenger_count
        return DomainEvent(
            type="BookingConfirmed",
            data={
                "booking": booking.id,
                "from": old_status.value,
                "to": BookingStatus.confirmed.value,
                "passenger_count": passenger_count,
                "by": user.name,
            },
        )

    @staticmethod
    def pay_booking(
        user: CruiseUserTemplate,
        booking: BookingState,
        captured_payment_exists: bool,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if booking.status != BookingStatus.confirmed:
            raise DomainError(
                f"Booking '{booking.id}' must be 'confirmed' to mark as paid "
                f"(is '{booking.status.value}')."
            )

        if not captured_payment_exists:
            raise DomainError(
                f"Booking '{booking.id}' requires a captured payment before "
                f"it can be marked as paid."
            )

        old_status = booking.status
        booking.status = BookingStatus.paid
        return DomainEvent(
            type="BookingPaid",
            data={
                "booking": booking.id,
                "from": old_status.value,
                "to": BookingStatus.paid.value,
                "by": user.name,
            },
        )

    @staticmethod
    def embark_booking(
        user: CruiseUserTemplate,
        booking: BookingState,
        cruise: CruiseState,
    ) -> DomainEvent:
        CruiseEngine.check_desk_or_above(user)

        if booking.status != BookingStatus.paid:
            raise DomainError(
                f"Booking '{booking.id}' must be 'paid' to embark "
                f"(is '{booking.status.value}')."
            )

        if cruise.status != CruiseStatus.boarding:
            raise DomainError(
                f"Cruise '{cruise.name}' must be 'boarding' to embark passengers "
                f"(is '{cruise.status.value}')."
            )

        old_status = booking.status
        booking.status = BookingStatus.embarked
        return DomainEvent(
            type="BookingEmbarked",
            data={
                "booking": booking.id,
                "from": old_status.value,
                "to": BookingStatus.embarked.value,
                "cruise": cruise.name,
                "by": user.name,
            },
        )

    @staticmethod
    def cancel_booking(
        user: CruiseUserTemplate,
        booking: BookingState,
        cruise: CruiseState,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if booking.status == BookingStatus.embarked:
            raise DomainError(
                f"Cannot cancel booking '{booking.id}': already embarked."
            )

        if booking.status == BookingStatus.cancelled:
            raise DomainError(
                f"Booking '{booking.id}' is already cancelled."
            )

        if booking.status == BookingStatus.paid and cruise.status in (
            CruiseStatus.boarding,
            CruiseStatus.sailing,
            CruiseStatus.completed,
        ):
            raise DomainError(
                f"Cannot cancel paid booking '{booking.id}': "
                f"cruise '{cruise.name}' is already '{cruise.status.value}'."
            )

        old_status = booking.status
        booking.status = BookingStatus.cancelled
        return DomainEvent(
            type="BookingCancelled",
            data={
                "booking": booking.id,
                "from": old_status.value,
                "to": BookingStatus.cancelled.value,
                "by": user.name,
            },
        )

    # --- Passenger Operations ---

    @staticmethod
    def add_passenger(
        user: CruiseUserTemplate,
        booking: BookingState,
        name: str,
        passport_number: str,
        emergency_contact: str,
        cruise_passports: set[str],
        cabin_capacity: int,
        current_passenger_count: int,
    ) -> tuple[PassengerState, DomainEvent]:
        CruiseEngine.check_agent_or_above(user)

        if booking.status in (BookingStatus.embarked, BookingStatus.cancelled):
            raise DomainError(
                f"Cannot add passengers to booking '{booking.id}' "
                f"with status '{booking.status.value}'."
            )

        if passport_number in cruise_passports:
            raise DomainError(
                f"Duplicate passport number '{passport_number}' on this cruise."
            )

        if current_passenger_count >= cabin_capacity:
            raise DomainError(
                f"Cabin capacity reached ({current_passenger_count}/{cabin_capacity}). "
                f"Cannot add more passengers to booking '{booking.id}'."
            )

        passenger = PassengerState(
            session_id=booking.session_id,
            booking_id=booking.id,
            name=name,
            passport_number=passport_number,
            emergency_contact=emergency_contact,
        )
        event = DomainEvent(
            type="PassengerAdded",
            data={
                "booking": booking.id,
                "passenger_name": name,
                "by": user.name,
            },
        )
        return passenger, event

    @staticmethod
    def update_passenger(
        user: CruiseUserTemplate,
        booking: BookingState,
        passenger: PassengerState,
        name: str | None = None,
        emergency_contact: str | None = None,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if booking.status == BookingStatus.embarked:
            raise DomainError(
                f"Cannot update passengers on embarked booking '{booking.id}'."
            )

        if name is not None:
            passenger.name = name
        if emergency_contact is not None:
            passenger.emergency_contact = emergency_contact

        return DomainEvent(
            type="PassengerUpdated",
            data={
                "passenger": passenger.id,
                "booking": booking.id,
                "by": user.name,
            },
        )

    @staticmethod
    def remove_passenger(
        user: CruiseUserTemplate,
        booking: BookingState,
        passenger: PassengerState,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if booking.status in (BookingStatus.embarked, BookingStatus.cancelled):
            raise DomainError(
                f"Cannot remove passengers from booking '{booking.id}' "
                f"with status '{booking.status.value}'."
            )

        return DomainEvent(
            type="PassengerRemoved",
            data={
                "passenger": passenger.id,
                "passenger_name": passenger.name,
                "booking": booking.id,
                "by": user.name,
            },
        )

    # --- Payment Operations ---

    @staticmethod
    def create_payment(
        user: CruiseUserTemplate,
        booking: BookingState,
        amount: float,
        method: str,
    ) -> tuple[PaymentState, DomainEvent]:
        CruiseEngine.check_agent_or_above(user)

        if booking.status in (BookingStatus.cancelled, BookingStatus.embarked):
            raise DomainError(
                f"Cannot create payment for booking '{booking.id}' "
                f"with status '{booking.status.value}'."
            )

        payment = PaymentState(
            session_id=booking.session_id,
            booking_id=booking.id,
            amount=amount,
            status=PaymentStatus.pending,
            method=method,
        )
        event = DomainEvent(
            type="PaymentCreated",
            data={
                "booking": booking.id,
                "amount": amount,
                "method": method,
                "by": user.name,
            },
        )
        return payment, event

    @staticmethod
    def authorize_payment(
        user: CruiseUserTemplate,
        payment: PaymentState,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if payment.status != PaymentStatus.pending:
            raise DomainError(
                f"Payment '{payment.id}' must be 'pending' to authorize "
                f"(is '{payment.status.value}')."
            )

        old_status = payment.status
        payment.status = PaymentStatus.authorized
        return DomainEvent(
            type="PaymentAuthorized",
            data={
                "payment": payment.id,
                "from": old_status.value,
                "to": PaymentStatus.authorized.value,
                "by": user.name,
            },
        )

    @staticmethod
    def capture_payment(
        user: CruiseUserTemplate,
        payment: PaymentState,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if payment.status != PaymentStatus.authorized:
            raise DomainError(
                f"Payment '{payment.id}' must be 'authorized' to capture "
                f"(is '{payment.status.value}')."
            )

        old_status = payment.status
        payment.status = PaymentStatus.captured
        return DomainEvent(
            type="PaymentCaptured",
            data={
                "payment": payment.id,
                "from": old_status.value,
                "to": PaymentStatus.captured.value,
                "by": user.name,
            },
        )

    @staticmethod
    def refund_payment(
        user: CruiseUserTemplate,
        payment: PaymentState,
    ) -> DomainEvent:
        CruiseEngine.check_agent_or_above(user)

        if payment.status != PaymentStatus.captured:
            raise DomainError(
                f"Payment '{payment.id}' must be 'captured' to refund "
                f"(is '{payment.status.value}')."
            )

        old_status = payment.status
        payment.status = PaymentStatus.refunded
        return DomainEvent(
            type="PaymentRefunded",
            data={
                "payment": payment.id,
                "from": old_status.value,
                "to": PaymentStatus.refunded.value,
                "by": user.name,
            },
        )

    # --- Cruise Operations ---

    @staticmethod
    def board_cruise(
        user: CruiseUserTemplate,
        cruise: CruiseState,
        held_booking_count: int,
    ) -> DomainEvent:
        CruiseEngine.check_admin(user)

        if cruise.status != CruiseStatus.scheduled:
            raise DomainError(
                f"Cruise '{cruise.name}' must be 'scheduled' to begin boarding "
                f"(is '{cruise.status.value}')."
            )

        if held_booking_count > 0:
            raise DomainError(
                f"Cannot begin boarding cruise '{cruise.name}': "
                f"{held_booking_count} booking(s) still in 'held' status."
            )

        old_status = cruise.status
        cruise.status = CruiseStatus.boarding
        return DomainEvent(
            type="CruiseBoarding",
            data={
                "cruise": cruise.name,
                "from": old_status.value,
                "to": CruiseStatus.boarding.value,
                "by": user.name,
            },
        )

    @staticmethod
    def sail_cruise(
        user: CruiseUserTemplate,
        cruise: CruiseState,
    ) -> DomainEvent:
        CruiseEngine.check_admin(user)

        if cruise.status != CruiseStatus.boarding:
            raise DomainError(
                f"Cruise '{cruise.name}' must be 'boarding' to sail "
                f"(is '{cruise.status.value}')."
            )

        old_status = cruise.status
        cruise.status = CruiseStatus.sailing
        return DomainEvent(
            type="CruiseSailing",
            data={
                "cruise": cruise.name,
                "from": old_status.value,
                "to": CruiseStatus.sailing.value,
                "by": user.name,
            },
        )

    @staticmethod
    def complete_cruise(
        user: CruiseUserTemplate,
        cruise: CruiseState,
    ) -> DomainEvent:
        CruiseEngine.check_admin(user)

        if cruise.status != CruiseStatus.sailing:
            raise DomainError(
                f"Cruise '{cruise.name}' must be 'sailing' to complete "
                f"(is '{cruise.status.value}')."
            )

        old_status = cruise.status
        cruise.status = CruiseStatus.completed
        return DomainEvent(
            type="CruiseCompleted",
            data={
                "cruise": cruise.name,
                "from": old_status.value,
                "to": CruiseStatus.completed.value,
                "by": user.name,
            },
        )

    @staticmethod
    def cancel_cruise(
        user: CruiseUserTemplate,
        cruise: CruiseState,
    ) -> DomainEvent:
        CruiseEngine.check_admin(user)

        if cruise.status != CruiseStatus.scheduled:
            raise DomainError(
                f"Cruise '{cruise.name}' must be 'scheduled' to cancel "
                f"(is '{cruise.status.value}')."
            )

        old_status = cruise.status
        cruise.status = CruiseStatus.cancelled
        return DomainEvent(
            type="CruiseCancelled",
            data={
                "cruise": cruise.name,
                "from": old_status.value,
                "to": CruiseStatus.cancelled.value,
                "by": user.name,
            },
        )
