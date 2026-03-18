"""Runner — orchestrates eval runs across tasks and configurations."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from eval.backend.context import EvalContext
from eval.gas_server.server import EvalRuntime
from eval.trad_server.server import TradRuntime
from eval.tasks.oracle import check_oracle
from eval.tasks.schema import TaskDefinition
from eval.tasks.seeder import seed_task

from .agent import EvalAgent
from .config import EvalConfig, MatrixConfig
from .metrics import EvalMetrics
from .results_db import ResultsDB


def load_tasks(tiers: list[int] | None = None) -> list[TaskDefinition]:
    """Load task definitions from JSON files."""
    tasks_dir = Path(__file__).parent.parent / "tasks" / "definitions"
    tasks = []
    for tier_file in sorted(tasks_dir.glob("tier_*.json")):
        with open(tier_file) as f:
            tier_tasks = json.load(f)
        for t in tier_tasks:
            task = TaskDefinition(**t)
            if tiers is None or task.tier in tiers:
                tasks.append(task)
    return tasks


def run_single(config: EvalConfig, task: TaskDefinition) -> EvalMetrics:
    """Run a single eval: seed → run agent → check oracle → return metrics."""
    acting_user_id = task.acting_user_id or config.acting_user_id

    # Create fresh context and runtime
    if config.mode == "gas":
        runtime = EvalRuntime()
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx

        # Seed task scenario
        id_map = seed_task(ctx, session_id, task.setup)

        # Create and run agent
        agent = EvalAgent(config, gas_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)

    else:
        # Traditional mode
        tool_level = config.tool_level
        runtime = TradRuntime(tool_level=tool_level)
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx

        # Seed task scenario
        id_map = seed_task(ctx, session_id, task.setup)

        # Create and run agent
        agent = EvalAgent(config, trad_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)

    # Check oracle
    oracle_passed, oracle_details = check_oracle(ctx, session_id, task.oracle, id_map=id_map)
    metrics.task_id = task.id
    metrics.task_tier = task.tier
    metrics.oracle_passed = oracle_passed
    metrics.oracle_details = oracle_details

    return metrics


def run_suite(config: EvalConfig, tasks: list[TaskDefinition]) -> list[EvalMetrics]:
    """Run a suite of tasks with the same config."""
    results = []
    for i, task in enumerate(tasks):
        print(f"  [{i+1}/{len(tasks)}] {task.name} (tier {task.tier})...", end=" ", flush=True)
        metrics = run_single(config, task)
        status = "PASS" if metrics.oracle_passed else "FAIL"
        print(f"{status} ({metrics.total_turns} turns, {metrics.invalid_action_count} invalid, {metrics.elapsed_seconds:.1f}s)")
        results.append(metrics)
    return results


def run_matrix(
    matrix: MatrixConfig,
    results_db_path: str = "eval_results.db",
) -> ResultsDB:
    """Run the full eval matrix: models x modes x tasks."""
    tasks = load_tasks(matrix.task_tiers)
    db = ResultsDB(results_db_path)

    total_runs = len(matrix.models) * len(matrix.modes) * len(tasks) * matrix.runs_per_cell
    run_num = 0

    for model in matrix.models:
        for mode in matrix.modes:
            # Parse mode
            if mode == "gas":
                eval_mode = "gas"
                tool_level = 3
            else:
                eval_mode = "trad"
                tool_level = int(mode.split("-")[1])

            config = EvalConfig(
                mode=eval_mode,
                tool_level=tool_level,
                model=model,
            )

            print(f"\n{'='*60}")
            print(f"Model: {model.name} | Mode: {mode}")
            print(f"{'='*60}")

            for run_i in range(matrix.runs_per_cell):
                if matrix.runs_per_cell > 1:
                    print(f"\n--- Run {run_i + 1}/{matrix.runs_per_cell} ---")

                for task in tasks:
                    run_num += 1
                    print(f"  [{run_num}/{total_runs}] {task.name}...", end=" ", flush=True)

                    try:
                        metrics = run_single(config, task)
                        status = "PASS" if metrics.oracle_passed else "FAIL"
                        print(f"{status} ({metrics.total_turns}t, {metrics.invalid_action_count}inv, {metrics.elapsed_seconds:.1f}s)")
                        db.save_run(metrics)
                    except Exception as e:
                        print(f"ERROR: {e}")

    return db
