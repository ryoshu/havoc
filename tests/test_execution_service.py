"""Tests for the execution service (GIA/GAS 2.0 PR 5).

`src/gia/commands/execution.py::execute` is the sole entry point through
which a mutating request reaches a `Command.execute()` handler — the "atomic
reference monitor" PR 5 establishes independently of MCP or `GameRuntime`.
Covers the PR's required test categories:
- two concurrent calls at one revision cannot both commit,
- a retry with the same idempotency key returns the same result without a
  second mutation or duplicate events,
- reusing an idempotency key with different input fails,
- an idempotency key is scoped per session (reuse across sessions does not
  collide, i.e. a "capability" from another scope is rejected as its own
  independent record rather than silently shared),
- transaction-failure injection proves state, events, revision, and
  provenance roll back together,
- the service needs nothing but a `GameContext` — no `GameRuntime`, no MCP.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from havoc_domain.execution import execute
from havoc_domain.context import GameContext
from havoc_domain.db import GameDB
from gia_core.errors import IdempotencyConflictError, StaleStateError
from havoc_domain.models import GamePhase, InjuryState
from havoc_server.runtime import GameRuntime


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


def _force_between_scenes_with_two_injured_characters(runtime: GameRuntime):
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
# Concurrency: two calls at one revision cannot both commit
# ---------------------------------------------------------------------------


def test_concurrent_execute_calls_at_one_revision_share_one_winner(runtime):
    first, second = _force_between_scenes_with_two_injured_characters(runtime)
    revision = runtime.ctx.get_session(runtime.session_id).state_revision

    def invoke(character_id: str):
        try:
            execute(
                runtime.ctx, runtime.session_id, "heal",
                {"character_id": character_id, "category": "1-2"}, revision,
            )
            return "ok"
        except StaleStateError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, [first.id, second.id]))

    assert sorted(outcomes) == ["ok", "stale"]
    healed_count = sum(
        1 for char_id in (first.id, second.id)
        if runtime.ctx.db.get_character(char_id).blood == 0
    )
    assert healed_count == 1  # exactly one heal committed, not two


# ---------------------------------------------------------------------------
# Idempotency: retry, conflict, and per-session scoping
# ---------------------------------------------------------------------------


def test_idempotent_retry_returns_the_same_result_without_a_second_mutation(runtime):
    injured, _other = _force_between_scenes_with_two_injured_characters(runtime)
    revision = runtime.ctx.get_session(runtime.session_id).state_revision
    params = {"character_id": injured.id, "category": "1-2"}

    result_1, events_1 = execute(
        runtime.ctx, runtime.session_id, "heal", params, revision,
        idempotency_key="heal-attempt-1",
    )
    assert events_1 and events_1[0].type == "InjuryHealed"
    healed_once = runtime.ctx.db.get_character(injured.id)
    assert healed_once.blood == 0

    # Retried with the same key and the same input, and a now-stale revision
    # (as a real retry after a dropped response would see) — must not
    # re-execute or fail as stale; it returns the original committed result.
    result_2, events_2 = execute(
        runtime.ctx, runtime.session_id, "heal", params, revision,
        idempotency_key="heal-attempt-1",
    )
    assert result_2 == result_1
    assert [e.model_dump() for e in events_2] == [e.model_dump() for e in events_1]

    still_healed_once = runtime.ctx.db.get_character(injured.id)
    assert still_healed_once.blood == 0  # not decremented a second time


def test_idempotency_key_reused_with_different_input_conflicts(runtime):
    injured, other = _force_between_scenes_with_two_injured_characters(runtime)
    revision = runtime.ctx.get_session(runtime.session_id).state_revision

    execute(
        runtime.ctx, runtime.session_id, "heal",
        {"character_id": injured.id, "category": "1-2"}, revision,
        idempotency_key="shared-key",
    )

    with pytest.raises(IdempotencyConflictError):
        execute(
            runtime.ctx, runtime.session_id, "heal",
            {"character_id": other.id, "category": "1-2"}, revision,
            idempotency_key="shared-key",
        )

    # The conflicting attempt must not have executed.
    assert runtime.ctx.db.get_character(other.id).blood == 3


def test_idempotency_key_is_scoped_per_session(tmp_path):
    db_path = str(tmp_path / "scoping.db")
    runtime_a = GameRuntime(db_path=db_path)
    try:
        session_a = runtime_a.create_session().data["id"]
        session_b = runtime_a.create_session().data["id"]  # same GameDB, different session

        for sid in (session_a, session_b):
            _act_for_session(runtime_a, sid, "select_character", {"template_id": "iryna"})
            _act_for_session(runtime_a, sid, "select_character", {"template_id": "chuck"})
            _act_for_session(runtime_a, sid, "start_mission")
            characters = runtime_a.ctx.db.get_session_characters(sid)
            injured = characters[0]
            injured.blood = 3
            injured.injuries = [InjuryState(category="1-2", minor_marked=True)]
            runtime_a.ctx.db.update_character(injured)
            session = runtime_a.ctx.get_session(sid)
            session.phase = GamePhase.between_scenes
            runtime_a.ctx.db.update_session(session)

        char_a = runtime_a.ctx.db.get_session_characters(session_a)[0]
        char_b = runtime_a.ctx.db.get_session_characters(session_b)[0]
        revision_a = runtime_a.ctx.get_session(session_a).state_revision
        revision_b = runtime_a.ctx.get_session(session_b).state_revision

        # Same literal idempotency key, two different sessions: both succeed
        # independently rather than the second being rejected as a conflict
        # or silently returning session A's cached result.
        result_a, _ = execute(
            runtime_a.ctx, session_a, "heal",
            {"character_id": char_a.id, "category": "1-2"}, revision_a,
            idempotency_key="same-key-different-session",
        )
        result_b, _ = execute(
            runtime_a.ctx, session_b, "heal",
            {"character_id": char_b.id, "category": "1-2"}, revision_b,
            idempotency_key="same-key-different-session",
        )
        assert runtime_a.ctx.db.get_character(char_a.id).blood == 0
        assert runtime_a.ctx.db.get_character(char_b.id).blood == 0
        # Both committed independently under the identical key string — one
        # idempotency record per session, not a shared/collided one. Each
        # session's actor is its own char_a/char_b (start_mission's active
        # character), so the records are also keyed by different actor_ids.
        assert runtime_a.ctx.db.get_idempotent_result(
            session_a, char_a.id, "same-key-different-session"
        )["result"] == result_a
        assert runtime_a.ctx.db.get_idempotent_result(
            session_b, char_b.id, "same-key-different-session"
        )["result"] == result_b
    finally:
        runtime_a.ctx.db.close()


def _act_for_session(runtime: GameRuntime, session_id: str, action: str, params: dict | None = None):
    revision = runtime.get("session", session_id=session_id).state_revision
    return runtime.act(action, params or {}, session_id=session_id, expected_revision=revision)


# ---------------------------------------------------------------------------
# Transaction consistency: failure injection rolls everything back together
# ---------------------------------------------------------------------------


def test_failure_after_mutation_rolls_back_state_events_and_provenance(runtime, monkeypatch):
    injured, _other = _force_between_scenes_with_two_injured_characters(runtime)
    revision = runtime.ctx.get_session(runtime.session_id).state_revision

    def boom(self, decision):
        raise RuntimeError("simulated decision-recording failure")

    monkeypatch.setattr(GameDB, "record_decision", boom)

    decisions_before = len(runtime.ctx.db.get_session_decisions(runtime.session_id))

    with pytest.raises(RuntimeError):
        execute(
            runtime.ctx, runtime.session_id, "heal",
            {"character_id": injured.id, "category": "1-2"}, revision,
        )

    # The character mutation kernel_dispatch already performed, the revision
    # claim, and the (never-reached) decision record must all roll back
    # together — none of ADR-0006's "one transaction" partially lands.
    unchanged = runtime.ctx.db.get_character(injured.id)
    assert unchanged.blood == 3
    assert unchanged.injuries[0].minor_marked
    assert runtime.ctx.get_session(runtime.session_id).state_revision == revision
    assert len(runtime.ctx.db.get_session_decisions(runtime.session_id)) == decisions_before


# ---------------------------------------------------------------------------
# Independence from GameRuntime/MCP
# ---------------------------------------------------------------------------


def test_execute_runs_against_a_bare_game_context_with_no_game_runtime():
    """The execution service's whole point (PR 5's goal): establish the
    enforcement guarantee independently of MCP or client behavior. This
    drives an entire mini-playthrough through `execute()` directly against
    a `GameContext`, never touching `GameRuntime` or any MCP type."""
    ctx = GameContext(db_path=":memory:")
    try:
        session = ctx.db.create_session()

        result, events = execute(ctx, session.id, "select_character", {"template_id": "iryna"}, 0)
        assert result["character_id"]
        assert events == []

        result, events = execute(ctx, session.id, "start_mission", {}, 1)
        assert "mission begins" in result["message"]

        session_after = ctx.get_session(session.id)
        assert session_after.phase == GamePhase.exploration
        assert session_after.state_revision == 2
    finally:
        ctx.db.close()
