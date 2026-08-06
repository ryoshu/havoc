"""Offline coverage for the PR12 controlled factorial harness."""

from __future__ import annotations

import json
from pathlib import Path

from eval.backend.context import EvalContext
from eval.gas_server.server import EvalRuntime
from eval.harness.agent import EvalAgent
from eval.harness.config import EvalConfig, ModelConfig, parse_mode
from eval.harness.controls import RetryPolicy
from eval.harness.design import CONDITIONS, build_cells, snapshot_design
from eval.harness.metrics import EvalMetrics, TurnDetail
from eval.harness.results_db import ResultsDB
from eval.tasks.oracle import check_oracle
from eval.tasks.seeder import seed_task
from eval.harness.runner import load_tasks
from eval.trad_server.server import TradRuntime


def _model() -> ModelConfig:
    return ModelConfig(
        name="offline",
        model="offline-model",
        api_base="http://127.0.0.1",
        api_key="test",
    )


def test_pr12_conditions_are_balanced_and_modes_are_backward_compatible():
    assert parse_mode("gas") == ("gas-advisory", 3)
    assert parse_mode("generic") == ("gas-generic", 3)
    assert parse_mode("state-filtered-native") == ("trad", 15)
    cells = build_cells(
        domains=["pm"], conditions=list(CONDITIONS), task_tiers=[1, 2], runs_per_cell=2
    )
    assert len(cells) == 5 * 2 * 2
    assert {cell.condition for cell in cells} == set(CONDITIONS)


def test_generic_gas_withholds_capabilities_but_advisory_preserves_them():
    generic = EvalRuntime(mode="gas-generic", advertise_capabilities=False)
    advisory = EvalRuntime(mode="gas-advisory", advertise_capabilities=True)
    try:
        generic_sid = generic.create_session("user-mgr-1")
        advisory_sid = advisory.create_session("user-mgr-1")
        generic_result = json.loads(generic.get("session", generic_sid, generic_sid))
        advisory_result = json.loads(advisory.get("session", advisory_sid, advisory_sid))
        assert "affordances" not in generic_result
        assert "affordances" in advisory_result
    finally:
        generic.ctx.db.close()
        advisory.ctx.db.close()


def test_state_filtered_native_projects_current_affordances():
    runtime = TradRuntime(state_filtered=True, tool_level=15)
    try:
        session_id = runtime.create_session("user-mgr-1")
        seed_task(
            runtime.ctx,
            session_id,
            {
                "projects": [{"id": "proj-alpha", "template_id": "proj-alpha", "alias": "alpha"}],
                "issues": [{
                    "id": "iss-open", "title": "Open issue", "project_id": "proj-alpha",
                    "status": "open", "priority": "p2", "alias": "open",
                }],
            },
        )
        names = {tool["function"]["name"] for tool in runtime.get_tool_definitions(session_id)}
        assert "get_issue" in names
        assert "transition_issue" not in names  # not a native tool at level 15
        assert "close_issue" not in names  # open → closed is not currently afforded
        assert "create_issue" in names
    finally:
        runtime.ctx.db.close()


def test_same_seeded_case_has_the_same_oracle_across_renderers():
    task = next(task for task in load_tasks([1]) if task.id == "t1-01")
    params = {
        "project_id": "proj-alpha",
        "title": "Login page timeout",
        "description": "",
        "priority": "p2",
    }
    outcomes = []
    gas = EvalRuntime(mode="gas-advisory")
    native = TradRuntime(tool_level=15)
    try:
        gas_sid = gas.create_session("user-mgr-1")
        native_sid = native.create_session("user-mgr-1")
        gas_map = seed_task(gas.ctx, gas_sid, task.setup)
        native_map = seed_task(native.ctx, native_sid, task.setup)
        json.loads(gas.act("create_issue", json.dumps(params), gas_sid))
        native_result = json.loads(native.call_tool("create_issue", params, native_sid))
        assert "error" not in native_result
        outcomes.append(check_oracle(gas.ctx, gas_sid, task.oracle, id_map=gas_map)[0])
        outcomes.append(check_oracle(native.ctx, native_sid, task.oracle, id_map=native_map)[0])
        assert outcomes == [True, True]
    finally:
        gas.ctx.db.close()
        native.ctx.db.close()


def test_retry_policy_and_history_policy_are_pinned():
    policy = RetryPolicy(max_attempts=3, backoff_seconds=(0.0, 0.25))
    assert policy.delay_for(0) == 0.0
    assert policy.delay_for(10) == 0.25
    assert policy.delay_for(1, retry_after=2.5) == 2.5

    config = EvalConfig(mode="gas-generic", model=_model(), history_policy="full")
    agent = EvalAgent(config, gas_runtime=EvalRuntime(mode="gas-generic", advertise_capabilities=False))
    assert "affordances" not in agent._get_tools()[0]["function"]["description"]
    assert config.history_policy == "full"


def test_snapshot_records_fixtures_harness_and_provider_pin(tmp_path: Path):
    snapshot = snapshot_design(
        Path(__file__).resolve().parents[1],
        models=[_model()], domains=("pm",), task_tiers=(1, 2),
    )
    assert snapshot.code_commit
    assert len(snapshot.fixture_digest) == 64
    assert len(snapshot.harness_digest) == 64
    assert snapshot.provider_models["offline"]["model"] == "offline-model"
    assert set(snapshot.conditions) == set(CONDITIONS)


def test_results_store_condition_seed_and_transcript(tmp_path: Path):
    db = ResultsDB(str(tmp_path / "results.db"))
    try:
        metrics = EvalMetrics(
            task_id="t1-01", task_tier=1, mode="gas-advisory", condition="gas-advisory",
            experiment_id="pr12-test", run_seed=7, model_name="offline",
            turns=[TurnDetail(turn_number=1, action="get")],
            transcript=[{"role": "user", "content": "task"}],
        )
        db.save_run(metrics)
        row = db.get_all_runs()[0]
        assert row["condition"] == "gas-advisory"
        assert row["experiment_id"] == "pr12-test"
        assert row["run_seed"] == 7
        assert json.loads(row["transcript_json"])[0]["role"] == "user"
    finally:
        db.close()
