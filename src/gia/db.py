"""SQLite layer — mutable game state persistence."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from collections.abc import Iterator

from .models import (
    CharacterState,
    DecisionRecord,
    DiceRoll,
    EquipmentState,
    GamePhase,
    GameSession,
    InjuryState,
    ObjectiveState,
    SceneState,
    ThreatState,
)

SCHEMA = """\
CREATE TABLE IF NOT EXISTS game_sessions (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL DEFAULT 'setup',
    state_revision INTEGER NOT NULL DEFAULT 0,
    current_location_id TEXT,
    active_character_id TEXT,
    round_number INTEGER NOT NULL DEFAULT 0,
    scene_number INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_states (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES game_sessions(id),
    template_id TEXT NOT NULL,
    name TEXT NOT NULL,
    blood INTEGER NOT NULL DEFAULT 0,
    injuries_json TEXT NOT NULL DEFAULT '[]',
    equipment_json TEXT NOT NULL DEFAULT '[]',
    unlocked_advances_json TEXT NOT NULL DEFAULT '[]',
    flashback_used INTEGER NOT NULL DEFAULT 0,
    is_downed INTEGER NOT NULL DEFAULT 0,
    is_dead INTEGER NOT NULL DEFAULT 0,
    current_location_id TEXT
);

CREATE TABLE IF NOT EXISTS scene_states (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES game_sessions(id),
    location_id TEXT NOT NULL,
    active_threats_json TEXT NOT NULL DEFAULT '[]',
    active_objectives_json TEXT NOT NULL DEFAULT '[]',
    completed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dice_rolls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES game_sessions(id),
    character_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    pool_size INTEGER NOT NULL,
    results_json TEXT NOT NULL DEFAULT '[]',
    discarded_json TEXT NOT NULL DEFAULT '[]',
    kept_json TEXT NOT NULL DEFAULT '[]',
    allocations_json TEXT NOT NULL DEFAULT '{}',
    gm_pool_size INTEGER NOT NULL DEFAULT 0,
    gm_results_json TEXT NOT NULL DEFAULT '[]',
    gm_discarded_json TEXT NOT NULL DEFAULT '[]',
    gm_kept_json TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES game_sessions(id),
    actor_id TEXT NOT NULL,
    actor_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    affordances_snapshot_json TEXT NOT NULL DEFAULT '[]',
    affordances_not_taken_json TEXT NOT NULL DEFAULT '[]',
    result_summary TEXT NOT NULL DEFAULT '',
    events_json TEXT NOT NULL DEFAULT '[]',
    phase_before TEXT NOT NULL DEFAULT '',
    phase_after TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL,
    llm_narration TEXT NOT NULL DEFAULT '',
    llm_turn_context TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pending_rolls (
    session_id TEXT PRIMARY KEY REFERENCES game_sessions(id),
    roll_json TEXT NOT NULL,
    player_kept_json TEXT NOT NULL DEFAULT '[]',
    gm_kept_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


class GameDB:
    """SQLite persistence for mutable game state."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self.conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.executescript(SCHEMA)
        self._ensure_session_revision_column()

    def _ensure_session_revision_column(self) -> None:
        """Add the PR 3 revision column to databases created by older GIA versions."""
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(game_sessions)").fetchall()
        }
        if "state_revision" not in columns:
            self.conn.execute(
                "ALTER TABLE game_sessions ADD COLUMN state_revision INTEGER NOT NULL DEFAULT 0"
            )
            self._commit()

    def close(self):
        with self._lock:
            self.conn.close()

    @property
    def connection_lock(self) -> threading.RLock:
        """Lock shared by runtime operations using this SQLite connection."""
        return self._lock

    def _commit(self) -> None:
        if self._transaction_depth == 0:
            self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run a state transition atomically on this connection.

        A re-entrant lock serializes callers sharing one runtime connection;
        ``BEGIN IMMEDIATE`` prevents another SQLite writer from interleaving
        between revision validation and decision persistence.
        """
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                self.conn.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                yield
            except Exception:
                if outermost:
                    self.conn.rollback()
                raise
            else:
                if outermost:
                    self.conn.commit()
            finally:
                self._transaction_depth -= 1

    # --- Sessions ---

    def create_session(self) -> GameSession:
        sid = _uid("gs-")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO game_sessions (id, phase, created_at) VALUES (?, ?, ?)",
            (sid, GamePhase.setup.value, now),
        )
        self._commit()
        return GameSession(id=sid, phase=GamePhase.setup, created_at=now)

    def get_session(self, session_id: str) -> GameSession | None:
        row = self.conn.execute(
            "SELECT * FROM game_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return GameSession(
            id=row["id"],
            phase=GamePhase(row["phase"]),
            state_revision=row["state_revision"],
            current_location_id=row["current_location_id"],
            active_character_id=row["active_character_id"],
            round_number=row["round_number"],
            scene_number=row["scene_number"],
            created_at=row["created_at"],
        )

    def update_session(self, session: GameSession) -> None:
        self.conn.execute(
            """UPDATE game_sessions
               SET phase=?, state_revision=?, current_location_id=?, active_character_id=?,
                   round_number=?, scene_number=?
               WHERE id=?""",
            (
                session.phase.value,
                session.state_revision,
                session.current_location_id,
                session.active_character_id,
                session.round_number,
                session.scene_number,
                session.id,
            ),
        )
        self._commit()

    def claim_session_revision(self, session_id: str, expected_revision: int) -> bool:
        """Atomically claim a revision for one mutating operation."""
        cursor = self.conn.execute(
            """UPDATE game_sessions
               SET state_revision = state_revision + 1
               WHERE id = ? AND state_revision = ?""",
            (session_id, expected_revision),
        )
        self._commit()
        return cursor.rowcount == 1

    # --- Character States ---

    def add_character(self, cs: CharacterState) -> CharacterState:
        if not cs.id:
            cs.id = _uid("ch-")
        self.conn.execute(
            """INSERT INTO character_states
               (id, session_id, template_id, name, blood, injuries_json,
                equipment_json, unlocked_advances_json, flashback_used,
                is_downed, is_dead, current_location_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cs.id, cs.session_id, cs.template_id, cs.name, cs.blood,
                json.dumps([i.model_dump() for i in cs.injuries]),
                json.dumps([e.model_dump() for e in cs.equipment]),
                json.dumps(cs.unlocked_advances),
                int(cs.flashback_used), int(cs.is_downed), int(cs.is_dead),
                cs.current_location_id,
            ),
        )
        self._commit()
        return cs

    def get_character(self, char_id: str) -> CharacterState | None:
        row = self.conn.execute(
            "SELECT * FROM character_states WHERE id = ?", (char_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_character(row)

    def get_session_characters(self, session_id: str) -> list[CharacterState]:
        rows = self.conn.execute(
            "SELECT * FROM character_states WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_character(r) for r in rows]

    def update_character(self, cs: CharacterState) -> None:
        self.conn.execute(
            """UPDATE character_states
               SET blood=?, injuries_json=?, equipment_json=?,
                   unlocked_advances_json=?, flashback_used=?,
                   is_downed=?, is_dead=?, current_location_id=?
               WHERE id=?""",
            (
                cs.blood,
                json.dumps([i.model_dump() for i in cs.injuries]),
                json.dumps([e.model_dump() for e in cs.equipment]),
                json.dumps(cs.unlocked_advances),
                int(cs.flashback_used), int(cs.is_downed), int(cs.is_dead),
                cs.current_location_id, cs.id,
            ),
        )
        self._commit()

    def _row_to_character(self, row: sqlite3.Row) -> CharacterState:
        return CharacterState(
            id=row["id"],
            session_id=row["session_id"],
            template_id=row["template_id"],
            name=row["name"],
            blood=row["blood"],
            injuries=[InjuryState(**i) for i in json.loads(row["injuries_json"])],
            equipment=[EquipmentState(**e) for e in json.loads(row["equipment_json"])],
            unlocked_advances=json.loads(row["unlocked_advances_json"]),
            flashback_used=bool(row["flashback_used"]),
            is_downed=bool(row["is_downed"]),
            is_dead=bool(row["is_dead"]),
            current_location_id=row["current_location_id"],
        )

    # --- Scene States ---

    def create_scene(self, session_id: str, location_id: str,
                     threats: list[ThreatState],
                     objectives: list[ObjectiveState]) -> SceneState:
        sid = _uid("sc-")
        scene = SceneState(
            id=sid, session_id=session_id, location_id=location_id,
            active_threats=threats, active_objectives=objectives,
        )
        self.conn.execute(
            """INSERT INTO scene_states
               (id, session_id, location_id, active_threats_json,
                active_objectives_json, completed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                sid, session_id, location_id,
                json.dumps([t.model_dump() for t in threats]),
                json.dumps([o.model_dump() for o in objectives]),
                0,
            ),
        )
        self._commit()
        return scene

    def get_scene(self, scene_id: str) -> SceneState | None:
        row = self.conn.execute(
            "SELECT * FROM scene_states WHERE id = ?", (scene_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_scene(row)

    def get_active_scene(self, session_id: str) -> SceneState | None:
        row = self.conn.execute(
            "SELECT * FROM scene_states WHERE session_id = ? AND completed = 0 ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_scene(row)

    def update_scene(self, scene: SceneState) -> None:
        self.conn.execute(
            """UPDATE scene_states
               SET active_threats_json=?, active_objectives_json=?, completed=?
               WHERE id=?""",
            (
                json.dumps([t.model_dump() for t in scene.active_threats]),
                json.dumps([o.model_dump() for o in scene.active_objectives]),
                int(scene.completed),
                scene.id,
            ),
        )
        self._commit()

    def _row_to_scene(self, row: sqlite3.Row) -> SceneState:
        return SceneState(
            id=row["id"],
            session_id=row["session_id"],
            location_id=row["location_id"],
            active_threats=[ThreatState(**t) for t in json.loads(row["active_threats_json"])],
            active_objectives=[ObjectiveState(**o) for o in json.loads(row["active_objectives_json"])],
            completed=bool(row["completed"]),
        )

    # --- Dice Rolls ---

    def record_roll(self, roll: DiceRoll) -> DiceRoll:
        if not roll.id:
            roll.id = _uid("dr-")
        if not roll.timestamp:
            roll.timestamp = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO dice_rolls
               (id, session_id, character_id, scene_id, pool_size,
                results_json, discarded_json, kept_json, allocations_json,
                gm_pool_size, gm_results_json, gm_discarded_json, gm_kept_json,
                timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                roll.id, roll.session_id, roll.character_id, roll.scene_id,
                roll.pool_size,
                json.dumps(roll.results), json.dumps(roll.discarded),
                json.dumps(roll.kept), json.dumps(roll.allocations),
                roll.gm_pool_size,
                json.dumps(roll.gm_results), json.dumps(roll.gm_discarded),
                json.dumps(roll.gm_kept),
                roll.timestamp,
            ),
        )
        self._commit()
        return roll

    def get_session_rolls(self, session_id: str) -> list[DiceRoll]:
        rows = self.conn.execute(
            "SELECT * FROM dice_rolls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [self._row_to_roll(r) for r in rows]

    # --- Pending Rolls ---

    def save_pending_roll(
        self,
        session_id: str,
        roll: DiceRoll,
        player_kept: list[int],
        gm_kept: list[int],
    ) -> None:
        """Persist the roll that must survive between build and allocation."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO pending_rolls
               (session_id, roll_json, player_kept_json, gm_kept_json, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   roll_json=excluded.roll_json,
                   player_kept_json=excluded.player_kept_json,
                   gm_kept_json=excluded.gm_kept_json,
                   created_at=excluded.created_at""",
            (
                session_id,
                json.dumps(roll.model_dump(mode="json")),
                json.dumps(player_kept),
                json.dumps(gm_kept),
                now,
            ),
        )
        self._commit()

    def get_pending_roll(self, session_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM pending_rolls WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "roll": DiceRoll.model_validate(json.loads(row["roll_json"])),
            "player_kept": json.loads(row["player_kept_json"]),
            "gm_kept": json.loads(row["gm_kept_json"]),
        }

    def delete_pending_roll(self, session_id: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_rolls WHERE session_id = ?",
            (session_id,),
        )
        self._commit()

    # --- Decision Records ---

    def record_decision(self, decision: DecisionRecord) -> DecisionRecord:
        if not decision.id:
            decision.id = _uid("dc-")
        if not decision.timestamp:
            decision.timestamp = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO decision_records
               (id, session_id, actor_id, actor_name, action, params_json,
                affordances_snapshot_json, affordances_not_taken_json,
                result_summary, events_json, phase_before, phase_after, timestamp,
                llm_narration, llm_turn_context)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.id, decision.session_id, decision.actor_id,
                decision.actor_name, decision.action,
                json.dumps(decision.params),
                json.dumps(decision.affordances_snapshot),
                json.dumps(decision.affordances_not_taken),
                decision.result_summary,
                json.dumps(decision.events),
                decision.phase_before, decision.phase_after,
                decision.timestamp,
                decision.llm_narration,
                decision.llm_turn_context,
            ),
        )
        self._commit()
        return decision

    def update_last_decision_llm_context(
        self, session_id: str, narration: str, turn_context: str,
    ) -> None:
        """Attach LLM reasoning to the most recent decision in a session."""
        self.conn.execute(
            """UPDATE decision_records
               SET llm_narration = ?, llm_turn_context = ?
               WHERE id = (
                   SELECT id FROM decision_records
                   WHERE session_id = ?
                   ORDER BY timestamp DESC LIMIT 1
               )""",
            (narration, turn_context, session_id),
        )
        self.conn.commit()

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
            phase_before=row["phase_before"],
            phase_after=row["phase_after"],
            timestamp=row["timestamp"],
            llm_narration=row["llm_narration"],
            llm_turn_context=row["llm_turn_context"],
        )

    def _row_to_roll(self, row: sqlite3.Row) -> DiceRoll:
        return DiceRoll(
            id=row["id"],
            session_id=row["session_id"],
            character_id=row["character_id"],
            scene_id=row["scene_id"],
            pool_size=row["pool_size"],
            results=json.loads(row["results_json"]),
            discarded=json.loads(row["discarded_json"]),
            kept=json.loads(row["kept_json"]),
            allocations=json.loads(row["allocations_json"]),
            gm_pool_size=row["gm_pool_size"],
            gm_results=json.loads(row["gm_results_json"]),
            gm_discarded=json.loads(row["gm_discarded_json"]),
            gm_kept=json.loads(row["gm_kept_json"]),
            timestamp=row["timestamp"],
        )
