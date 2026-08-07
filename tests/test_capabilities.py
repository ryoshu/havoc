"""Tests for the capability-set IR (GIA/GAS 2.0 PR 2).

Covers the PR's required test categories:
- round-trip losslessness of the legacy affordance adapter,
- canonicalization (ordering does not change IDs),
- schema validation of emitted capability sets,
- capability IDs varying with subject/binding/state revision/policy version,
- the "no MCP types" exit criterion for src/gia/capabilities/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gia_core.capabilities import (
    Capability,
    CapabilitySet,
    EffectMetadata,
    ResourceRef,
    affordances_from_capability_set,
    canonical_json,
    capability_from_affordance,
    capability_set_from_affordances,
    compute_binding_key,
    compute_capability_id,
)
from gia_core.capabilities.legacy_effects import MUTATING_ACTIONS, READ_ONLY_ACTIONS
from gia_core.contracts import Affordance
from gia.server import GameRuntime

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES_DIR = REPO_ROOT / "src" / "gia" / "capabilities"
COMMAND_MATRIX = json.loads(
    (REPO_ROOT / "docs" / "gia2" / "command-matrix.json").read_text()
)["actions"]


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


# ---------------------------------------------------------------------------
# Round-trip losslessness
# ---------------------------------------------------------------------------


def test_setup_phase_affordances_round_trip_losslessly(runtime):
    original = runtime.get("session", session_id=runtime.session_id).affordances

    capability_set = capability_set_from_affordances(
        original, scope=runtime.session_id, state_revision=0
    )
    recovered = affordances_from_capability_set(capability_set)

    assert recovered == original


def test_exploration_phase_affordances_round_trip_losslessly(runtime):
    _act(runtime, "select_character", {"template_id": "iryna"})
    _act(runtime, "select_character", {"template_id": "chuck"})
    state = _act(runtime, "start_mission")
    original = state.affordances

    capability_set = capability_set_from_affordances(
        original, scope=runtime.session_id, state_revision=state.state_revision
    )
    recovered = affordances_from_capability_set(capability_set)

    assert recovered == original
    assert len(original) > 1  # exercises more than one schema/constraint shape


def test_empty_affordance_list_round_trips_to_empty():
    capability_set = capability_set_from_affordances([], scope="s-1", state_revision=0)
    assert capability_set.commands == []
    assert affordances_from_capability_set(capability_set) == []


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def test_canonical_json_ignores_key_insertion_order():
    a = {"z": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "z": 1}
    assert canonical_json(a) == canonical_json(b)


def test_binding_key_and_capability_id_are_stable_regardless_of_dict_order():
    schema_a = {"type": "object", "properties": {"amount": {}, "receiver_id": {}}}
    schema_b = {"properties": {"receiver_id": {}, "amount": {}}, "type": "object"}

    binding_a = compute_binding_key(
        command="share_blood", target=None, input_schema=schema_a, constraints=["c1"]
    )
    binding_b = compute_binding_key(
        command="share_blood", target=None, input_schema=schema_b, constraints=["c1"]
    )
    assert binding_a == binding_b

    id_a = compute_capability_id(
        command="share_blood",
        binding=binding_a,
        subject="system",
        scope="s-1",
        state_revision=0,
        policy_version="unversioned",
    )
    id_b = compute_capability_id(
        command="share_blood",
        binding=binding_b,
        subject="system",
        scope="s-1",
        state_revision=0,
        policy_version="unversioned",
    )
    assert id_a == id_b


def test_capability_id_is_independent_of_list_position(runtime):
    _act(runtime, "select_character", {"template_id": "iryna"})
    state = runtime.get("session", session_id=runtime.session_id)
    affordances = state.affordances
    assert len(affordances) > 1

    forward = capability_set_from_affordances(
        affordances, scope=runtime.session_id, state_revision=state.state_revision
    )
    backward = capability_set_from_affordances(
        list(reversed(affordances)), scope=runtime.session_id, state_revision=state.state_revision
    )

    forward_ids = {c.legacy_id: c.id for c in forward.commands}
    backward_ids = {c.legacy_id: c.id for c in backward.commands}
    assert forward_ids == backward_ids


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _sample_capability(**overrides) -> Capability:
    fields = dict(
        id="cap-" + "0" * 24,
        command="select_character",
        target=None,
        title="Select a character",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        effects=EffectMetadata(mutating=True),
        valid_at_revision=0,
        policy_version="unversioned",
    )
    fields.update(overrides)
    return Capability(**fields)


def test_capability_set_schema_round_trips_through_json():
    capability_set = CapabilitySet(
        subject="system",
        scope="s-1",
        state_revision=0,
        policy_version="unversioned",
        commands=[_sample_capability()],
    )
    dumped = capability_set.model_dump(mode="json")
    restored = CapabilitySet.model_validate(dumped)
    assert restored == capability_set


def test_capability_set_model_json_schema_is_well_formed():
    schema = CapabilitySet.model_json_schema()
    assert schema["type"] == "object"
    assert "commands" in schema["properties"]
    assert "links" in schema["properties"]
    assert "complete" in schema["properties"]
    assert "next_cursor" in schema["properties"]


def test_emitted_capability_ids_match_expected_format(runtime):
    _act(runtime, "select_character", {"template_id": "iryna"})
    state = runtime.get("session", session_id=runtime.session_id)
    capability_set = capability_set_from_affordances(
        state.affordances, scope=runtime.session_id, state_revision=state.state_revision
    )
    for capability in capability_set.commands:
        assert capability.id.startswith("cap-")
        assert len(capability.id) == len("cap-") + 24


def test_resource_ref_and_link_are_constructible():
    ref = ResourceRef(resource_type="character", id="ch-1")
    assert ref.id == "ch-1"


# ---------------------------------------------------------------------------
# IDs vary with context
# ---------------------------------------------------------------------------


def _capability_id(**kwargs) -> str:
    base = dict(
        command="select_character",
        binding="binding-fixture",
        subject="system",
        scope="s-1",
        state_revision=0,
        policy_version="unversioned",
    )
    base.update(kwargs)
    return compute_capability_id(**base)


def test_capability_id_changes_with_subject():
    assert _capability_id(subject="system") != _capability_id(subject="other-actor")


def test_capability_id_changes_with_scope():
    assert _capability_id(scope="s-1") != _capability_id(scope="s-2")


def test_capability_id_changes_with_binding():
    assert _capability_id(binding="binding-a") != _capability_id(binding="binding-b")


def test_capability_id_changes_with_state_revision():
    assert _capability_id(state_revision=0) != _capability_id(state_revision=1)


def test_capability_id_changes_with_policy_version():
    assert _capability_id(policy_version="unversioned") != _capability_id(policy_version="v2")


def test_capability_id_stable_for_identical_context():
    assert _capability_id() == _capability_id()


def test_same_affordance_gets_different_ids_across_state_revisions():
    affordance = Affordance(
        id="aff-fixture",
        action="view_scene",
        description="View the current scene",
        schema_={"type": "object", "properties": {}, "additionalProperties": False},
    )
    at_rev_0 = capability_from_affordance(
        affordance, subject="system", scope="s-1", state_revision=0, policy_version="unversioned"
    )
    at_rev_1 = capability_from_affordance(
        affordance, subject="system", scope="s-1", state_revision=1, policy_version="unversioned"
    )
    assert at_rev_0.id != at_rev_1.id
    # But the recovered legacy affordance is identical either way.
    assert at_rev_0.legacy_id == at_rev_1.legacy_id == "aff-fixture"


# ---------------------------------------------------------------------------
# Legacy effect metadata / drift guard
# ---------------------------------------------------------------------------


def test_legacy_effects_map_matches_command_matrix_mutation_column():
    for entry in COMMAND_MATRIX:
        action = entry["action"]
        mutation = entry["mutation"]
        if mutation is None:
            # wait_for_rescue: never dispatched (Gap A/B), treated as mutating
            # by intent — see legacy_effects.py's module docstring.
            assert action in MUTATING_ACTIONS
            continue
        expected_set = MUTATING_ACTIONS if mutation else READ_ONLY_ACTIONS
        assert action in expected_set, f"{action} mutation={mutation} not reflected in legacy_effects.py"


def test_legacy_effects_map_has_no_unknown_actions():
    matrix_actions = {entry["action"] for entry in COMMAND_MATRIX}
    assert MUTATING_ACTIONS | READ_ONLY_ACTIONS == matrix_actions


# ---------------------------------------------------------------------------
# "No MCP types" exit criterion
# ---------------------------------------------------------------------------


def test_capabilities_package_has_no_mcp_dependency():
    for path in CAPABILITIES_DIR.glob("*.py"):
        source = path.read_text()
        assert "import mcp" not in source, f"{path} imports mcp types"
        assert "from mcp" not in source, f"{path} imports mcp types"
