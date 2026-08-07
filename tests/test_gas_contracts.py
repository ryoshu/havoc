"""GAS 2.0 contract and migration coverage (PR 7)."""

from __future__ import annotations

import json

import pytest

from gas_protocol.errors import (
    InvalidInputError as GasInvalidInputError,
    StaleViewError as GasStaleViewError,
)
from gia.policy import Scope
from gia.server import GameRuntime, build_gas_service

from .helpers import _command


@pytest.fixture
def gas_runtime():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        yield runtime, gas
    finally:
        runtime.ctx.db.close()


def test_gas_response_separates_links_commands_and_context(gas_runtime):
    _runtime, gas = gas_runtime
    created = gas.create_session()

    assert created.data["id"]
    assert created.links[0].rel == "self"
    assert created.commands
    assert all(command.id.startswith("cap-") for command in created.commands)
    assert created.subject == "system"
    assert created.scope.endswith(f"session:{created.data['id']}")
    assert created.policy_version == "policy-v1"
    assert created.complete is True


def test_gas_get_uri_and_search_query_contract(gas_runtime):
    _runtime, gas = gas_runtime
    session_id = gas.create_session().data["id"]

    state = gas.get(f"gia://session/{session_id}")
    assert state.data["id"] == session_id
    assert state.state_revision == 0
    assert state.commands

    locations = gas.search("locations", {"sector": 3}, session_id=session_id)
    assert locations.data
    assert {item["sector"] for item in locations.data} == {3}
    assert locations.commands


def test_gas_act_uses_capability_id_and_returns_next_local_set(gas_runtime):
    _runtime, gas = gas_runtime
    session_id = gas.create_session().data["id"]
    state = gas.get(f"gia://session/{session_id}")
    capability = _command(state, "select_character", template_id="iryna")

    result = gas.act(
        capability.id,
        state.state_revision,
        {"template_id": "iryna"},
        "gas-test-select",
        session_id=session_id,
    )

    assert result.data["character_id"].startswith("ch-")
    assert result.state_revision == 1
    assert result.commands
    assert result.events == []


def test_forged_action_name_in_input_cannot_influence_dispatch(gas_runtime):
    runtime, gas = gas_runtime
    session_id = gas.create_session().data["id"]
    state = gas.get(f"gia://session/{session_id}")
    capability = _command(state, "select_character", template_id="iryna")

    with pytest.raises(GasInvalidInputError):
        gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna", "action": "start_mission"},
            "gas-test-forged-input",
            session_id=session_id,
        )
    assert runtime.ctx.get_session(session_id).state_revision == 0


def test_search_pagination_is_stable_and_bounded():
    runtime = GameRuntime()
    gas = build_gas_service(runtime, max_page_size=2, max_commands=2)
    try:
        session_id = gas.create_session().data["id"]
        cursor = None
        pages = []
        responses = []
        while True:
            response = gas.search(
                "locations",
                {"sector": 3},
                cursor=cursor,
                limit=2,
                session_id=session_id,
            )
            responses.append(response)
            pages.extend(item["id"] for item in response.data)
            if response.next_cursor is None:
                break
            cursor = response.next_cursor

        expected = [
            location.id
            for location in runtime.ctx.get_all_locations()
            if location.sector == 3
        ]
        assert pages == expected
        assert all(len(response.data) <= 2 for response in responses)
        assert all(response.scope.endswith("/collection:locations") for response in responses)
        assert responses[-1].complete is True
        assert all(response.state_revision == 0 for response in responses)
    finally:
        runtime.ctx.db.close()


def test_cursor_reuse_after_revision_change_returns_stale_view():
    runtime = GameRuntime()
    gas = build_gas_service(runtime, max_page_size=1)
    try:
        session_id = gas.create_session().data["id"]
        first = gas.search("locations", limit=1, session_id=session_id)
        assert first.next_cursor
        state = gas.get(f"gia://session/{session_id}")
        capability = _command(state, "select_character", template_id="iryna")
        gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna"},
            "gas-pr8-stale-cursor",
            session_id=session_id,
        )

        with pytest.raises(GasStaleViewError):
            gas.search("locations", cursor=first.next_cursor, limit=1, session_id=session_id)
    finally:
        runtime.ctx.db.close()


def test_cursor_reuse_after_policy_change_returns_stale_view():
    runtime = GameRuntime()
    gas = build_gas_service(runtime, max_page_size=1)
    try:
        session_id = gas.create_session().data["id"]
        first = gas.search("locations", limit=1, session_id=session_id)
        assert first.next_cursor
        runtime.ctx.policy_provider.set_version("policy-v2")

        with pytest.raises(GasStaleViewError):
            gas.search("locations", cursor=first.next_cursor, limit=1, session_id=session_id)
    finally:
        runtime.ctx.db.close()


def test_large_binding_sets_use_templates_and_a_bounded_page():
    runtime = GameRuntime()
    gas = build_gas_service(runtime, max_commands=5)
    try:
        template = next(iter(runtime.ctx._char_templates.values()))
        runtime.ctx._char_templates = {
            f"fixture-{index}": template.model_copy(update={"id": f"fixture-{index}"})
            for index in range(250)
        }
        response = gas.create_session()

        assert len(response.commands) <= 5
        assert response.complete is False
        assert response.next_cursor
        assert response.binding_templates
        assert all(item.id.startswith("tmpl-") for item in response.binding_templates)
        assert all(item.command in {"select_character", "view_character_template"} for item in response.binding_templates)
    finally:
        runtime.ctx.db.close()


def test_resource_local_capabilities_are_scoped_and_executable():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.get(f"gia://character_template/iryna?session_id={session_id}")
        assert response.scope.endswith("/resource:character_template/iryna")
        assert response.complete is False
        capability = _command(response, "select_character", template_id="iryna")

        result = gas.act(
            capability.id,
            response.state_revision,
            {"template_id": "iryna"},
            "gas-pr8-local-capability",
            session_id=session_id,
            scope=response.scope,
        )
        assert result.data["character_id"]
    finally:
        runtime.ctx.db.close()


def test_why_not_is_diagnostic_only():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.why_not(f"gia://session/{session_id}", "start_mission")

        assert response.commands == []
        assert response.binding_templates == []
        assert response.data["available"] is False
        assert response.data["reasons"][0]["code"] == "prerequisite_unsatisfied"
        assert "iryna" not in json.dumps(response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_scope_kinds_include_workflow_and_round_trip_canonical_keys():
    workflow = Scope.workflow("tenant-a", "mission-brief")
    assert workflow.key == "tenant:tenant-a/workflow:mission-brief"
    assert Scope.from_key(workflow.key) == workflow
    assert workflow.contains_session("any-session") is True
