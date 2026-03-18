"""SQLite results store for eval runs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
_DEFAULT_DB = str(_RESULTS_DIR / "eval_results.db")

from .metrics import EvalMetrics

RESULTS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    task_tier INTEGER NOT NULL,
    mode TEXT NOT NULL,
    model_name TEXT NOT NULL,
    total_turns INTEGER NOT NULL DEFAULT 0,
    total_tokens_in INTEGER NOT NULL DEFAULT 0,
    total_tokens_out INTEGER NOT NULL DEFAULT 0,
    invalid_action_count INTEGER NOT NULL DEFAULT 0,
    valid_action_count INTEGER NOT NULL DEFAULT 0,
    error_recovery_turns INTEGER NOT NULL DEFAULT 0,
    time_to_first_valid INTEGER NOT NULL DEFAULT 0,
    redundant_calls INTEGER NOT NULL DEFAULT 0,
    affordance_utilization REAL NOT NULL DEFAULT 0.0,
    task_completed INTEGER NOT NULL DEFAULT 0,
    oracle_passed INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds REAL NOT NULL DEFAULT 0.0,
    invalid_action_rate REAL NOT NULL DEFAULT 0.0,
    turns_json TEXT NOT NULL DEFAULT '[]',
    oracle_details_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT ''
);
"""


class ResultsDB:
    """SQLite store for eval results."""

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(RESULTS_SCHEMA)

    def close(self):
        self.conn.close()

    def save_run(self, metrics: EvalMetrics) -> str:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO runs
               (id, task_id, task_tier, mode, model_name,
                total_turns, total_tokens_in, total_tokens_out,
                invalid_action_count, valid_action_count,
                error_recovery_turns, time_to_first_valid,
                redundant_calls, affordance_utilization,
                task_completed, oracle_passed, elapsed_seconds,
                invalid_action_rate, turns_json, oracle_details_json,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, metrics.task_id, metrics.task_tier,
                metrics.mode, metrics.model_name,
                metrics.total_turns, metrics.total_tokens_in,
                metrics.total_tokens_out, metrics.invalid_action_count,
                metrics.valid_action_count, metrics.error_recovery_turns,
                metrics.time_to_first_valid_action, metrics.redundant_calls,
                metrics.affordance_utilization,
                int(metrics.task_completed), int(metrics.oracle_passed),
                metrics.elapsed_seconds, metrics.invalid_action_rate,
                json.dumps([t.model_dump() for t in metrics.turns]),
                json.dumps(metrics.oracle_details),
                now,
            ),
        )
        self.conn.commit()
        return run_id

    def get_all_runs(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def get_runs_by_mode(self, mode: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE mode = ? ORDER BY created_at",
            (mode,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self) -> dict:
        """Aggregate summary across all runs, grouped by mode."""
        rows = self.conn.execute("""
            SELECT mode,
                   COUNT(*) as run_count,
                   SUM(invalid_action_count) as invalid_count,
                   SUM(valid_action_count) as valid_count,
                   AVG(total_turns) as avg_turns,
                   AVG(total_tokens_in + total_tokens_out) as avg_tokens,
                   SUM(oracle_passed) as oracle_pass_count,
                   SUM(task_completed) as task_complete_count,
                   AVG(elapsed_seconds) as avg_time
            FROM runs
            GROUP BY mode
            ORDER BY mode
        """).fetchall()
        return {
            r["mode"]: {
                "run_count": r["run_count"],
                # Weighted invalid rate across all calls in the mode.
                "avg_invalid_rate": (
                    r["invalid_count"] / (r["invalid_count"] + r["valid_count"])
                    if (r["invalid_count"] + r["valid_count"]) else 0
                ),
                "avg_turns": r["avg_turns"],
                "avg_tokens": r["avg_tokens"],
                "oracle_pass_rate": r["oracle_pass_count"] / r["run_count"] if r["run_count"] else 0,
                "task_complete_rate": r["task_complete_count"] / r["run_count"] if r["run_count"] else 0,
                "avg_time": r["avg_time"],
            }
            for r in rows
        }
