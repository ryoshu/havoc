"""Extract results from SQLite into DataFrames for analysis."""

from __future__ import annotations

import json

from eval.harness.providers import LEGACY_NAME_MAP, MODEL_ORDER
from eval.harness.results_db import ResultsDB

# Canonical model names that should appear in charts/reports.
_CANONICAL_MODELS: set[str] = set(MODEL_ORDER)


def _normalize_model_name(name: str) -> str:
    """Map legacy DB names to current canonical names."""
    return LEGACY_NAME_MAP.get(name, name)


def results_to_records(db: ResultsDB) -> list[dict]:
    """Convert results DB rows to flat records suitable for DataFrame creation.

    Applies two filters to keep charts consistent with curated reports:
    1. Only includes models present in MODEL_ORDER (the active catalog).
    2. Deduplicates by (model_name, mode, task_id), keeping the latest run.
    """
    rows = db.get_all_runs()  # ordered by created_at

    # Build records, filtering to canonical models
    records = []
    for row in rows:
        model = _normalize_model_name(row["model_name"])
        if model not in _CANONICAL_MODELS:
            continue
        records.append({
            "task_id": row["task_id"],
            "task_tier": row["task_tier"],
            "mode": row["mode"],
            # Historical rows predate the condition column; their canonical
            # mode is the only safe condition label available.
            "condition": row.get("condition") or row["mode"],
            "experiment_id": row.get("experiment_id", ""),
            "run_seed": row.get("run_seed", 0),
            "model_name": model,
            "total_turns": row["total_turns"],
            "total_tokens": row["total_tokens_in"] + row["total_tokens_out"],
            "tokens_in": row["total_tokens_in"],
            "tokens_out": row["total_tokens_out"],
            "invalid_action_count": row["invalid_action_count"],
            "invalid_request_count": row.get("invalid_request_count", 0),
            "invalid_state_transition_count": row.get("invalid_state_transition_count", 0),
            "valid_action_count": row["valid_action_count"],
            "invalid_action_rate": row["invalid_action_rate"],
            "error_recovery_turns": row["error_recovery_turns"],
            "task_completed": bool(row["task_completed"]),
            "oracle_passed": bool(row["oracle_passed"]),
            "elapsed_seconds": row["elapsed_seconds"],
        })

    # Deduplicate: keep latest run per (model, condition, task).  Condition is
    # part of the key so a factorial matrix cannot silently collapse cells.
    # Records are ordered by created_at (from get_all_runs), so last wins.
    seen: dict[tuple[str, str, str], int] = {}
    for i, rec in enumerate(records):
        key = (rec["model_name"], rec["condition"], rec["task_id"])
        seen[key] = i  # overwrites earlier duplicates

    return [records[i] for i in sorted(seen.values())]


def try_import_pandas():
    """Import pandas, return None if not available."""
    try:
        import pandas as pd
        return pd
    except ImportError:
        return None


def results_to_dataframe(db: ResultsDB):
    """Convert results to a pandas DataFrame (requires pandas)."""
    pd = try_import_pandas()
    if pd is None:
        raise ImportError("pandas is required for DataFrame extraction. Install with: pip install pandas")
    records = results_to_records(db)
    return pd.DataFrame(records)
