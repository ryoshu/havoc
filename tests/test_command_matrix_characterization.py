"""Characterization tests for the GIA/GAS 2.0 PR 1 command matrix.

These tests freeze *current* behavior — including the known gaps recorded in
docs/gia2/command-matrix.json — so later PRs in
docs/GIA-GAS-2.0-IMPLEMENTATION-PLAN.md have a baseline to diverge from on
purpose. They intentionally avoid LLMs and dice-outcome-dependent assertions;
phases that would otherwise require driving randomized combat to reach
(between_scenes, downed, last_stand, mission_complete) are forced directly
through GameContext, since compute_affordances and _dispatch_action only
consult session/character state, not how that state was reached.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest

from src.gia.domain import DomainError, UnavailableActionError
from src.gia.models import GamePhase, InjuryState
from src.gia.server import ActionName, GameRuntime

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMAND_MATRIX = json.loads(
    (REPO_ROOT / "docs" / "gia2" / "command-matrix.json").read_text()
)["actions"]
AFFORDANCES_SRC = (REPO_ROOT / "src" / "gia" / "affordances.py").read_text()
SERVER_SRC = (REPO_ROOT / "src" / "gia" / "server.py").read_text()


# ---------------------------------------------------------------------------
# Fixtures and helpers (mirrors tests/test_runtime_contract.py's style)
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime():
    instance = GameRuntime()
    instance.session_id = instance.create_session().data["id"]
    try:
        yield instance
    finally:
        instance.ctx.db.close()


def _act(runtime: GameRuntime, action: str, params: dict | None = None):
    revision = runtime.get("session", session_id=runtime.session_id).state_revision
    return runtime.act(
        action, params or {}, session_id=runtime.session_id, expected_revision=revision
    )


def _actions(runtime: GameRuntime) -> set[str]:
    session = runtime.get("session", session_id=runtime.session_id)
    return {a.action for a in session.affordances}


def _advance_to_exploration(runtime: GameRuntime):
    _act(runtime, "select_character", {"template_id": "iryna"})
    _act(runtime, "select_character", {"template_id": "chuck"})
    return _act(runtime, "start_mission")


def _advance_to_engagement_pre_roll(runtime: GameRuntime):
    _advance_to_exploration(runtime)
    scene = runtime.ctx.get_active_scene(runtime.session_id)
    threat = scene.active_threats[0]
    return _act(runtime, "engage_threat", {"threat_name": threat.name})


def _advance_to_engagement_post_roll(runtime: GameRuntime):
    _advance_to_engagement_pre_roll(runtime)
    return _act(runtime, "build_dice_pool", {"stat": "brawl"})


def _force_phase(runtime: GameRuntime, phase: GamePhase) -> None:
    """Directly set the session phase, bypassing normal transitions.

    Used only for phases that are either RNG-dependent to reach organically
    (between_scenes, last_stand, mission_complete) or unreachable through
    the current dispatcher entirely (downed — see Gap B in
    docs/gia2/COMMAND-MATRIX.md). compute_affordances and _dispatch_action
    read session.phase directly, so this exercises the same projection and
    dispatch code a real transition would.
    """
    session = runtime.ctx.get_session(runtime.session_id)
    session.phase = phase
    runtime.ctx.db.update_session(session)


# ---------------------------------------------------------------------------
# Matrix <-> code coverage (table-driven, per action)
# ---------------------------------------------------------------------------


def test_matrix_actions_match_the_action_name_literal():
    matrix_actions = {entry["action"] for entry in COMMAND_MATRIX}
    literal_actions = set(get_args(ActionName))
    assert matrix_actions == literal_actions


@pytest.mark.parametrize(
    "entry", COMMAND_MATRIX, ids=[entry["action"] for entry in COMMAND_MATRIX]
)
def test_every_matrix_action_is_projected_in_affordances_py(entry):
    assert f'action="{entry["action"]}"' in AFFORDANCES_SRC


@pytest.mark.parametrize(
    "entry",
    [e for e in COMMAND_MATRIX if e["dispatched"]],
    ids=[e["action"] for e in COMMAND_MATRIX if e["dispatched"]],
)
def test_dispatched_actions_have_a_dispatch_branch_in_server_py(entry):
    assert f'action == "{entry["action"]}"' in SERVER_SRC


def test_wait_for_rescue_has_no_dispatch_branch():
    """Gap A: advertised in the downed phase, but _dispatch_action has no
    branch for it. This test documents the gap; it should start failing
    (forcing an explicit update) the moment a later PR adds one definition
    per command and the gap can no longer exist structurally."""
    assert 'action == "wait_for_rescue"' not in SERVER_SRC


def test_downed_phase_is_never_assigned_by_the_dispatcher():
    """Gap B: GamePhase.downed is only ever read (in affordances.py's
    projection), never written. The downed phase — and therefore
    wait_for_rescue — is unreachable through normal play."""
    assert "GamePhase.downed" not in SERVER_SRC


# ---------------------------------------------------------------------------
# Per-phase projection and negative-case tests
# ---------------------------------------------------------------------------


def test_setup_phase_affordances(runtime):
    actions = _actions(runtime)
    assert {"select_character", "view_character_template"} <= actions
    assert "start_mission" not in actions

    with pytest.raises(UnavailableActionError):
        _act(runtime, "view_character_sheet")


def test_exploration_phase_affordances(runtime):
    _advance_to_exploration(runtime)
    actions = _actions(runtime)

    assert {
        "view_character_sheet",
        "view_scene",
        "move_to_location",
        "engage_threat",
        "check_inventory",
        "next_turn",
    } <= actions
    assert not {"select_character", "start_mission", "build_dice_pool", "allocate_dice"} & actions

    for unavailable in ("allocate_dice", "heal", "trigger_last_stand", "view_epilogue"):
        with pytest.raises(UnavailableActionError):
            _act(runtime, unavailable)


def test_engagement_pre_roll_phase_affordances(runtime):
    _advance_to_engagement_pre_roll(runtime)
    actions = _actions(runtime)

    assert {"build_dice_pool", "retreat"} <= actions
    assert not {"move_to_location", "engage_threat", "allocate_dice"} & actions

    with pytest.raises(UnavailableActionError):
        _act(runtime, "allocate_dice")


def test_engagement_post_roll_phase_affordances(runtime):
    _advance_to_engagement_post_roll(runtime)
    actions = _actions(runtime)

    assert {"allocate_dice", "use_flashback"} <= actions
    assert "build_dice_pool" not in actions

    with pytest.raises(UnavailableActionError):
        _act(runtime, "build_dice_pool")


def test_between_scenes_phase_affordances(runtime):
    _advance_to_exploration(runtime)
    session = runtime.ctx.get_session(runtime.session_id)
    characters = runtime.ctx.db.get_session_characters(runtime.session_id)
    injured, healthy = characters[0], characters[1]
    injured.blood = 3
    injured.injuries = [InjuryState(category="1-2", minor_marked=True)]
    healthy.blood = 2
    runtime.ctx.db.update_character(injured)
    runtime.ctx.db.update_character(healthy)
    _force_phase(runtime, GamePhase.between_scenes)

    actions = _actions(runtime)
    assert {"heal", "choose_next_location", "share_blood"} <= actions
    assert not {"move_to_location", "engage_threat"} & actions

    share_blood_affordance = next(
        a for a in runtime.get("session", session_id=runtime.session_id).affordances
        if a.action == "share_blood"
    )
    assert "giver_id" in share_blood_affordance.schema_["properties"]

    result = _act(
        runtime,
        "heal",
        {"character_id": injured.id, "category": "1-2"},
    )
    assert result.events and result.events[0].type == "InjuryHealed"

    with pytest.raises(UnavailableActionError):
        _act(runtime, "engage_threat")


def test_downed_phase_affordances_and_wait_for_rescue_dispatch_gap(runtime):
    _advance_to_exploration(runtime)
    session = runtime.ctx.get_session(runtime.session_id)
    active_char = runtime.ctx.db.get_character(session.active_character_id)
    active_char.is_downed = True
    runtime.ctx.db.update_character(active_char)
    _force_phase(runtime, GamePhase.downed)

    actions = _actions(runtime)
    assert "wait_for_rescue" in actions

    with pytest.raises(DomainError, match="Unknown action: wait_for_rescue"):
        _act(runtime, "wait_for_rescue")


def test_last_stand_phase_affordances_and_dispatch(runtime):
    _advance_to_exploration(runtime)
    session = runtime.ctx.get_session(runtime.session_id)
    dying_char = runtime.ctx.db.get_character(session.active_character_id)
    dying_char.is_dead = True
    runtime.ctx.db.update_character(dying_char)
    _force_phase(runtime, GamePhase.last_stand)

    assert "trigger_last_stand" in _actions(runtime)

    result = _act(runtime, "trigger_last_stand")
    assert result.data["results"]
    assert len(result.data["results"]) == 8  # HavocEngine.trigger_last_stand rolls 8d6

    session_after = runtime.ctx.get_session(runtime.session_id)
    other_alive = [
        c for c in runtime.ctx.db.get_session_characters(runtime.session_id)
        if not c.is_dead and c.id != dying_char.id
    ]
    assert session_after.phase == (
        GamePhase.exploration if other_alive else GamePhase.mission_complete
    )


def test_mission_complete_phase_affordances_and_dispatch(runtime):
    _advance_to_exploration(runtime)
    _force_phase(runtime, GamePhase.mission_complete)

    assert "view_epilogue" in _actions(runtime)

    result = _act(runtime, "view_epilogue")
    assert "war is over" in result.data["message"]

    with pytest.raises(UnavailableActionError):
        _act(runtime, "engage_threat")


# ---------------------------------------------------------------------------
# Response serialization shape (catches accidental envelope drift)
# ---------------------------------------------------------------------------


def test_get_session_response_shape(runtime):
    result = runtime.get("session", session_id=runtime.session_id).model_dump(
        mode="json", by_alias=True
    )
    assert set(result.keys()) == {"data", "affordances", "state_revision"}
    assert set(result["data"].keys()) >= {
        "id", "phase", "state_revision", "current_location_id",
        "active_character_id", "round_number", "scene_number", "created_at",
    }
    for affordance in result["affordances"]:
        assert set(affordance.keys()) == {"id", "action", "description", "schema", "constraints"}


def test_search_locations_response_shape(runtime):
    result = runtime.search("locations", {"sector": 3}, runtime.session_id).model_dump(
        mode="json", by_alias=True
    )
    assert set(result.keys()) == {"data", "affordances", "state_revision"}
    assert result["data"]
    assert set(result["data"][0].keys()) == {"id", "name", "sector", "objective", "objective_rating"}


def test_act_select_character_response_shape(runtime):
    result = _act(runtime, "select_character", {"template_id": "iryna"}).model_dump(
        mode="json", by_alias=True
    )
    assert set(result.keys()) == {"data", "affordances", "events", "state_revision"}
    assert set(result["data"].keys()) == {"message", "character_id"}
