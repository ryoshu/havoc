"""Fast behavioral contract tests for the GIA runtime.

These tests exercise the game runtime directly. They intentionally avoid LLMs,
network services, and MCP transports so later protocol refactors have a stable
behavioral baseline.
"""

from __future__ import annotations

import json

import pytest

from src.gia.server import GameRuntime


@pytest.fixture
def runtime():
    instance = GameRuntime()
    try:
        yield instance
    finally:
        instance.ctx.db.close()


def _result(payload: str) -> dict:
    return json.loads(payload)


def _actions(payload: dict) -> set[str]:
    return {item["action"] for item in payload.get("affordances", [])}


def test_initial_session_exposes_setup_state_and_affordances(runtime):
    result = _result(runtime.get("session"))

    assert result["data"]["id"] == runtime.default_session_id
    assert result["data"]["phase"] == "setup"
    assert "select_character" in _actions(result)
    assert "view_character_template" in _actions(result)
    assert "start_mission" not in _actions(result)


def test_character_search_uses_the_standard_response_envelope(runtime):
    result = _result(runtime.search("characters"))

    assert {"data", "affordances"} <= result.keys()
    assert {item["id"] for item in result["data"]} >= {"iryna", "chuck"}
    assert "select_character" in _actions(result)


def test_location_search_applies_sector_filter(runtime):
    result = _result(runtime.search("locations", '{"sector": 3}'))

    assert result["data"]
    assert {item["sector"] for item in result["data"]} == {3}


def test_setup_transition_records_decisions_and_enters_exploration(runtime):
    select_iryna = _result(
        runtime.act("select_character", '{"template_id": "iryna"}')
    )
    assert select_iryna["data"]["character_id"].startswith("ch-")
    assert "start_mission" in _actions(select_iryna)

    runtime.act("select_character", '{"template_id": "chuck"}')
    started = _result(runtime.act("start_mission"))
    session = _result(runtime.get("session"))

    assert started["data"]["active_character"] == "Iryna"
    assert session["data"]["phase"] == "exploration"
    assert session["data"]["round_number"] == 1
    assert session["data"]["scene_number"] == 1
    assert "engage_threat" in _actions(session)

    decisions = runtime.ctx.db.get_session_decisions(runtime.default_session_id)
    assert [decision.action for decision in decisions] == [
        "select_character",
        "select_character",
        "start_mission",
    ]


def test_duplicate_character_selection_returns_domain_error(runtime):
    runtime.act("select_character", '{"template_id": "iryna"}')

    result = _result(
        runtime.act("select_character", '{"template_id": "iryna"}')
    )

    assert result["error"] == "Character iryna already selected."
    assert "start_mission" in _actions(result)


def test_runtime_instances_are_isolated():
    first = GameRuntime()
    second = GameRuntime()
    try:
        first.act("select_character", '{"template_id": "iryna"}')

        first_state = _result(first.get("session"))
        second_state = _result(second.get("session"))

        assert first.default_session_id != second.default_session_id
        assert "start_mission" in _actions(first_state)
        assert "start_mission" not in _actions(second_state)
    finally:
        first.ctx.db.close()
        second.ctx.db.close()


@pytest.mark.xfail(
    strict=True,
    reason="PR 3 will reject known actions that are absent from current affordances",
)
def test_known_but_unavailable_action_is_rejected(runtime):
    runtime.act("select_character", '{"template_id": "iryna"}')
    runtime.act("start_mission")

    result = _result(
        runtime.act("select_character", '{"template_id": "chuck"}')
    )

    assert "error" in result
    assert "not currently available" in result["error"]


@pytest.mark.xfail(
    strict=True,
    reason="PR 2 will replace encoded JSON parameters and surface typed errors",
)
def test_malformed_action_parameters_return_a_domain_error(runtime):
    result = _result(runtime.act("select_character", "{not-json"))

    assert "error" in result
    assert "parameter" in result["error"].lower()
