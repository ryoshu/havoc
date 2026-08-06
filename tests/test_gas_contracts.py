"""GAS 2.0 contract and migration coverage (PR 7)."""

from __future__ import annotations

import json

import pytest

from src.gia.compat import JsonGameRuntimeAdapter
from src.gia.domain import InvalidParameterError
from src.gia.gas import GasRuntime
from src.gia.server import GameRuntime


@pytest.fixture
def gas_runtime():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        yield gas
    finally:
        runtime.ctx.db.close()


def _command(response, name: str, **constants):
    candidates = [command for command in response.commands if command.command == name]
    for command in candidates:
        properties = command.input_schema.get("properties", {})
        if all(properties.get(key, {}).get("const") == value for key, value in constants.items()):
            return command
    raise AssertionError(f"No {name} capability matches {constants!r}")


def test_gas_response_separates_links_commands_and_context(gas_runtime):
    created = gas_runtime.create_session()

    assert created.data["id"]
    assert created.links[0].rel == "self"
    assert created.commands
    assert all(command.id.startswith("cap-") for command in created.commands)
    assert created.subject == "system"
    assert created.scope.endswith(f"session:{created.data['id']}")
    assert created.policy_version == "policy-v1"
    assert created.complete is True


def test_gas_get_uri_and_search_query_contract(gas_runtime):
    session_id = gas_runtime.create_session().data["id"]

    state = gas_runtime.get(f"gia://session/{session_id}")
    assert state.data["id"] == session_id
    assert state.state_revision == 0
    assert state.commands

    locations = gas_runtime.search("locations", {"sector": 3}, session_id=session_id)
    assert locations.data
    assert {item["sector"] for item in locations.data} == {3}
    assert locations.commands


def test_gas_act_uses_capability_id_and_returns_next_local_set(gas_runtime):
    session_id = gas_runtime.create_session().data["id"]
    state = gas_runtime.get(f"gia://session/{session_id}")
    capability = _command(state, "select_character", template_id="iryna")

    result = gas_runtime.act(
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
    session_id = gas_runtime.create_session().data["id"]
    state = gas_runtime.get(f"gia://session/{session_id}")
    capability = _command(state, "select_character", template_id="iryna")

    with pytest.raises(InvalidParameterError):
        gas_runtime.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna", "action": "start_mission"},
            "gas-test-forged-input",
            session_id=session_id,
        )
    assert gas_runtime.ctx.get_session(session_id).state_revision == 0


def test_legacy_and_gas_adapters_reach_equivalent_state():
    typed_runtime = GameRuntime()
    legacy_runtime = GameRuntime()
    try:
        typed = GasRuntime(typed_runtime)
        gas_session = typed.create_session().data["id"]
        legacy_session = legacy_runtime.create_session().data["id"]
        legacy = JsonGameRuntimeAdapter(legacy_runtime, session_id=legacy_session)

        for template_id in ("iryna", "chuck"):
            state = typed.get(f"gia://session/{gas_session}")
            capability = _command(state, "select_character", template_id=template_id)
            typed.act(
                capability.id,
                state.state_revision,
                {"template_id": template_id},
                f"gas-equivalence-{template_id}",
                session_id=gas_session,
            )
            legacy_state = json.loads(legacy.get("session", session_id=legacy_session))
            revision = legacy_state["state_revision"]
            json.loads(
                legacy.act(
                    "select_character",
                    json.dumps({"template_id": template_id}),
                    session_id=legacy_session,
                    expected_revision=revision,
                )
            )

        gas_state = typed.get(f"gia://session/{gas_session}")
        gas_start = _command(gas_state, "start_mission")
        typed.act(
            gas_start.id,
            gas_state.state_revision,
            {},
            "gas-equivalence-start",
            session_id=gas_session,
        )
        legacy_state = json.loads(legacy.get("session", session_id=legacy_session))
        json.loads(
            legacy.act(
                "start_mission",
                "{}",
                session_id=legacy_session,
                expected_revision=legacy_state["state_revision"],
            )
        )

        assert typed_runtime.ctx.get_session(gas_session).phase == legacy_runtime.ctx.get_session(legacy_session).phase
        assert typed_runtime.ctx.get_session(gas_session).round_number == legacy_runtime.ctx.get_session(legacy_session).round_number
        assert len(typed_runtime.ctx.db.get_session_characters(gas_session)) == len(
            legacy_runtime.ctx.db.get_session_characters(legacy_session)
        )
    finally:
        typed_runtime.ctx.db.close()
        legacy_runtime.ctx.db.close()
