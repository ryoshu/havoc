"""Extract results from SQLite into DataFrames for analysis."""

from __future__ import annotations

import json

from eval.harness.results_db import ResultsDB


def results_to_records(db: ResultsDB) -> list[dict]:
    """Convert results DB rows to flat records suitable for DataFrame creation."""
    rows = db.get_all_runs()
    records = []
    for row in rows:
        records.append({
            "task_id": row["task_id"],
            "task_tier": row["task_tier"],
            "mode": row["mode"],
            "model_name": row["model_name"],
            "total_turns": row["total_turns"],
            "total_tokens": row["total_tokens_in"] + row["total_tokens_out"],
            "tokens_in": row["total_tokens_in"],
            "tokens_out": row["total_tokens_out"],
            "invalid_action_count": row["invalid_action_count"],
            "valid_action_count": row["valid_action_count"],
            "invalid_action_rate": row["invalid_action_rate"],
            "error_recovery_turns": row["error_recovery_turns"],
            "task_completed": bool(row["task_completed"]),
            "oracle_passed": bool(row["oracle_passed"]),
            "elapsed_seconds": row["elapsed_seconds"],
        })
    return records


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
