"""SQLite layer — mutable automotive dealership state persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .models import (
    AutoSession,
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
from eval.backend.models import DecisionRecord

SCHEMA = """\
CREATE TABLE IF NOT EXISTS auto_sessions (
    id TEXT PRIMARY KEY,
    acting_user_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    template_id TEXT NOT NULL DEFAULT '',
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    year INTEGER NOT NULL DEFAULT 0,
    trim TEXT NOT NULL DEFAULT '',
    vin TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    msrp REAL NOT NULL DEFAULT 0.0,
    invoice_price REAL NOT NULL DEFAULT 0.0,
    mileage INTEGER NOT NULL DEFAULT 0,
    condition TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'available',
    features_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    drivers_license TEXT NOT NULL DEFAULT '',
    credit_score INTEGER NOT NULL DEFAULT 0,
    credit_status TEXT NOT NULL DEFAULT 'not_started',
    pre_approved_amount REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_drives (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    vehicle_id TEXT NOT NULL REFERENCES vehicles(id),
    scheduled_time TEXT NOT NULL DEFAULT '',
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    salesperson_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'scheduled',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    vehicle_id TEXT NOT NULL REFERENCES vehicles(id),
    salesperson_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'negotiating',
    final_price REAL NOT NULL DEFAULT 0.0,
    financing_amount REAL NOT NULL DEFAULT 0.0,
    down_payment REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    deal_id TEXT NOT NULL REFERENCES deals(id),
    amount REAL NOT NULL DEFAULT 0.0,
    offered_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    trade_in_credit REAL NOT NULL DEFAULT 0.0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_ins (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    deal_id TEXT NOT NULL REFERENCES deals(id),
    customer_id TEXT NOT NULL DEFAULT '',
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    year INTEGER NOT NULL DEFAULT 0,
    vin TEXT NOT NULL DEFAULT '',
    mileage INTEGER NOT NULL DEFAULT 0,
    condition TEXT NOT NULL DEFAULT '',
    appraised_value REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending_appraisal',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES auto_sessions(id),
    actor_id TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    affordances_snapshot_json TEXT NOT NULL DEFAULT '[]',
    affordances_not_taken_json TEXT NOT NULL DEFAULT '[]',
    result_summary TEXT NOT NULL DEFAULT '',
    events_json TEXT NOT NULL DEFAULT '[]',
    was_valid INTEGER NOT NULL DEFAULT 1,
    error_message TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
"""


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


class AutoDB:
    """SQLite persistence for mutable automotive dealership state."""

    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # --- Sessions ---

    def create_session(self, acting_user_id: str = "") -> AutoSession:
        sid = _uid("as-")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO auto_sessions (id, acting_user_id, created_at) VALUES (?, ?, ?)",
            (sid, acting_user_id, now),
        )
        self.conn.commit()
        return AutoSession(id=sid, acting_user_id=acting_user_id, created_at=now)

    def get_session(self, session_id: str) -> AutoSession | None:
        row = self.conn.execute(
            "SELECT * FROM auto_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return AutoSession(
            id=row["id"],
            acting_user_id=row["acting_user_id"],
            created_at=row["created_at"],
        )

    def update_session(self, session: AutoSession) -> None:
        self.conn.execute(
            "UPDATE auto_sessions SET acting_user_id=? WHERE id=?",
            (session.acting_user_id, session.id),
        )
        self.conn.commit()

    # --- Vehicles ---

    def create_vehicle(self, vehicle: VehicleState) -> VehicleState:
        if not vehicle.id:
            vehicle.id = _uid("veh-")
        if not vehicle.created_at:
            vehicle.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO vehicles
               (id, session_id, template_id, make, model, year, trim, vin, color,
                msrp, invoice_price, mileage, condition, status, features_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vehicle.id, vehicle.session_id, vehicle.template_id,
                vehicle.make, vehicle.model, vehicle.year, vehicle.trim,
                vehicle.vin, vehicle.color, vehicle.msrp, vehicle.invoice_price,
                vehicle.mileage, vehicle.condition, vehicle.status.value,
                json.dumps(vehicle.features), vehicle.created_at,
            ),
        )
        self.conn.commit()
        return vehicle

    def get_vehicle(self, vehicle_id: str) -> VehicleState | None:
        row = self.conn.execute(
            "SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_vehicle(row)

    def get_session_vehicles(self, session_id: str) -> list[VehicleState]:
        rows = self.conn.execute(
            "SELECT * FROM vehicles WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_vehicle(r) for r in rows]

    def search_vehicles(self, session_id: str, filters: dict) -> list[VehicleState]:
        query = "SELECT * FROM vehicles WHERE session_id = ?"
        params: list = [session_id]
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        if "make" in filters:
            query += " AND make = ?"
            params.append(filters["make"])
        if "condition" in filters:
            query += " AND condition = ?"
            params.append(filters["condition"])
        if "min_price" in filters:
            query += " AND msrp >= ?"
            params.append(filters["min_price"])
        if "max_price" in filters:
            query += " AND msrp <= ?"
            params.append(filters["max_price"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_vehicle(r) for r in rows]

    def update_vehicle(self, vehicle: VehicleState) -> None:
        self.conn.execute(
            """UPDATE vehicles
               SET make=?, model=?, year=?, trim=?, vin=?, color=?,
                   msrp=?, invoice_price=?, mileage=?, condition=?, status=?,
                   features_json=?
               WHERE id=?""",
            (
                vehicle.make, vehicle.model, vehicle.year, vehicle.trim,
                vehicle.vin, vehicle.color, vehicle.msrp, vehicle.invoice_price,
                vehicle.mileage, vehicle.condition, vehicle.status.value,
                json.dumps(vehicle.features), vehicle.id,
            ),
        )
        self.conn.commit()

    def _row_to_vehicle(self, row: sqlite3.Row) -> VehicleState:
        return VehicleState(
            id=row["id"],
            session_id=row["session_id"],
            template_id=row["template_id"],
            make=row["make"],
            model=row["model"],
            year=row["year"],
            trim=row["trim"],
            vin=row["vin"],
            color=row["color"],
            msrp=row["msrp"],
            invoice_price=row["invoice_price"],
            mileage=row["mileage"],
            condition=row["condition"],
            status=VehicleStatus(row["status"]),
            features=json.loads(row["features_json"]),
            created_at=row["created_at"],
        )

    # --- Customers ---

    def create_customer(self, customer: CustomerState) -> CustomerState:
        if not customer.id:
            customer.id = _uid("cust-")
        if not customer.created_at:
            customer.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO customers
               (id, session_id, name, email, phone, drivers_license,
                credit_score, credit_status, pre_approved_amount, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                customer.id, customer.session_id, customer.name,
                customer.email, customer.phone, customer.drivers_license,
                customer.credit_score, customer.credit_status.value,
                customer.pre_approved_amount, customer.created_at,
            ),
        )
        self.conn.commit()
        return customer

    def get_customer(self, customer_id: str) -> CustomerState | None:
        row = self.conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_customer(row)

    def get_session_customers(self, session_id: str) -> list[CustomerState]:
        rows = self.conn.execute(
            "SELECT * FROM customers WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_customer(r) for r in rows]

    def search_customers(self, session_id: str, filters: dict) -> list[CustomerState]:
        query = "SELECT * FROM customers WHERE session_id = ?"
        params: list = [session_id]
        if "name" in filters:
            query += " AND name LIKE ?"
            params.append(f"%{filters['name']}%")
        if "email" in filters:
            query += " AND email LIKE ?"
            params.append(f"%{filters['email']}%")
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_customer(r) for r in rows]

    def update_customer(self, customer: CustomerState) -> None:
        self.conn.execute(
            """UPDATE customers
               SET name=?, email=?, phone=?, drivers_license=?,
                   credit_score=?, credit_status=?, pre_approved_amount=?
               WHERE id=?""",
            (
                customer.name, customer.email, customer.phone,
                customer.drivers_license, customer.credit_score,
                customer.credit_status.value, customer.pre_approved_amount,
                customer.id,
            ),
        )
        self.conn.commit()

    def _row_to_customer(self, row: sqlite3.Row) -> CustomerState:
        return CustomerState(
            id=row["id"],
            session_id=row["session_id"],
            name=row["name"],
            email=row["email"],
            phone=row["phone"],
            drivers_license=row["drivers_license"],
            credit_score=row["credit_score"],
            credit_status=CreditStatus(row["credit_status"]),
            pre_approved_amount=row["pre_approved_amount"],
            created_at=row["created_at"],
        )

    # --- Test Drives ---

    def create_test_drive(self, test_drive: TestDriveState) -> TestDriveState:
        if not test_drive.id:
            test_drive.id = _uid("td-")
        if not test_drive.created_at:
            test_drive.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO test_drives
               (id, session_id, customer_id, vehicle_id, scheduled_time,
                duration_minutes, salesperson_id, status, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                test_drive.id, test_drive.session_id, test_drive.customer_id,
                test_drive.vehicle_id, test_drive.scheduled_time,
                test_drive.duration_minutes, test_drive.salesperson_id,
                test_drive.status.value, test_drive.notes, test_drive.created_at,
            ),
        )
        self.conn.commit()
        return test_drive

    def get_test_drive(self, test_drive_id: str) -> TestDriveState | None:
        row = self.conn.execute(
            "SELECT * FROM test_drives WHERE id = ?", (test_drive_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_test_drive(row)

    def get_session_test_drives(self, session_id: str) -> list[TestDriveState]:
        rows = self.conn.execute(
            "SELECT * FROM test_drives WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_test_drive(r) for r in rows]

    def search_test_drives(self, session_id: str, filters: dict) -> list[TestDriveState]:
        query = "SELECT * FROM test_drives WHERE session_id = ?"
        params: list = [session_id]
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        if "customer_id" in filters:
            query += " AND customer_id = ?"
            params.append(filters["customer_id"])
        if "vehicle_id" in filters:
            query += " AND vehicle_id = ?"
            params.append(filters["vehicle_id"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_test_drive(r) for r in rows]

    def update_test_drive(self, test_drive: TestDriveState) -> None:
        self.conn.execute(
            """UPDATE test_drives
               SET customer_id=?, vehicle_id=?, scheduled_time=?,
                   duration_minutes=?, salesperson_id=?, status=?, notes=?
               WHERE id=?""",
            (
                test_drive.customer_id, test_drive.vehicle_id,
                test_drive.scheduled_time, test_drive.duration_minutes,
                test_drive.salesperson_id, test_drive.status.value,
                test_drive.notes, test_drive.id,
            ),
        )
        self.conn.commit()

    def _row_to_test_drive(self, row: sqlite3.Row) -> TestDriveState:
        return TestDriveState(
            id=row["id"],
            session_id=row["session_id"],
            customer_id=row["customer_id"],
            vehicle_id=row["vehicle_id"],
            scheduled_time=row["scheduled_time"],
            duration_minutes=row["duration_minutes"],
            salesperson_id=row["salesperson_id"],
            status=TestDriveStatus(row["status"]),
            notes=row["notes"],
            created_at=row["created_at"],
        )

    # --- Deals ---

    def create_deal(self, deal: DealState) -> DealState:
        if not deal.id:
            deal.id = _uid("deal-")
        now = datetime.now(timezone.utc).isoformat()
        if not deal.created_at:
            deal.created_at = now
        if not deal.updated_at:
            deal.updated_at = now
        self.conn.execute(
            """INSERT INTO deals
               (id, session_id, customer_id, vehicle_id, salesperson_id,
                status, final_price, financing_amount, down_payment,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                deal.id, deal.session_id, deal.customer_id, deal.vehicle_id,
                deal.salesperson_id, deal.status.value, deal.final_price,
                deal.financing_amount, deal.down_payment,
                deal.created_at, deal.updated_at,
            ),
        )
        self.conn.commit()
        return deal

    def get_deal(self, deal_id: str) -> DealState | None:
        row = self.conn.execute(
            "SELECT * FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_deal(row)

    def get_session_deals(self, session_id: str) -> list[DealState]:
        rows = self.conn.execute(
            "SELECT * FROM deals WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_deal(r) for r in rows]

    def get_vehicle_active_deal(self, session_id: str, vehicle_id: str) -> DealState | None:
        row = self.conn.execute(
            """SELECT * FROM deals
               WHERE session_id = ? AND vehicle_id = ?
               AND status NOT IN (?, ?)
               LIMIT 1""",
            (session_id, vehicle_id, DealStatus.lost.value, DealStatus.closed.value),
        ).fetchone()
        if not row:
            return None
        return self._row_to_deal(row)

    def search_deals(self, session_id: str, filters: dict) -> list[DealState]:
        query = "SELECT * FROM deals WHERE session_id = ?"
        params: list = [session_id]
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        if "customer_id" in filters:
            query += " AND customer_id = ?"
            params.append(filters["customer_id"])
        if "vehicle_id" in filters:
            query += " AND vehicle_id = ?"
            params.append(filters["vehicle_id"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_deal(r) for r in rows]

    def update_deal(self, deal: DealState) -> None:
        deal.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE deals
               SET customer_id=?, vehicle_id=?, salesperson_id=?, status=?,
                   final_price=?, financing_amount=?, down_payment=?, updated_at=?
               WHERE id=?""",
            (
                deal.customer_id, deal.vehicle_id, deal.salesperson_id,
                deal.status.value, deal.final_price, deal.financing_amount,
                deal.down_payment, deal.updated_at, deal.id,
            ),
        )
        self.conn.commit()

    def _row_to_deal(self, row: sqlite3.Row) -> DealState:
        return DealState(
            id=row["id"],
            session_id=row["session_id"],
            customer_id=row["customer_id"],
            vehicle_id=row["vehicle_id"],
            salesperson_id=row["salesperson_id"],
            status=DealStatus(row["status"]),
            final_price=row["final_price"],
            financing_amount=row["financing_amount"],
            down_payment=row["down_payment"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Offers ---

    def create_offer(self, offer: OfferState) -> OfferState:
        if not offer.id:
            offer.id = _uid("off-")
        if not offer.created_at:
            offer.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO offers
               (id, session_id, deal_id, amount, offered_by, status,
                trade_in_credit, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                offer.id, offer.session_id, offer.deal_id, offer.amount,
                offer.offered_by, offer.status.value, offer.trade_in_credit,
                offer.notes, offer.created_at,
            ),
        )
        self.conn.commit()
        return offer

    def get_offer(self, offer_id: str) -> OfferState | None:
        row = self.conn.execute(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_offer(row)

    def get_deal_offers(self, deal_id: str) -> list[OfferState]:
        rows = self.conn.execute(
            "SELECT * FROM offers WHERE deal_id = ? ORDER BY created_at",
            (deal_id,),
        ).fetchall()
        return [self._row_to_offer(r) for r in rows]

    def get_pending_offer(self, deal_id: str) -> OfferState | None:
        row = self.conn.execute(
            "SELECT * FROM offers WHERE deal_id = ? AND status = ? ORDER BY created_at DESC LIMIT 1",
            (deal_id, OfferStatus.pending.value),
        ).fetchone()
        if not row:
            return None
        return self._row_to_offer(row)

    def get_session_offers(self, session_id: str) -> list[OfferState]:
        rows = self.conn.execute(
            "SELECT * FROM offers WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._row_to_offer(r) for r in rows]

    def search_offers(self, session_id: str, filters: dict) -> list[OfferState]:
        query = "SELECT * FROM offers WHERE session_id = ?"
        params: list = [session_id]
        if "deal_id" in filters:
            query += " AND deal_id = ?"
            params.append(filters["deal_id"])
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        query += " ORDER BY created_at"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_offer(r) for r in rows]

    def update_offer(self, offer: OfferState) -> None:
        self.conn.execute(
            """UPDATE offers
               SET amount=?, offered_by=?, status=?, trade_in_credit=?, notes=?
               WHERE id=?""",
            (
                offer.amount, offer.offered_by, offer.status.value,
                offer.trade_in_credit, offer.notes, offer.id,
            ),
        )
        self.conn.commit()

    def _row_to_offer(self, row: sqlite3.Row) -> OfferState:
        return OfferState(
            id=row["id"],
            session_id=row["session_id"],
            deal_id=row["deal_id"],
            amount=row["amount"],
            offered_by=row["offered_by"],
            status=OfferStatus(row["status"]),
            trade_in_credit=row["trade_in_credit"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    # --- Trade-Ins ---

    def create_trade_in(self, trade_in: TradeInState) -> TradeInState:
        if not trade_in.id:
            trade_in.id = _uid("ti-")
        if not trade_in.created_at:
            trade_in.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO trade_ins
               (id, session_id, deal_id, customer_id, make, model, year, vin,
                mileage, condition, appraised_value, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_in.id, trade_in.session_id, trade_in.deal_id,
                trade_in.customer_id, trade_in.make, trade_in.model,
                trade_in.year, trade_in.vin, trade_in.mileage,
                trade_in.condition, trade_in.appraised_value,
                trade_in.status.value, trade_in.created_at,
            ),
        )
        self.conn.commit()
        return trade_in

    def get_trade_in(self, trade_in_id: str) -> TradeInState | None:
        row = self.conn.execute(
            "SELECT * FROM trade_ins WHERE id = ?", (trade_in_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_trade_in(row)

    def get_deal_trade_ins(self, deal_id: str) -> list[TradeInState]:
        rows = self.conn.execute(
            "SELECT * FROM trade_ins WHERE deal_id = ? ORDER BY created_at",
            (deal_id,),
        ).fetchall()
        return [self._row_to_trade_in(r) for r in rows]

    def get_session_trade_ins(self, session_id: str) -> list[TradeInState]:
        rows = self.conn.execute(
            "SELECT * FROM trade_ins WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._row_to_trade_in(r) for r in rows]

    def search_trade_ins(self, session_id: str, filters: dict) -> list[TradeInState]:
        query = "SELECT * FROM trade_ins WHERE session_id = ?"
        params: list = [session_id]
        if "deal_id" in filters:
            query += " AND deal_id = ?"
            params.append(filters["deal_id"])
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        if "customer_id" in filters:
            query += " AND customer_id = ?"
            params.append(filters["customer_id"])
        query += " ORDER BY created_at"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_trade_in(r) for r in rows]

    def update_trade_in(self, trade_in: TradeInState) -> None:
        self.conn.execute(
            """UPDATE trade_ins
               SET deal_id=?, customer_id=?, make=?, model=?, year=?, vin=?,
                   mileage=?, condition=?, appraised_value=?, status=?
               WHERE id=?""",
            (
                trade_in.deal_id, trade_in.customer_id, trade_in.make,
                trade_in.model, trade_in.year, trade_in.vin,
                trade_in.mileage, trade_in.condition, trade_in.appraised_value,
                trade_in.status.value, trade_in.id,
            ),
        )
        self.conn.commit()

    def _row_to_trade_in(self, row: sqlite3.Row) -> TradeInState:
        return TradeInState(
            id=row["id"],
            session_id=row["session_id"],
            deal_id=row["deal_id"],
            customer_id=row["customer_id"],
            make=row["make"],
            model=row["model"],
            year=row["year"],
            vin=row["vin"],
            mileage=row["mileage"],
            condition=row["condition"],
            appraised_value=row["appraised_value"],
            status=TradeInStatus(row["status"]),
            created_at=row["created_at"],
        )

    # --- Decision Records ---

    def record_decision(self, decision: DecisionRecord) -> DecisionRecord:
        if not decision.id:
            decision.id = _uid("dec-")
        if not decision.timestamp:
            decision.timestamp = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO decision_records
               (id, session_id, actor_id, actor_name, action, params_json,
                affordances_snapshot_json, affordances_not_taken_json,
                result_summary, events_json, was_valid, error_message, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.id, decision.session_id, decision.actor_id,
                decision.actor_name, decision.action,
                json.dumps(decision.params),
                json.dumps(decision.affordances_snapshot),
                json.dumps(decision.affordances_not_taken),
                decision.result_summary,
                json.dumps(decision.events),
                int(decision.was_valid), decision.error_message,
                decision.timestamp,
            ),
        )
        self.conn.commit()
        return decision

    def get_session_decisions(self, session_id: str) -> list[DecisionRecord]:
        rows = self.conn.execute(
            "SELECT * FROM decision_records WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def _row_to_decision(self, row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            id=row["id"],
            session_id=row["session_id"],
            actor_id=row["actor_id"],
            actor_name=row["actor_name"],
            action=row["action"],
            params=json.loads(row["params_json"]),
            affordances_snapshot=json.loads(row["affordances_snapshot_json"]),
            affordances_not_taken=json.loads(row["affordances_not_taken_json"]),
            result_summary=row["result_summary"],
            events=json.loads(row["events_json"]),
            was_valid=bool(row["was_valid"]),
            error_message=row["error_message"],
            timestamp=row["timestamp"],
        )
