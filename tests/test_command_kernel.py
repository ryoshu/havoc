"""Tests for the command-policy kernel (GIA/GAS 2.0 PR 3 vertical slice).

`heal` is the one command migrated in this PR. Covers the PR's required
test categories:
- registry uniqueness and typed lookup,
- soundness (a projected binding executes or fails with a documented
  domain-value error),
- enforcement (an unprojected binding is rejected before its handler runs),
- regression parity (a shadow comparison between the old affordance
  projection and the new kernel projection for the same state),
- stale-revision and concurrency behavior for the migrated command.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.gia.commands import Actor, Binding, CommandRegistry, DuplicateCommandError, HealCommand
from src.gia.commands.base import Snapshot
from src.gia.commands.kernel import dispatch as kernel_dispatch
from src.gia.commands.kernel import project_affordances, registry
from src.gia.domain import DomainError, StaleStateError
from src.gia.models import GamePhase, InjuryState
from src.gia.server import GameRuntime

ACTOR = Actor(subject="system")
REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = REPO_ROOT / "src" / "gia" / "commands"


def test_commands_package_has_no_mcp_dependency():
    """Mirrors test_capabilities.py's check: ADR-0009 (GIA is independent of
    GAS) applies to the kernel just as much as to the capability IR."""
    for path in COMMANDS_DIR.glob("*.py"):
        source = path.read_text()
        assert "import mcp" not in source, f"{path} imports mcp types"
        assert "from mcp" not in source, f"{path} imports mcp types"


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


def _advance_to_exploration(runtime: GameRuntime):
    _act(runtime, "select_character", {"template_id": "iryna"})
    _act(runtime, "select_character", {"template_id": "chuck"})
    return _act(runtime, "start_mission")


def _force_between_scenes_with_one_injured_character(runtime: GameRuntime):
    """Mirrors test_command_matrix_characterization.py's between_scenes fixture."""
    _advance_to_exploration(runtime)
    characters = runtime.ctx.db.get_session_characters(runtime.session_id)
    injured, healthy = characters[0], characters[1]
    injured.blood = 3
    injured.injuries = [InjuryState(category="1-2", minor_marked=True)]
    healthy.blood = 2
    runtime.ctx.db.update_character(injured)
    runtime.ctx.db.update_character(healthy)

    session = runtime.ctx.get_session(runtime.session_id)
    session.phase = GamePhase.between_scenes
    runtime.ctx.db.update_session(session)
    return injured, healthy


def _force_between_scenes_with_two_injured_characters(runtime: GameRuntime):
    """Two independently heal-eligible characters, so healing one leaves the
    `heal` action available (bound to the other) for revision-race tests."""
    _advance_to_exploration(runtime)
    characters = runtime.ctx.db.get_session_characters(runtime.session_id)
    first, second = characters[0], characters[1]
    for char in (first, second):
        char.blood = 3
        char.injuries = [InjuryState(category="1-2", minor_marked=True)]
        runtime.ctx.db.update_character(char)

    session = runtime.ctx.get_session(runtime.session_id)
    session.phase = GamePhase.between_scenes
    runtime.ctx.db.update_session(session)
    return first, second


# ---------------------------------------------------------------------------
# Registry uniqueness and typed lookup
# ---------------------------------------------------------------------------


def test_registry_rejects_duplicate_command_names():
    local_registry = CommandRegistry()
    local_registry.register(HealCommand())
    with pytest.raises(DuplicateCommandError):
        local_registry.register(HealCommand())


def test_registry_typed_lookup():
    command = registry.get("heal")
    assert isinstance(command, HealCommand)
    assert registry.get("no-such-command") is None
    assert "heal" in registry.names()


def test_default_registry_has_exactly_the_heal_vertical_slice():
    # PR 4 grows this; PR 3 only migrates one command.
    assert registry.names() == frozenset({"heal"})


# ---------------------------------------------------------------------------
# Soundness: a projected binding executes against the unchanged snapshot
# ---------------------------------------------------------------------------


def test_projected_binding_executes_successfully(runtime):
    injured, _healthy = _force_between_scenes_with_one_injured_character(runtime)

    snapshot = Snapshot(ctx=runtime.ctx, session=runtime.ctx.get_session(runtime.session_id))
    command = registry.get("heal")
    bindings = command.applicable(snapshot, ACTOR)
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.target == {"resource_type": "character", "id": injured.id}

    result = _act(runtime, "heal", {"character_id": injured.id, "category": "1-2"})
    assert result.events and result.events[0].type == "InjuryHealed"

    healed = runtime.ctx.db.get_character(injured.id)
    assert healed.blood == 0
    assert not healed.injuries[0].minor_marked


def test_binding_with_no_unhealed_injury_fails_with_a_domain_value_error(runtime):
    _advance_to_exploration(runtime)
    characters = runtime.ctx.db.get_session_characters(runtime.session_id)
    healthy = characters[0]
    healthy.blood = 5
    runtime.ctx.db.update_character(healthy)
    session = runtime.ctx.get_session(runtime.session_id)
    session.phase = GamePhase.between_scenes
    runtime.ctx.db.update_session(session)

    with pytest.raises(DomainError):
        kernel_dispatch(
            runtime.ctx,
            runtime.ctx.get_session(runtime.session_id),
            "heal",
            {"character_id": healthy.id, "category": "1-2"},
        )


# ---------------------------------------------------------------------------
# Enforcement: an unprojected binding is rejected before its handler runs
# ---------------------------------------------------------------------------


def test_heal_outside_between_scenes_is_rejected_before_execution(runtime):
    _advance_to_exploration(runtime)  # phase == exploration, not between_scenes
    characters = runtime.ctx.db.get_session_characters(runtime.session_id)
    char = characters[0]
    char.blood = 5
    char.injuries = [InjuryState(category="1-2", minor_marked=True)]
    runtime.ctx.db.update_character(char)

    with pytest.raises(DomainError):
        kernel_dispatch(
            runtime.ctx,
            runtime.ctx.get_session(runtime.session_id),
            "heal",
            {"character_id": char.id, "category": "1-2"},
        )

    unchanged = runtime.ctx.db.get_character(char.id)
    assert unchanged.blood == 5
    assert unchanged.injuries[0].minor_marked


def test_stale_binding_for_a_since_healthy_character_is_rejected(runtime):
    injured, _healthy = _force_between_scenes_with_one_injured_character(runtime)

    stale_binding = Binding(
        command="heal",
        target={"resource_type": "character", "id": injured.id},
        title="stale",
        input_schema={"category": {"enum": ["1-2"]}},
    )

    _act(runtime, "heal", {"character_id": injured.id, "category": "1-2"})

    snapshot = Snapshot(ctx=runtime.ctx, session=runtime.ctx.get_session(runtime.session_id))
    command = registry.get("heal")
    with pytest.raises(DomainError):
        command.validate(snapshot, ACTOR, stale_binding, {"character_id": injured.id, "category": "1-2"})


def test_act_rejects_heal_for_an_unavailable_action_entirely(runtime):
    from src.gia.domain import UnavailableActionError

    _advance_to_exploration(runtime)
    with pytest.raises(UnavailableActionError):
        _act(runtime, "heal", {"character_id": "does-not-matter", "category": "1-2"})


# ---------------------------------------------------------------------------
# Regression parity: shadow comparison between old and new projections
# ---------------------------------------------------------------------------


def test_kernel_projection_matches_the_legacy_affordance_shape(runtime):
    """Shadow comparison: the kernel-projected heal binding must render to
    the exact same Affordance the deleted affordances.py loop used to
    produce for the same state, modulo the id assigned by finalize_affordances."""
    injured, _healthy = _force_between_scenes_with_one_injured_character(runtime)
    session = runtime.ctx.get_session(runtime.session_id)

    kernel_affordances = project_affordances(runtime.ctx, session)
    assert len(kernel_affordances) == 1
    projected = kernel_affordances[0]

    assert projected.action == "heal"
    assert projected.description == f"Heal {injured.name} (costs 3 Blood, has 3)"
    assert projected.schema_["properties"]["character_id"]["const"] == injured.id
    assert projected.schema_["properties"]["category"]["enum"] == ["1-2"]

    full_affordances = runtime.get("session", session_id=runtime.session_id).affordances
    heal_affordances = [a for a in full_affordances if a.action == "heal"]
    assert len(heal_affordances) == 1
    assert heal_affordances[0].description == projected.description
    assert heal_affordances[0].schema_["properties"] == projected.schema_["properties"]


def test_no_kernel_projection_outside_between_scenes(runtime):
    _advance_to_exploration(runtime)
    session = runtime.ctx.get_session(runtime.session_id)
    assert project_affordances(runtime.ctx, session) == []


# ---------------------------------------------------------------------------
# Stale revision and concurrency (PR 3 exit criterion)
# ---------------------------------------------------------------------------


def test_stale_revision_cannot_execute_heal(runtime):
    first, second = _force_between_scenes_with_two_injured_characters(runtime)
    revision = runtime.ctx.get_session(runtime.session_id).state_revision

    runtime.act(
        "heal",
        {"character_id": first.id, "category": "1-2"},
        session_id=runtime.session_id,
        expected_revision=revision,
    )

    # `heal` is still offered (bound to `second`), so this reaches the
    # revision check rather than failing as unavailable/invalid-parameter.
    with pytest.raises(StaleStateError):
        runtime.act(
            "heal",
            {"character_id": second.id, "category": "1-2"},
            session_id=runtime.session_id,
            expected_revision=revision,
        )


def test_concurrent_heal_calls_share_one_revision(runtime):
    first, second = _force_between_scenes_with_two_injured_characters(runtime)
    revision = runtime.ctx.get_session(runtime.session_id).state_revision

    def invoke(character_id: str):
        try:
            runtime.act(
                "heal",
                {"character_id": character_id, "category": "1-2"},
                session_id=runtime.session_id,
                expected_revision=revision,
            )
            return "ok"
        except StaleStateError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, [first.id, second.id]))

    assert sorted(outcomes) == ["ok", "stale"]

    healed_count = sum(
        1
        for char_id in (first.id, second.id)
        if runtime.ctx.db.get_character(char_id).blood == 0
    )
    assert healed_count == 1  # exactly one heal committed, not two
