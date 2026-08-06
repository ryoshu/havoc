"""Regression coverage for the advisory/enforced GAS evaluation split."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.auto_gas_server.server import AutoGasRuntime
from eval.cruise_gas_server.server import CruiseGasRuntime
from eval.gas_server.contracts import GasActionResponse, GasErrorResponse, GasResourceResponse
from eval.gas_server.server import EvalRuntime
from eval.harness.agent import EvalAgent
from eval.harness.config import EvalConfig, ModelConfig, parse_mode
from eval.harness.metrics import EvalMetrics
from eval.harness.results_db import ResultsDB


RUNTIMES = (EvalRuntime, CruiseGasRuntime, AutoGasRuntime)


@pytest.fixture(params=RUNTIMES)
def enforced_runtime(request):
    runtime = request.param(mode="gas-enforced")
    acting_user = "user-agent-1" if request.param is CruiseGasRuntime else "user-mgr-1"
    session_id = runtime.create_session(acting_user)
    try:
        yield runtime, session_id
    finally:
        runtime.ctx.db.close()


def test_enforced_mode_requires_explicit_session(enforced_runtime):
    runtime, session_id = enforced_runtime

    missing = runtime.act_enforced("unknown_action", {}, session_id="", expected_revision=0)
    assert isinstance(missing, GasErrorResponse)
    assert missing.error.code == "invalid_input"

    unavailable = runtime.act_enforced("unknown_action", {}, session_id=session_id, expected_revision=0)
    assert isinstance(unavailable, GasErrorResponse)
    assert unavailable.error.code == "action_unavailable"
    assert unavailable.mode == "gas-enforced"


def test_enforced_reads_are_typed_and_revision_errors_are_normalized(enforced_runtime):
    runtime, session_id = enforced_runtime

    state = runtime.get_enforced("session", session_id=session_id)
    assert isinstance(state, GasResourceResponse)
    assert state.mode == "gas-enforced"
    assert state.state_revision == 0

    stale = runtime.act_enforced(
        "unknown_action",
        {},
        session_id=session_id,
        expected_revision=1,
    )
    assert isinstance(stale, GasErrorResponse)
    assert stale.error.code == "stale_state"
    assert stale.error.details["current_revision"] == 0


def test_advisory_mode_remains_the_legacy_default():
    runtime = EvalRuntime()
    try:
        session_id = runtime.create_session("user-mgr-1")
        assert runtime.mode == "gas-advisory"
        assert runtime.default_session_id == session_id
    finally:
        runtime.ctx.db.close()


def test_harness_labels_and_tool_schema_distinguish_gas_modes():
    assert parse_mode("gas") == ("gas-advisory", 3)
    assert parse_mode("gas-enforced") == ("gas-enforced", 3)
    config = EvalConfig(
        mode="gas-enforced",
        model=ModelConfig(
            name="test", model="test", api_base="http://127.0.0.1", api_key="test"
        ),
    )
    agent = EvalAgent(config, gas_runtime=EvalRuntime(mode="gas-enforced"))
    tools = {tool["function"]["name"]: tool for tool in agent._get_tools()}
    assert "expected_revision" in tools["act"]["function"]["parameters"]["required"]
    assert tools["act"]["function"]["parameters"]["properties"]["params"]["type"] == "object"


def test_enforced_eval_action_advances_revision_and_rejects_replay():
    runtime = EvalRuntime(mode="gas-enforced")
    try:
        session_id = runtime.create_session("user-mgr-1")
        project = runtime.ctx.create_project_from_template(session_id, "proj-alpha")
        params = {
            "project_id": project.id,
            "title": "Enforced contract regression",
            "description": "",
            "priority": "p3",
        }
        result = runtime.act_enforced(
            "create_issue", params, session_id=session_id, expected_revision=0
        )
        assert isinstance(result, GasActionResponse)
        assert result.state_revision == 1

        replay = runtime.act_enforced(
            "create_issue", params, session_id=session_id, expected_revision=0
        )
        assert isinstance(replay, GasErrorResponse)
        assert replay.error.code == "stale_state"
    finally:
        runtime.ctx.db.close()


def test_results_store_normalizes_advisory_history(tmp_path: Path):
    db = ResultsDB(str(tmp_path / "results.db"))
    try:
        legacy = EvalMetrics(mode="gas", model_name="legacy")
        db.save_run(legacy)
        assert db.get_summary()["gas-advisory"]["run_count"] == 1
        assert len(db.get_runs_by_mode("gas-advisory")) == 1
    finally:
        db.close()
