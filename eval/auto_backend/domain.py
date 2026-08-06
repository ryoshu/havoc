"""Domain logic — AutoEngine for the automotive dealership eval domain."""

from __future__ import annotations

from datetime import datetime

from .models import (
    AutoRole,
    AutoUserTemplate,
    CreditStatus,
    CustomerState,
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
from eval.backend.domain import DomainError
from eval.backend.models import DomainEvent


# Valid status transitions
DEAL_TRANSITIONS: dict[DealStatus, list[DealStatus]] = {
    DealStatus.negotiating: [DealStatus.financing, DealStatus.lost],
    DealStatus.financing: [DealStatus.approved, DealStatus.negotiating, DealStatus.lost],
    DealStatus.approved: [DealStatus.closed, DealStatus.lost],
    DealStatus.closed: [],
    DealStatus.lost: [],
}

OFFER_TRANSITIONS: dict[OfferStatus, list[OfferStatus]] = {
    OfferStatus.pending: [OfferStatus.accepted, OfferStatus.rejected, OfferStatus.countered, OfferStatus.expired],
    OfferStatus.accepted: [],
    OfferStatus.rejected: [],
    OfferStatus.countered: [],
    OfferStatus.expired: [],
}

TRADE_IN_TRANSITIONS: dict[TradeInStatus, list[TradeInStatus]] = {
    TradeInStatus.pending_appraisal: [TradeInStatus.appraised],
    TradeInStatus.appraised: [TradeInStatus.accepted, TradeInStatus.declined],
    TradeInStatus.accepted: [TradeInStatus.applied],
    TradeInStatus.declined: [],
    TradeInStatus.applied: [],
}

TEST_DRIVE_TRANSITIONS: dict[TestDriveStatus, list[TestDriveStatus]] = {
    TestDriveStatus.scheduled: [TestDriveStatus.completed, TestDriveStatus.cancelled, TestDriveStatus.no_show],
    TestDriveStatus.completed: [],
    TestDriveStatus.cancelled: [],
    TestDriveStatus.no_show: [],
}


class AutoEngine:
    """Implements automotive dealership business rules."""

    # --- Permission checks ---

    @staticmethod
    def check_not_receptionist(user: AutoUserTemplate) -> None:
        if user.role == AutoRole.receptionist:
            raise DomainError(f"{user.name} is a receptionist and cannot perform this operation.")

    @staticmethod
    def check_sales_or_above(user: AutoUserTemplate) -> None:
        if user.role not in (AutoRole.salesperson, AutoRole.manager):
            raise DomainError(
                f"{user.name} must be salesperson or manager for this operation."
            )

    @staticmethod
    def check_manager(user: AutoUserTemplate) -> None:
        if user.role != AutoRole.manager:
            raise DomainError(f"{user.name} must be manager for this operation.")

    @staticmethod
    def check_finance_or_manager(user: AutoUserTemplate) -> None:
        if user.role not in (AutoRole.finance, AutoRole.manager):
            raise DomainError(
                f"{user.name} must be finance or manager for this operation."
            )

    @staticmethod
    def check_not_finance(user: AutoUserTemplate) -> None:
        if user.role == AutoRole.finance:
            raise DomainError(f"{user.name} is finance and cannot perform this operation.")

    # --- Customer Operations ---

    @staticmethod
    def create_customer(
        user: AutoUserTemplate,
        name: str,
        email: str,
        phone: str,
        drivers_license: str,
        session_id: str,
    ) -> tuple[CustomerState, DomainEvent]:
        # Any role can create a customer
        customer = CustomerState(
            session_id=session_id,
            name=name,
            email=email,
            phone=phone,
            drivers_license=drivers_license,
        )
        event = DomainEvent(
            type="CustomerCreated",
            data={"name": name, "email": email, "by": user.name},
        )
        return customer, event

    @staticmethod
    def update_customer(
        user: AutoUserTemplate,
        customer: CustomerState,
        **fields: str,
    ) -> DomainEvent:
        AutoEngine.check_not_receptionist(user)

        for key, value in fields.items():
            if hasattr(customer, key):
                setattr(customer, key, value)

        return DomainEvent(
            type="CustomerUpdated",
            data={"customer": customer.name, "fields": list(fields.keys()), "by": user.name},
        )

    @staticmethod
    def submit_credit_app(
        user: AutoUserTemplate,
        customer: CustomerState,
        requested_amount: float,
    ) -> DomainEvent:
        AutoEngine.check_finance_or_manager(user)

        if customer.credit_status != CreditStatus.not_started:
            raise DomainError(
                f"Credit application for '{customer.name}' already started "
                f"(status: '{customer.credit_status.value}')."
            )

        customer.credit_status = CreditStatus.submitted
        return DomainEvent(
            type="CreditAppSubmitted",
            data={
                "customer": customer.name,
                "requested_amount": requested_amount,
                "by": user.name,
            },
        )

    @staticmethod
    def approve_credit(
        user: AutoUserTemplate,
        customer: CustomerState,
        approved_amount: float,
    ) -> DomainEvent:
        AutoEngine.check_finance_or_manager(user)

        if customer.credit_status != CreditStatus.submitted:
            raise DomainError(
                f"Credit for '{customer.name}' must be 'submitted' to approve "
                f"(is '{customer.credit_status.value}')."
            )

        customer.credit_status = CreditStatus.approved
        customer.pre_approved_amount = approved_amount
        return DomainEvent(
            type="CreditApproved",
            data={
                "customer": customer.name,
                "approved_amount": approved_amount,
                "by": user.name,
            },
        )

    @staticmethod
    def deny_credit(
        user: AutoUserTemplate,
        customer: CustomerState,
    ) -> DomainEvent:
        AutoEngine.check_finance_or_manager(user)

        if customer.credit_status != CreditStatus.submitted:
            raise DomainError(
                f"Credit for '{customer.name}' must be 'submitted' to deny "
                f"(is '{customer.credit_status.value}')."
            )

        customer.credit_status = CreditStatus.denied
        return DomainEvent(
            type="CreditDenied",
            data={"customer": customer.name, "by": user.name},
        )

    # --- Test Drive Operations ---

    @staticmethod
    def schedule_test_drive(
        user: AutoUserTemplate,
        vehicle: VehicleState,
        customer: CustomerState,
        scheduled_time: str,
        salesperson_id: str,
        existing_drives: list[TestDriveState],
    ) -> tuple[TestDriveState, DomainEvent]:
        AutoEngine.check_not_finance(user)

        if vehicle.status not in (VehicleStatus.available, VehicleStatus.reserved):
            raise DomainError(
                f"Vehicle '{vehicle.make} {vehicle.model}' is '{vehicle.status.value}' "
                f"and cannot be test driven."
            )

        if not customer.drivers_license:
            raise DomainError(
                f"Customer '{customer.name}' does not have a driver's license on file."
            )

        # Check for time conflicts
        try:
            new_time = datetime.fromisoformat(scheduled_time)
        except ValueError:
            raise DomainError(f"Invalid scheduled_time format: '{scheduled_time}'.")

        for drive in existing_drives:
            if drive.status != TestDriveStatus.scheduled:
                continue
            try:
                existing_time = datetime.fromisoformat(drive.scheduled_time)
            except ValueError:
                continue
            diff_minutes = abs((new_time - existing_time).total_seconds()) / 60
            if diff_minutes < drive.duration_minutes:
                if drive.vehicle_id == vehicle.id:
                    raise DomainError(
                        f"Vehicle '{vehicle.make} {vehicle.model}' has a conflicting "
                        f"test drive at {drive.scheduled_time}."
                    )
                if drive.customer_id == customer.id:
                    raise DomainError(
                        f"Customer '{customer.name}' has a conflicting "
                        f"test drive at {drive.scheduled_time}."
                    )

        test_drive = TestDriveState(
            session_id=vehicle.session_id,
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            scheduled_time=scheduled_time,
            salesperson_id=salesperson_id,
        )
        event = DomainEvent(
            type="TestDriveScheduled",
            data={
                "customer": customer.name,
                "vehicle": f"{vehicle.make} {vehicle.model}",
                "time": scheduled_time,
                "by": user.name,
            },
        )
        return test_drive, event

    @staticmethod
    def complete_test_drive(
        user: AutoUserTemplate,
        test_drive: TestDriveState,
    ) -> DomainEvent:
        if test_drive.status != TestDriveStatus.scheduled:
            raise DomainError(
                f"Test drive '{test_drive.id}' must be 'scheduled' to complete "
                f"(is '{test_drive.status.value}')."
            )

        test_drive.status = TestDriveStatus.completed
        return DomainEvent(
            type="TestDriveCompleted",
            data={"test_drive": test_drive.id, "by": user.name},
        )

    @staticmethod
    def cancel_test_drive(
        user: AutoUserTemplate,
        test_drive: TestDriveState,
    ) -> DomainEvent:
        if test_drive.status != TestDriveStatus.scheduled:
            raise DomainError(
                f"Test drive '{test_drive.id}' must be 'scheduled' to cancel "
                f"(is '{test_drive.status.value}')."
            )

        test_drive.status = TestDriveStatus.cancelled
        return DomainEvent(
            type="TestDriveCancelled",
            data={"test_drive": test_drive.id, "by": user.name},
        )

    # --- Deal Operations ---

    @staticmethod
    def create_deal(
        user: AutoUserTemplate,
        vehicle: VehicleState,
        customer: CustomerState,
        salesperson_id: str,
        session_id: str,
    ) -> tuple[DealState, DomainEvent]:
        AutoEngine.check_sales_or_above(user)

        if vehicle.status != VehicleStatus.available:
            raise DomainError(
                f"Vehicle '{vehicle.make} {vehicle.model}' must be 'available' to start a deal "
                f"(is '{vehicle.status.value}')."
            )

        vehicle.status = VehicleStatus.reserved
        deal = DealState(
            session_id=session_id,
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            salesperson_id=salesperson_id,
        )
        event = DomainEvent(
            type="DealCreated",
            data={
                "customer": customer.name,
                "vehicle": f"{vehicle.make} {vehicle.model}",
                "salesperson_id": salesperson_id,
                "by": user.name,
            },
        )
        return deal, event

    @staticmethod
    def mark_deal_lost(
        user: AutoUserTemplate,
        deal: DealState,
        vehicle: VehicleState,
    ) -> DomainEvent:
        AutoEngine.check_not_receptionist(user)

        if deal.status in (DealStatus.closed, DealStatus.lost):
            raise DomainError(
                f"Deal '{deal.id}' is already '{deal.status.value}' and cannot be marked lost."
            )

        deal.status = DealStatus.lost
        vehicle.status = VehicleStatus.available
        return DomainEvent(
            type="DealLost",
            data={"deal": deal.id, "by": user.name},
        )

    @staticmethod
    def move_to_financing(
        user: AutoUserTemplate,
        deal: DealState,
        has_accepted_offer: bool,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if deal.status != DealStatus.negotiating:
            raise DomainError(
                f"Deal '{deal.id}' must be 'negotiating' to move to financing "
                f"(is '{deal.status.value}')."
            )

        if not has_accepted_offer:
            raise DomainError(
                f"Deal '{deal.id}' must have an accepted offer before moving to financing."
            )

        deal.status = DealStatus.financing
        return DomainEvent(
            type="DealMovedToFinancing",
            data={"deal": deal.id, "by": user.name},
        )

    @staticmethod
    def approve_deal(
        user: AutoUserTemplate,
        deal: DealState,
        customer: CustomerState,
    ) -> DomainEvent:
        AutoEngine.check_finance_or_manager(user)

        if deal.status != DealStatus.financing:
            raise DomainError(
                f"Deal '{deal.id}' must be 'financing' to approve "
                f"(is '{deal.status.value}')."
            )

        if customer.credit_status not in (CreditStatus.approved, CreditStatus.conditional):
            raise DomainError(
                f"Customer '{customer.name}' credit status must be 'approved' or 'conditional' "
                f"(is '{customer.credit_status.value}')."
            )

        deal.status = DealStatus.approved
        return DomainEvent(
            type="DealApproved",
            data={"deal": deal.id, "customer": customer.name, "by": user.name},
        )

    @staticmethod
    def close_deal(
        user: AutoUserTemplate,
        deal: DealState,
        vehicle: VehicleState,
        accepted_offer_amount: float,
        down_payment: float,
    ) -> DomainEvent:
        AutoEngine.check_finance_or_manager(user)

        if deal.status != DealStatus.approved:
            raise DomainError(
                f"Deal '{deal.id}' must be 'approved' to close "
                f"(is '{deal.status.value}')."
            )

        deal.status = DealStatus.closed
        deal.final_price = accepted_offer_amount
        deal.down_payment = down_payment
        deal.financing_amount = accepted_offer_amount - down_payment
        vehicle.status = VehicleStatus.sold
        return DomainEvent(
            type="DealClosed",
            data={
                "deal": deal.id,
                "final_price": accepted_offer_amount,
                "down_payment": down_payment,
                "by": user.name,
            },
        )

    # --- Offer Operations ---

    @staticmethod
    def make_offer(
        user: AutoUserTemplate,
        deal: DealState,
        amount: float,
        existing_pending_offers: list[OfferState],
        offered_by: str = "dealer",
    ) -> tuple[OfferState, DomainEvent]:
        AutoEngine.check_sales_or_above(user)

        if deal.status != DealStatus.negotiating:
            raise DomainError(
                f"Deal '{deal.id}' must be 'negotiating' to make an offer "
                f"(is '{deal.status.value}')."
            )

        # Auto-expire previous pending offers on this deal
        for offer in existing_pending_offers:
            if offer.status == OfferStatus.pending:
                offer.status = OfferStatus.expired

        new_offer = OfferState(
            session_id=deal.session_id,
            deal_id=deal.id,
            amount=amount,
            offered_by=offered_by,
        )
        event = DomainEvent(
            type="OfferMade",
            data={
                "deal": deal.id,
                "amount": amount,
                "offered_by": offered_by,
                "by": user.name,
            },
        )
        return new_offer, event

    @staticmethod
    def accept_offer(
        user: AutoUserTemplate,
        deal: DealState,
        offer: OfferState,
        vehicle_invoice_price: float,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if offer.status != OfferStatus.pending:
            raise DomainError(
                f"Offer '{offer.id}' must be 'pending' to accept "
                f"(is '{offer.status.value}')."
            )

        if offer.amount < vehicle_invoice_price:
            raise DomainError(
                f"Offer amount ${offer.amount:.2f} is below invoice price "
                f"${vehicle_invoice_price:.2f}. Cannot accept below cost."
            )

        # C10: if amount < invoice_price * 1.05, require manager
        if offer.amount < vehicle_invoice_price * 1.05:
            AutoEngine.check_manager(user)

        offer.status = OfferStatus.accepted
        return DomainEvent(
            type="OfferAccepted",
            data={
                "deal": deal.id,
                "offer": offer.id,
                "amount": offer.amount,
                "by": user.name,
            },
        )

    @staticmethod
    def reject_offer(
        user: AutoUserTemplate,
        offer: OfferState,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if offer.status != OfferStatus.pending:
            raise DomainError(
                f"Offer '{offer.id}' must be 'pending' to reject "
                f"(is '{offer.status.value}')."
            )

        offer.status = OfferStatus.rejected
        return DomainEvent(
            type="OfferRejected",
            data={"offer": offer.id, "by": user.name},
        )

    @staticmethod
    def counter_offer(
        user: AutoUserTemplate,
        deal: DealState,
        offer: OfferState,
        amount: float,
        offered_by: str = "dealer",
    ) -> tuple[OfferState, DomainEvent]:
        AutoEngine.check_sales_or_above(user)

        if deal.status != DealStatus.negotiating:
            raise DomainError(
                f"Deal '{deal.id}' must be 'negotiating' to counter an offer "
                f"(is '{deal.status.value}')."
            )

        if offer.status != OfferStatus.pending:
            raise DomainError(
                f"Offer '{offer.id}' must be 'pending' to counter "
                f"(is '{offer.status.value}')."
            )

        offer.status = OfferStatus.countered
        new_offer = OfferState(
            session_id=deal.session_id,
            deal_id=deal.id,
            amount=amount,
            offered_by=offered_by,
        )
        event = DomainEvent(
            type="OfferCountered",
            data={
                "deal": deal.id,
                "original_offer": offer.id,
                "new_amount": amount,
                "offered_by": offered_by,
                "by": user.name,
            },
        )
        return new_offer, event

    # --- Trade-In Operations ---

    @staticmethod
    def add_trade_in(
        user: AutoUserTemplate,
        deal: DealState,
        customer_id: str,
        make: str,
        model: str,
        year: int,
        vin: str,
        mileage: int,
        condition: str,
        session_id: str,
    ) -> tuple[TradeInState, DomainEvent]:
        AutoEngine.check_sales_or_above(user)

        trade_in = TradeInState(
            session_id=session_id,
            deal_id=deal.id,
            customer_id=customer_id,
            make=make,
            model=model,
            year=year,
            vin=vin,
            mileage=mileage,
            condition=condition,
        )
        event = DomainEvent(
            type="TradeInAdded",
            data={
                "deal": deal.id,
                "vehicle": f"{year} {make} {model}",
                "by": user.name,
            },
        )
        return trade_in, event

    @staticmethod
    def appraise_trade_in(
        user: AutoUserTemplate,
        trade_in: TradeInState,
        appraised_value: float,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if trade_in.status != TradeInStatus.pending_appraisal:
            raise DomainError(
                f"Trade-in '{trade_in.id}' must be 'pending_appraisal' to appraise "
                f"(is '{trade_in.status.value}')."
            )

        trade_in.status = TradeInStatus.appraised
        trade_in.appraised_value = appraised_value
        return DomainEvent(
            type="TradeInAppraised",
            data={
                "trade_in": trade_in.id,
                "appraised_value": appraised_value,
                "by": user.name,
            },
        )

    @staticmethod
    def accept_trade_in(
        user: AutoUserTemplate,
        trade_in: TradeInState,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if trade_in.status != TradeInStatus.appraised:
            raise DomainError(
                f"Trade-in '{trade_in.id}' must be 'appraised' to accept "
                f"(is '{trade_in.status.value}')."
            )

        trade_in.status = TradeInStatus.accepted
        return DomainEvent(
            type="TradeInAccepted",
            data={"trade_in": trade_in.id, "by": user.name},
        )

    @staticmethod
    def decline_trade_in(
        user: AutoUserTemplate,
        trade_in: TradeInState,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if trade_in.status != TradeInStatus.appraised:
            raise DomainError(
                f"Trade-in '{trade_in.id}' must be 'appraised' to decline "
                f"(is '{trade_in.status.value}')."
            )

        trade_in.status = TradeInStatus.declined
        return DomainEvent(
            type="TradeInDeclined",
            data={"trade_in": trade_in.id, "by": user.name},
        )

    @staticmethod
    def apply_trade_in_credit(
        user: AutoUserTemplate,
        deal: DealState,
        trade_in: TradeInState,
    ) -> DomainEvent:
        AutoEngine.check_sales_or_above(user)

        if trade_in.status != TradeInStatus.accepted:
            raise DomainError(
                f"Trade-in '{trade_in.id}' must be 'accepted' to apply credit "
                f"(is '{trade_in.status.value}')."
            )

        if deal.status != DealStatus.negotiating:
            raise DomainError(
                f"Deal '{deal.id}' must be 'negotiating' to apply trade-in credit "
                f"(is '{deal.status.value}')."
            )

        trade_in.status = TradeInStatus.applied
        return DomainEvent(
            type="TradeInCreditApplied",
            data={
                "deal": deal.id,
                "trade_in": trade_in.id,
                "credit": trade_in.appraised_value,
                "by": user.name,
            },
        )
