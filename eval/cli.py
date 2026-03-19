"""CLI entry point for the GAS eval framework.

Usage:
    python -m eval run --mode gas --model gpt-4o --tiers 1 3
    python -m eval run --mode trad-15 --model glm-5 --tiers 1
    python -m eval matrix --models gpt-4o glm-5 --modes gas trad-15 trad-30 --tiers 1 3
    python -m eval summary
    python -m eval charts
    python -m eval list-tasks
    python -m eval list-models
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# All results default to eval/results/ relative to this package.
_EVAL_DIR = Path(__file__).resolve().parent
_RESULTS_DIR = _EVAL_DIR / "results"
_DEFAULT_DB = str(_RESULTS_DIR / "eval_results.db")
_DEFAULT_CHARTS = str(_RESULTS_DIR / "charts")

from eval.harness.config import EvalConfig, MatrixConfig, parse_mode
from eval.harness.providers import get_available_models, get_model_by_name, print_available_models
from eval.harness.results_db import ResultsDB
from eval.harness.runner import load_tasks, run_matrix, run_suite


def cmd_run(args):
    """Run eval suite with a single config."""
    model = get_model_by_name(args.model)
    if not model:
        print(f"Model '{args.model}' not found.", file=sys.stderr)
        print_available_models()
        sys.exit(1)

    # Parse mode
    eval_mode, tool_level = parse_mode(args.mode)

    config = EvalConfig(
        mode=eval_mode,
        tool_level=tool_level,
        model=model,
        acting_user_id=args.user,
    )

    tiers = [int(t) for t in args.tiers] if args.tiers else None
    tasks = load_tasks(tiers)

    if args.tasks:
        task_ids = set(args.tasks)
        tasks = [t for t in tasks if t.id in task_ids]

    if not tasks:
        print("No tasks found for specified tiers.", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(tasks)} tasks | Mode: {args.mode} | Model: {model.name}")
    print(f"Acting as: {config.acting_user_id}")
    print()

    results = run_suite(config, tasks)

    # Save results
    batch = args.batch or ""
    db = ResultsDB(args.db)
    for r in results:
        db.save_run(r, batch=batch)
    db.close()

    # Print summary
    passed = sum(1 for r in results if r.oracle_passed)
    total_invalid = sum(r.invalid_action_count for r in results)
    total_valid = sum(r.valid_action_count for r in results)
    rate = total_invalid / (total_invalid + total_valid) if (total_invalid + total_valid) else 0

    print(f"\nResults: {passed}/{len(results)} oracle passed")
    print(f"Invalid action rate: {rate:.1%} ({total_invalid}/{total_invalid + total_valid})")
    print(f"Saved to: {args.db}")


def cmd_matrix(args):
    """Run full eval matrix."""
    models = []
    for name in args.models:
        m = get_model_by_name(name)
        if m:
            models.append(m)
        else:
            print(f"Warning: model '{name}' not found, skipping.", file=sys.stderr)

    if not models:
        print("No valid models found.", file=sys.stderr)
        print_available_models()
        sys.exit(1)

    matrix = MatrixConfig(
        models=models,
        modes=args.modes,
        task_tiers=[int(t) for t in args.tiers] if args.tiers else [1, 3],
        runs_per_cell=args.runs,
    )

    print(f"Matrix: {len(models)} models x {len(matrix.modes)} modes x {len(load_tasks(matrix.task_tiers))} tasks x {matrix.runs_per_cell} runs")
    print()

    db = run_matrix(matrix, args.db, batch=args.batch or "")
    summary = db.get_summary()
    db.close()

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for mode, stats in summary.items():
        print(f"\n{mode}:")
        print(f"  Runs: {stats['run_count']}")
        print(f"  Avg invalid rate: {stats['avg_invalid_rate']:.1%}")
        print(f"  Oracle pass rate: {stats['oracle_pass_rate']:.1%}")
        print(f"  Avg turns: {stats['avg_turns']:.1f}")
        print(f"  Avg tokens: {stats['avg_tokens']:.0f}")
        print(f"  Avg time: {stats['avg_time']:.1f}s")


def cmd_summary(args):
    """Print summary from results DB."""
    db = ResultsDB(args.db)
    summary = db.get_summary()
    db.close()

    if not summary:
        print("No results found.")
        return

    print(f"{'Mode':<12} {'Runs':>5} {'Invalid%':>9} {'Oracle%':>8} {'Turns':>6} {'Tokens':>8} {'Time':>6}")
    print("-" * 60)
    for mode, stats in summary.items():
        print(
            f"{mode:<12} {stats['run_count']:>5} "
            f"{stats['avg_invalid_rate']:>8.1%} "
            f"{stats['oracle_pass_rate']:>7.1%} "
            f"{stats['avg_turns']:>6.1f} "
            f"{stats['avg_tokens']:>8.0f} "
            f"{stats['avg_time']:>5.1f}s"
        )


def cmd_charts(args):
    """Generate charts from results DB."""
    from eval.analysis.charts import generate_all_charts
    from eval.analysis.extract import results_to_dataframe

    db = ResultsDB(args.db)
    df = results_to_dataframe(db)
    db.close()

    if df.empty:
        print("No results to chart.")
        return

    paths = generate_all_charts(df, args.output)
    for p in paths:
        print(f"Generated: {p}")


def cmd_list_tasks(args):
    """List all available tasks."""
    tiers = [int(t) for t in args.tiers] if args.tiers else None
    tasks = load_tasks(tiers)
    for t in tasks:
        print(f"  [{t.tier}] {t.id}: {t.name}")
    print(f"\nTotal: {len(tasks)} tasks")


def cmd_list_models(args):
    """List available models."""
    print_available_models()


def main():
    parser = argparse.ArgumentParser(description="GAS Eval Framework")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run eval suite with a single config")
    p_run.add_argument("--mode", default="gas", help="gas, trad-15, trad-30, trad-60, trad-60-poly, trad-120d, trad-240d, trad-480d")
    p_run.add_argument("--model", default="gpt-4o", help="Model name or alias")
    p_run.add_argument("--tiers", nargs="+", default=None, help="Task tiers to run")
    p_run.add_argument("--tasks", nargs="+", default=None, help="Specific task IDs to run")
    p_run.add_argument("--user", default="user-mgr-1", help="Acting user ID")
    p_run.add_argument("--db", default=_DEFAULT_DB, help="Results DB path")
    p_run.add_argument("--batch", default="", help="Batch label for this run (e.g. 'glm5-rerun-v2')")
    p_run.set_defaults(func=cmd_run)

    # matrix
    p_matrix = sub.add_parser("matrix", help="Run full eval matrix")
    p_matrix.add_argument("--models", nargs="+", default=["gpt-4o"])
    p_matrix.add_argument("--modes", nargs="+", default=["gas", "trad-15"])
    p_matrix.add_argument("--tiers", nargs="+", default=None)
    p_matrix.add_argument("--runs", type=int, default=1, help="Runs per cell")
    p_matrix.add_argument("--db", default=_DEFAULT_DB)
    p_matrix.add_argument("--batch", default="", help="Batch label for this run")
    p_matrix.set_defaults(func=cmd_matrix)

    # summary
    p_summary = sub.add_parser("summary", help="Print results summary")
    p_summary.add_argument("--db", default=_DEFAULT_DB)
    p_summary.set_defaults(func=cmd_summary)

    # charts
    p_charts = sub.add_parser("charts", help="Generate charts")
    p_charts.add_argument("--db", default=_DEFAULT_DB)
    p_charts.add_argument("--output", default=_DEFAULT_CHARTS)
    p_charts.set_defaults(func=cmd_charts)

    # list-tasks
    p_lt = sub.add_parser("list-tasks", help="List available tasks")
    p_lt.add_argument("--tiers", nargs="+", default=None)
    p_lt.set_defaults(func=cmd_list_tasks)

    # list-models
    p_lm = sub.add_parser("list-models", help="List available models")
    p_lm.set_defaults(func=cmd_list_models)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
