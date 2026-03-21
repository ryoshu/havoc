"""SQLite layer — mutable cruise booking state persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .models import (
    BookingState,
    BookingStatus,
    CruiseSession,
    CruiseState,
    CruiseStatus,
    PassengerState,
    PaymentState,
    PaymentStatus,
)
from eval.backend.models import DecisionRecord

SCHEMA = """\
CREATE TABLE IF NOT EXISTS cruise_sessions (
    id TEXT PRIMARY KEY,
    acting_user_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cruises (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cruise_sessions(id),
    template_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    ship TEXT NOT NULL DEFAULT '',
    departure_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cruise_sessions(id),
    cruise_id TEXT NOT NULL REFERENCES cruises(id),
    cabin_type_id TEXT NOT NULL DEFAULT '',
    cabin_number TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'held',
    lead_passenger_id TEXT NOT NULL DEFAULT '',
    passenger_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passengers (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cruise_sessions(id),
    booking_id TEXT NOT NULL REFERENCES bookings(id),
    name TEXT NOT NULL DEFAULT '',
    passport_number TEXT NOT NULL DEFAULT '',
    emergency_contact TEXT NOT NULL DEFAULT '',
    checked_in INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cruise_sessions(id),
    booking_id TEXT NOT NULL REFERENCES bookings(id),
    amount REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending',
    method TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES cruise_sessions(id),
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


class CruiseDB:
    """SQLite persistence for mutable cruise booking state."""

    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # --- Sessions ---

    def create_session(self, acting_user_id: str = "") -> CruiseSession:
        sid = _uid("cs-")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO cruise_sessions (id, acting_user_id, created_at) VALUES (?, ?, ?)",
            (sid, acting_user_id, now),
        )
        self.conn.commit()
        return CruiseSession(id=sid, acting_user_id=acting_user_id, created_at=now)

    def get_session(self, session_id: str) -> CruiseSession | None:
        row = self.conn.execute(
            "SELECT * FROM cruise_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return CruiseSession(
            id=row["id"],
            acting_user_id=row["acting_user_id"],
            created_at=row["created_at"],
        )

    def update_session(self, session: CruiseSession) -> None:
        self.conn.execute(
            "UPDATE cruise_sessions SET acting_user_id=? WHERE id=?",
            (session.acting_user_id, session.id),
        )
        self.conn.commit()

    # --- Cruises ---

    def create_cruise(self, cruise: CruiseState) -> CruiseState:
        if not cruise.id:
            cruise.id = _uid("cr-")
        if not cruise.created_at:
            cruise.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO cruises
               (id, session_id, template_id, name, ship, departure_date, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cruise.id, cruise.session_id, cruise.template_id,
                cruise.name, cruise.ship, cruise.departure_date,
                cruise.status.value, cruise.created_at,
            ),
        )
        self.conn.commit()
        return cruise

    def get_cruise(self, cruise_id: str) -> CruiseState | None:
        row = self.conn.execute(
            "SELECT * FROM cruises WHERE id = ?", (cruise_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_cruise(row)

    def get_session_cruises(self, session_id: str) -> list[CruiseState]:
        rows = self.conn.execute(
            "SELECT * FROM cruises WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_cruise(r) for r in rows]

    def update_cruise(self, cruise: CruiseState) -> None:
        self.conn.execute(
            """UPDATE cruises
               SET name=?, ship=?, departure_date=?, status=?
               WHERE id=?""",
            (
                cruise.name, cruise.ship, cruise.departure_date,
                cruise.status.value, cruise.id,
            ),
        )
        self.conn.commit()

    def _row_to_cruise(self, row: sqlite3.Row) -> CruiseState:
        return CruiseState(
            id=row["id"],
            session_id=row["session_id"],
            template_id=row["template_id"],
            name=row["name"],
            ship=row["ship"],
            departure_date=row["departure_date"],
            status=CruiseStatus(row["status"]),
            created_at=row["created_at"],
        )

    # --- Bookings ---

    def create_booking(self, booking: BookingState) -> BookingState:
        if not booking.id:
            booking.id = _uid("bk-")
        now = datetime.now(timezone.utc).isoformat()
        if not booking.created_at:
            booking.created_at = now
        if not booking.updated_at:
            booking.updated_at = now
        self.conn.execute(
            """INSERT INTO bookings
               (id, session_id, cruise_id, cabin_type_id, cabin_number, status,
                lead_passenger_id, passenger_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                booking.id, booking.session_id, booking.cruise_id,
                booking.cabin_type_id, booking.cabin_number, booking.status.value,
                booking.lead_passenger_id, booking.passenger_count,
                booking.created_at, booking.updated_at,
            ),
        )
        self.conn.commit()
        return booking

    def get_booking(self, booking_id: str) -> BookingState | None:
        row = self.conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_booking(row)

    def get_session_bookings(self, session_id: str) -> list[BookingState]:
        rows = self.conn.execute(
            "SELECT * FROM bookings WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_booking(r) for r in rows]

    def get_cruise_bookings(self, cruise_id: str) -> list[BookingState]:
        rows = self.conn.execute(
            "SELECT * FROM bookings WHERE cruise_id = ?", (cruise_id,)
        ).fetchall()
        return [self._row_to_booking(r) for r in rows]

    def search_bookings(self, session_id: str, filters: dict) -> list[BookingState]:
        query = "SELECT * FROM bookings WHERE session_id = ?"
        params: list = [session_id]
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        if "cruise_id" in filters:
            query += " AND cruise_id = ?"
            params.append(filters["cruise_id"])
        if "cabin_type_id" in filters:
            query += " AND cabin_type_id = ?"
            params.append(filters["cabin_type_id"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_booking(r) for r in rows]

    def update_booking(self, booking: BookingState) -> None:
        booking.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE bookings
               SET cruise_id=?, cabin_type_id=?, cabin_number=?, status=?,
                   lead_passenger_id=?, passenger_count=?, updated_at=?
               WHERE id=?""",
            (
                booking.cruise_id, booking.cabin_type_id, booking.cabin_number,
                booking.status.value, booking.lead_passenger_id,
                booking.passenger_count, booking.updated_at, booking.id,
            ),
        )
        self.conn.commit()

    def _row_to_booking(self, row: sqlite3.Row) -> BookingState:
        return BookingState(
            id=row["id"],
            session_id=row["session_id"],
            cruise_id=row["cruise_id"],
            cabin_type_id=row["cabin_type_id"],
            cabin_number=row["cabin_number"],
            status=BookingStatus(row["status"]),
            lead_passenger_id=row["lead_passenger_id"],
            passenger_count=row["passenger_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Passengers ---

    def create_passenger(self, passenger: PassengerState) -> PassengerState:
        if not passenger.id:
            passenger.id = _uid("pax-")
        if not passenger.created_at:
            passenger.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO passengers
               (id, session_id, booking_id, name, passport_number,
                emergency_contact, checked_in, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                passenger.id, passenger.session_id, passenger.booking_id,
                passenger.name, passenger.passport_number,
                passenger.emergency_contact, int(passenger.checked_in),
                passenger.created_at,
            ),
        )
        self.conn.commit()
        return passenger

    def get_passenger(self, passenger_id: str) -> PassengerState | None:
        row = self.conn.execute(
            "SELECT * FROM passengers WHERE id = ?", (passenger_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_passenger(row)

    def get_booking_passengers(self, booking_id: str) -> list[PassengerState]:
        rows = self.conn.execute(
            "SELECT * FROM passengers WHERE booking_id = ?", (booking_id,)
        ).fetchall()
        return [self._row_to_passenger(r) for r in rows]

    def get_cruise_passengers(self, session_id: str, cruise_id: str) -> list[PassengerState]:
        rows = self.conn.execute(
            """SELECT p.* FROM passengers p
               JOIN bookings b ON p.booking_id = b.id
               WHERE p.session_id = ? AND b.cruise_id = ?""",
            (session_id, cruise_id),
        ).fetchall()
        return [self._row_to_passenger(r) for r in rows]

    def search_passengers(self, session_id: str, filters: dict) -> list[PassengerState]:
        query = "SELECT * FROM passengers WHERE session_id = ?"
        params: list = [session_id]
        if "booking_id" in filters:
            query += " AND booking_id = ?"
            params.append(filters["booking_id"])
        if "passport_number" in filters:
            query += " AND passport_number = ?"
            params.append(filters["passport_number"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_passenger(r) for r in rows]

    def update_passenger(self, passenger: PassengerState) -> None:
        self.conn.execute(
            """UPDATE passengers
               SET name=?, passport_number=?, emergency_contact=?, checked_in=?
               WHERE id=?""",
            (
                passenger.name, passenger.passport_number,
                passenger.emergency_contact, int(passenger.checked_in),
                passenger.id,
            ),
        )
        self.conn.commit()

    def _row_to_passenger(self, row: sqlite3.Row) -> PassengerState:
        return PassengerState(
            id=row["id"],
            session_id=row["session_id"],
            booking_id=row["booking_id"],
            name=row["name"],
            passport_number=row["passport_number"],
            emergency_contact=row["emergency_contact"],
            checked_in=bool(row["checked_in"]),
            created_at=row["created_at"],
        )

    # --- Payments ---

    def create_payment(self, payment: PaymentState) -> PaymentState:
        if not payment.id:
            payment.id = _uid("pay-")
        if not payment.created_at:
            payment.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO payments
               (id, session_id, booking_id, amount, status, method, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                payment.id, payment.session_id, payment.booking_id,
                payment.amount, payment.status.value, payment.method,
                payment.created_at,
            ),
        )
        self.conn.commit()
        return payment

    def get_payment(self, payment_id: str) -> PaymentState | None:
        row = self.conn.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_payment(row)

    def get_booking_payments(self, booking_id: str) -> list[PaymentState]:
        rows = self.conn.execute(
            "SELECT * FROM payments WHERE booking_id = ?", (booking_id,)
        ).fetchall()
        return [self._row_to_payment(r) for r in rows]

    def search_payments(self, session_id: str, filters: dict) -> list[PaymentState]:
        query = "SELECT * FROM payments WHERE session_id = ?"
        params: list = [session_id]
        if "booking_id" in filters:
            query += " AND booking_id = ?"
            params.append(filters["booking_id"])
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_payment(r) for r in rows]

    def update_payment(self, payment: PaymentState) -> None:
        self.conn.execute(
            """UPDATE payments SET amount=?, status=?, method=? WHERE id=?""",
            (payment.amount, payment.status.value, payment.method, payment.id),
        )
        self.conn.commit()

    def _row_to_payment(self, row: sqlite3.Row) -> PaymentState:
        return PaymentState(
            id=row["id"],
            session_id=row["session_id"],
            booking_id=row["booking_id"],
            amount=row["amount"],
            status=PaymentStatus(row["status"]),
            method=row["method"],
            created_at=row["created_at"],
        )

    # --- Cabin Availability ---

    def get_cabin_type_booking_count(
        self, session_id: str, cruise_id: str, cabin_type_id: str
    ) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*) as cnt FROM bookings
               WHERE session_id = ? AND cruise_id = ? AND cabin_type_id = ?
               AND status != ?""",
            (session_id, cruise_id, cabin_type_id, BookingStatus.cancelled.value),
        ).fetchone()
        return row["cnt"] if row else 0

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
