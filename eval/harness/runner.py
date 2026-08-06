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
from .config import DOMAIN_DEFAULT_USER, EvalConfig, MatrixConfig, parse_mode
from .design import CONDITIONS
from .metrics import EvalMetrics, TurnDetail
from .results_db import ResultsDB, _DEFAULT_DB


def load_tasks(tiers: list[int] | None = None, domain: str = "pm") -> list[TaskDefinition]:
    """Load task definitions from JSON files."""
    if domain == "cruise":
        tasks_dir = Path(__file__).parent.parent / "cruise_tasks" / "definitions"
    elif domain == "auto":
        tasks_dir = Path(__file__).parent.parent / "auto_tasks" / "definitions"
    else:
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

    if config.domain == "cruise":
        return _run_single_cruise(config, task, acting_user_id)
    if config.domain == "auto":
        return _run_single_auto(config, task, acting_user_id)

    # --- PM domain (default) ---
    if config.mode in {"gas-advisory", "gas-enforced", "gas-generic"}:
        runtime = EvalRuntime(
            mode=config.mode,
            advertise_capabilities=config.advertise_capabilities,
        )
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx
        id_map = seed_task(ctx, session_id, task.setup)
        agent = EvalAgent(config, gas_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)
    else:
        tool_level = config.tool_level
        runtime = TradRuntime(tool_level=tool_level, state_filtered=config.state_filtered)
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx
        id_map = seed_task(ctx, session_id, task.setup)
        agent = EvalAgent(config, trad_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)

    oracle_passed, oracle_details = check_oracle(ctx, session_id, task.oracle, id_map=id_map)
    metrics.task_id = task.id
    metrics.task_tier = task.tier
    metrics.oracle_passed = oracle_passed
    metrics.oracle_details = oracle_details
    return metrics


def _run_single_cruise(config: EvalConfig, task: TaskDefinition, acting_user_id: str) -> EvalMetrics:
    """Run a single cruise domain eval."""
    from eval.cruise_gas_server.server import CruiseGasRuntime
    from eval.cruise_trad_server.server import CruiseTradRuntime
    from eval.cruise_tasks.seeder import seed_cruise_task
    from eval.cruise_tasks.oracle import check_cruise_oracle

    if config.mode in {"gas-advisory", "gas-enforced", "gas-generic"}:
        runtime = CruiseGasRuntime(
            mode=config.mode,
            advertise_capabilities=config.advertise_capabilities,
        )
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx
        id_map = seed_cruise_task(ctx, session_id, task.setup)
        agent = EvalAgent(config, gas_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)
    else:
        tool_level = config.tool_level
        runtime = CruiseTradRuntime(tool_level=tool_level, state_filtered=config.state_filtered)
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx
        id_map = seed_cruise_task(ctx, session_id, task.setup)
        agent = EvalAgent(config, trad_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)

    oracle_passed, oracle_details = check_cruise_oracle(ctx, session_id, task.oracle, id_map=id_map)
    metrics.task_id = task.id
    metrics.task_tier = task.tier
    metrics.oracle_passed = oracle_passed
    metrics.oracle_details = oracle_details
    return metrics


def _run_single_auto(config: EvalConfig, task: TaskDefinition, acting_user_id: str) -> EvalMetrics:
    """Run a single auto domain eval."""
    from eval.auto_gas_server.server import AutoGasRuntime
    from eval.auto_trad_server.server import AutoTradRuntime
    from eval.auto_tasks.seeder import seed_auto_task
    from eval.auto_tasks.oracle import check_auto_oracle

    if config.mode in {"gas-advisory", "gas-enforced", "gas-generic"}:
        runtime = AutoGasRuntime(
            mode=config.mode,
            advertise_capabilities=config.advertise_capabilities,
        )
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx
        id_map = seed_auto_task(ctx, session_id, task.setup)
        agent = EvalAgent(config, gas_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)
    else:
        tool_level = config.tool_level
        runtime = AutoTradRuntime(tool_level=tool_level, state_filtered=config.state_filtered)
        session_id = runtime.create_session(acting_user_id=acting_user_id)
        ctx = runtime.ctx
        id_map = seed_auto_task(ctx, session_id, task.setup)
        agent = EvalAgent(config, trad_runtime=runtime)
        metrics = agent.run(task.description, session_id, max_turns=task.max_turns)

    oracle_passed, oracle_details = check_auto_oracle(ctx, session_id, task.oracle, id_map=id_map)
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
    results_db_path: str = _DEFAULT_DB,
    batch: str = "",
) -> ResultsDB:
    """Run the full eval matrix: models x modes x tasks."""
    tasks = load_tasks(matrix.task_tiers, domain=matrix.domain)
    db = ResultsDB(results_db_path)

    if matrix.conditions:
        condition_items = [
            (condition_id, CONDITIONS[condition_id])
            for condition_id in matrix.conditions
        ]
    else:
        # Preserve the pre-PR12 CLI: modes remain valid historical labels.
        condition_items = [
            (mode, None) for mode in matrix.modes
        ]

    total_runs = len(matrix.models) * len(condition_items) * len(tasks) * matrix.runs_per_cell
    run_num = 0

    for model in matrix.models:
        for condition_id, condition in condition_items:
            # Parse a legacy mode or use the pinned PR12 condition spec.
            if condition is None:
                eval_mode, tool_level = parse_mode(condition_id)
                if condition_id == "gas":
                    condition_id = "gas-advisory"
                advertise_capabilities = eval_mode != "gas-generic"
                state_filtered = False
            else:
                eval_mode, tool_level = condition.mode, condition.tool_level
                advertise_capabilities = condition.advertises_capabilities
                state_filtered = condition.filtering == "state"

            config = EvalConfig(
                domain=matrix.domain,
                mode=eval_mode,
                tool_level=tool_level,
                model=model,
                acting_user_id=DOMAIN_DEFAULT_USER.get(matrix.domain, "user-mgr-1"),
                condition=condition_id,
                experiment_id=matrix.experiment_id,
                history_policy=matrix.history_policy,
                retry_policy=matrix.retry_policy,
                advertise_capabilities=advertise_capabilities,
                state_filtered=state_filtered,
            )

            print(f"\n{'='*60}")
            print(f"Model: {model.name} | Condition: {condition_id}")
            print(f"{'='*60}")

            for run_i in range(matrix.runs_per_cell):
                if matrix.runs_per_cell > 1:
                    print(f"\n--- Run {run_i + 1}/{matrix.runs_per_cell} ---")

                for task in tasks:
                    run_num += 1
                    print(f"  [{run_num}/{total_runs}] {task.name}...", end=" ", flush=True)
                    config.run_seed = run_i

                    try:
                        metrics = run_single(config, task)
                        status = "PASS" if metrics.oracle_passed else "FAIL"
                        print(f"{status} ({metrics.total_turns}t, {metrics.invalid_action_count}inv, {metrics.elapsed_seconds:.1f}s)")
                        db.save_run(metrics, batch=batch)
                    except Exception as e:
                        print(f"ERROR: {e}")
                        # Persist hard failures so matrix coverage and failure rate
                        # are auditable instead of silently dropped.
                        failed = EvalMetrics(
                            task_id=task.id,
                            task_tier=task.tier,
                            mode=eval_mode if eval_mode in {"gas-advisory", "gas-enforced", "gas-generic"} else f"trad-{tool_level}",
                            model_name=model.name,
                            condition=condition_id,
                            experiment_id=matrix.experiment_id,
                            run_seed=run_i,
                            total_turns=1,
                            invalid_action_count=1,
                            invalid_request_count=1,
                            task_completed=False,
                            oracle_passed=False,
                            turns=[TurnDetail(
                                turn_number=1,
                                was_valid=False,
                                error_message=f"Runner exception: {e}",
                            )],
                            oracle_details=[{"error": str(e)}],
                        )
                        db.save_run(failed, batch=batch)

    return db
