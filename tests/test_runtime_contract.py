"""Fast behavioral contract tests for the GIA runtime.

These tests exercise the game runtime directly. They intentionally avoid LLMs,
network services, and MCP transports so later protocol refactors have a stable
behavioral baseline.
"""

from __future__ import annotations

import json

import pytest

from src.gia.compat import JsonGameRuntimeAdapter
from src.gia.domain import (
    InvalidInputError,
    InvalidParameterError,
    ResourceNotFoundError,
    StaleStateError,
    UnavailableActionError,
)
from src.gia.responses import ActionResponse, ResourceResponse
from src.gia.server import GameRuntime


@pytest.fixture
def runtime():
    instance = GameRuntime()
    instance.session_id = instance.create_session().data["id"]
    try:
        yield instance
    finally:
        instance.ctx.db.close()


def _result(payload: ResourceResponse) -> dict:
    return payload.model_dump(mode="json", by_alias=True)


def _actions(payload: dict) -> set[str]:
    return {item["action"] for item in payload.get("affordances", [])}


def _act(runtime: GameRuntime, action: str, params: dict | None = None):
    revision = runtime.get("session", session_id=runtime.session_id).state_revision
    return runtime.act(
        action,
        params or {},
        session_id=runtime.session_id,
        expected_revision=revision,
    )


def test_initial_session_exposes_setup_state_and_affordances(runtime):
    response = runtime.get("session", session_id=runtime.session_id)
    result = _result(response)

    assert isinstance(response, ResourceResponse)
    assert result["data"]["id"] == runtime.session_id
    assert result["data"]["phase"] == "setup"
    assert result["state_revision"] == 0
    assert "select_character" in _actions(result)
    assert "view_character_template" in _actions(result)
    assert "start_mission" not in _actions(result)
    assert all(
        affordance["schema"]["type"] == "object"
        and affordance["schema"]["additionalProperties"] is False
        and "id" in affordance
        for affordance in result["affordances"]
    )
    assert len({affordance["id"] for affordance in result["affordances"]}) == len(result["affordances"])


def test_sessions_are_created_explicitly_and_isolated():
    runtime = GameRuntime()
    try:
        first = _result(runtime.create_session())
        second = _result(runtime.create_session())

        assert first["data"]["id"] != second["data"]["id"]
        assert first["state_revision"] == second["state_revision"] == 0
        assert "select_character" in _actions(first)

        _act_for_session(runtime, first["data"]["id"], "select_character", {"template_id": "iryna"})
        second_state = _result(runtime.get("session", session_id=second["data"]["id"]))
        assert "start_mission" not in _actions(second_state)
    finally:
        runtime.ctx.db.close()


def _act_for_session(runtime: GameRuntime, session_id: str, action: str, params: dict | None = None):
    revision = runtime.get("session", session_id=session_id).state_revision
    return runtime.act(
        action,
        params or {},
        session_id=session_id,
        expected_revision=revision,
    )


def test_stateful_operations_require_a_session_handle(runtime):
    with pytest.raises(InvalidInputError, match="session_id is required"):
        runtime.get("session")
    with pytest.raises(InvalidInputError, match="session_id is required"):
        runtime.act("select_character", {"template_id": "iryna"}, expected_revision=0)


def test_immutable_knowledge_reads_do_not_require_a_session(runtime):
    response = runtime.get("character_template", "iryna")
    assert response.state_revision is None
    assert response.affordances == []

    search = runtime.search("locations", {"sector": 3})
    assert search.state_revision is None
    assert search.affordances == []


def test_affordance_ids_are_stable_across_reads(runtime):
    first = _result(runtime.get("session", session_id=runtime.session_id))
    second = _result(runtime.get("session", session_id=runtime.session_id))

    assert [item["id"] for item in first["affordances"]] == [
        item["id"] for item in second["affordances"]
    ]


def test_character_search_uses_the_standard_response_envelope(runtime):
    result = _result(runtime.search("characters", session_id=runtime.session_id))

    assert {"data", "affordances"} <= result.keys()
    assert {item["id"] for item in result["data"]} >= {"iryna", "chuck"}
    assert "select_character" in _actions(result)


def test_location_search_applies_sector_filter(runtime):
    result = _result(runtime.search("locations", {"sector": 3}, runtime.session_id))

    assert result["data"]
    assert {item["sector"] for item in result["data"]} == {3}


def test_setup_transition_records_decisions_and_enters_exploration(runtime):
    select_iryna = _result(
        _act(runtime, "select_character", {"template_id": "iryna"})
    )
    assert select_iryna["data"]["character_id"].startswith("ch-")
    assert "start_mission" in _actions(select_iryna)

    _act(runtime, "select_character", {"template_id": "chuck"})
    started = _result(_act(runtime, "start_mission"))
    session = _result(runtime.get("session", session_id=runtime.session_id))

    assert started["data"]["active_character"] == "Iryna"
    assert session["data"]["phase"] == "exploration"
    assert session["data"]["round_number"] == 1
    assert session["data"]["scene_number"] == 1
    assert "engage_threat" in _actions(session)

    decisions = runtime.ctx.db.get_session_decisions(runtime.session_id)
    assert [decision.action for decision in decisions] == [
        "select_character",
        "select_character",
        "start_mission",
    ]


def test_invalid_character_selection_parameters_are_rejected(runtime):
    _act(runtime, "select_character", {"template_id": "iryna"})

    with pytest.raises(InvalidParameterError, match="must equal"):
        _act(runtime, "select_character", {"template_id": "iryna"})



def test_runtime_instances_are_isolated():
    first = GameRuntime()
    second = GameRuntime()
    try:
        first.session_id = first.create_session().data["id"]
        second.session_id = second.create_session().data["id"]
        _act(first, "select_character", {"template_id": "iryna"})

        first_state = _result(first.get("session", session_id=first.session_id))
        second_state = _result(second.get("session", session_id=second.session_id))

        assert first.session_id != second.session_id
        assert "start_mission" in _actions(first_state)
        assert "start_mission" not in _actions(second_state)
    finally:
        first.ctx.db.close()
        second.ctx.db.close()


def test_known_but_unavailable_action_is_rejected(runtime):
    _act(runtime, "select_character", {"template_id": "iryna"})
    _act(runtime, "start_mission")

    with pytest.raises(UnavailableActionError, match="not currently available"):
        _act(runtime, "select_character", {"template_id": "chuck"})


def test_runtime_requires_mapping_action_parameters(runtime):
    with pytest.raises(InvalidInputError, match="params must be a mapping"):
        runtime.act("select_character", "{not-json", session_id=runtime.session_id)


def test_extra_action_parameters_are_rejected_before_dispatch(runtime):
    with pytest.raises(InvalidParameterError, match="extra is not allowed"):
        _act(runtime, "select_character", {"template_id": "iryna", "extra": True})


def test_runtime_requires_expected_revision(runtime):
    with pytest.raises(InvalidInputError, match="expected_revision is required"):
        runtime.act("select_character", {"template_id": "iryna"}, session_id=runtime.session_id)


def test_affordance_id_authorizes_the_matching_action(runtime):
    state = _result(runtime.get("session", session_id=runtime.session_id))
    affordance = next(
        item
        for item in state["affordances"]
        if item["action"] == "select_character" and item["schema"]["properties"]["template_id"]["const"] == "iryna"
    )

    response = runtime.act(
        "select_character",
        {"template_id": "iryna"},
        session_id=runtime.session_id,
        expected_revision=state["state_revision"],
        affordance_id=affordance["id"],
    )

    assert response.data["character_id"].startswith("ch-")


def test_action_response_has_typed_events_and_affordances(runtime):
    response = _act(runtime, "select_character", {"template_id": "iryna"})

    assert isinstance(response, ActionResponse)
    assert response.events == []
    assert all(affordance.action for affordance in response.affordances)


def test_stale_revision_cannot_mutate_session(runtime):
    revision = runtime.get("session", session_id=runtime.session_id).state_revision
    runtime.act(
        "select_character",
        {"template_id": "iryna"},
        session_id=runtime.session_id,
        expected_revision=revision,
    )

    with pytest.raises(StaleStateError, match="not 0"):
        runtime.act(
            "select_character",
            {"template_id": "chuck"},
            session_id=runtime.session_id,
            expected_revision=revision,
        )


def test_missing_resources_raise_typed_exceptions(runtime):
    with pytest.raises(ResourceNotFoundError) as exc_info:
        runtime.get("character_template", "missing")

    assert exc_info.value.code == "resource_not_found"
    assert exc_info.value.details == {
        "resource_type": "character_template",
        "id": "missing",
    }


def test_json_adapter_preserves_legacy_success_and_error_payloads(runtime):
    adapter = JsonGameRuntimeAdapter(runtime, session_id=runtime.session_id)

    success = json.loads(adapter.search("locations", '{"sector": 3}'))
    failure = json.loads(adapter.act("select_character", "{not-json"))

    assert {item["sector"] for item in success["data"]} == {3}
    assert "Malformed JSON in params" in failure["error"]
    assert "select_character" in _actions(failure)
