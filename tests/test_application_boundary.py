"""Tests for the GIA application boundary (PR 14 of the GIA/GAS 2.0 plan).

Imports only `gia_core.*` (including the policy namespace moved out of the
legacy package by RS-02) and the concrete Havoc-backed
implementation (`havoc_domain.application.HavocGiaApplication`,
`havoc_domain.context.GameContext`) — never `gia.server`, `mcp`, or (since
PR 19 removed it) `GasRuntime` — so this file itself is evidence for the exit
criterion "GIA
tests run without constructing an MCP server or GAS runtime." (`GameRuntime`
is imported only by the one test that explicitly proves the facade and the
direct boundary path are equivalent — see its own docstring.) See the
import block below for why every cross-package import here uses its bare
(installed-package) name rather than an `src.`-prefixed one.

Each test reuses an idiom already proven elsewhere in the suite
(`test_execution_service.py`'s idempotency/rollback/concurrency tests,
`test_pr13_golden_fixtures.py`'s tenant-scope test, `test_gas_contracts.py`'s
policy-version test) rather than inventing a new one, applied through
`HavocGiaApplication` instead of `GameRuntime`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from havoc_domain.application import HavocGiaApplication
from havoc_domain.context import GameContext
from havoc_domain.db import GameDB
from havoc_domain.models import GamePhase, InjuryState
from gia_core.policy import Actor, RequestContext

# `gia_core` (and every other cross-package import in this file) is
# deliberately imported by its bare (installed-package) name, not an
# `src.`-prefixed one — `havoc_domain.application` (imported above) reaches
# `gia_core` through an *absolute* `from gia_core... import` (it has to:
# `havoc_domain`/`gia`/`gia_core` are siblings in the installed wheel with
# no shared parent package, so a relative import can't cross that boundary
# — see the import-boundary checker and package manifests). That
# binds the exception/DTO classes this test needs to compare/catch under
# the bare `gia_core.*` identity in `sys.modules`. Importing them here as
# `src.gia_core.*` instead would load a second, distinct copy of the same
# module under a different dotted name — same class *names*, different
# class *objects* — so `pytest.raises(StaleStateError)` would silently
# never match what `havoc_domain.execution` actually raises.
from gia_core.errors import (
    IdempotencyConflictError,
    PolicyChangedError,
    ScopeMismatchError,
    StaleStateError,
)
from gia_core.ports import CapabilityAuthority, ResourceProvider
from gia_core.requests import (
    ExecuteRequest,
    GetRequest,
    ProjectRequest,
)

from .helpers import _command, normalize


@pytest.fixture
def application():
    ctx = GameContext(":memory:")
    app = HavocGiaApplication(ctx)
    session_id = app.create_session().data.id
    try:
        yield app, session_id
    finally:
        ctx.db.close()


def _act(app: HavocGiaApplication, session_id: str, action: str, params: dict | None = None, **kwargs):
    revision = app.get(GetRequest(resource_type="session", session_id=session_id)).state_revision
    return app.execute(
        ExecuteRequest(session_id=session_id, action=action, params=params or {}, expected_revision=revision, **kwargs)
    )


def _advance_to_exploration(app: HavocGiaApplication, session_id: str):
    _act(app, session_id, "select_character", {"template_id": "iryna"})
    _act(app, session_id, "select_character", {"template_id": "chuck"})
    return _act(app, session_id, "start_mission")


def _force_between_scenes_with_two_injured_characters(app: HavocGiaApplication, session_id: str):
    _advance_to_exploration(app, session_id)
    characters = app.ctx.db.get_session_characters(session_id)
    first, second = characters[0], characters[1]
    for char in (first, second):
        char.blood = 3
        char.injuries = [InjuryState(category="1-2", minor_marked=True)]
        app.ctx.db.update_character(char)

    session = app.ctx.get_session(session_id)
    session.phase = GamePhase.between_scenes
    app.ctx.db.update_session(session)
    return first, second


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_protocol_conformance(application):
    app, _session_id = application
    assert isinstance(app, ResourceProvider)
    assert isinstance(app, CapabilityAuthority)


# ---------------------------------------------------------------------------
# Stale state
# ---------------------------------------------------------------------------


def test_stale_state_rejected_through_boundary(application):
    app, session_id = application
    _act(app, session_id, "select_character", {"template_id": "iryna"})

    with pytest.raises(StaleStateError):
        app.execute(
            ExecuteRequest(
                session_id=session_id,
                action="select_character",
                params={"template_id": "chuck"},
                expected_revision=0,  # already advanced to 1 by the call above
            )
        )


# ---------------------------------------------------------------------------
# Policy change
# ---------------------------------------------------------------------------


def test_policy_change_rejected_through_boundary(application):
    app, session_id = application
    app.ctx.policy_provider.set_version("policy-v2")

    with pytest.raises(PolicyChangedError):
        app.execute(
            ExecuteRequest(
                session_id=session_id,
                action="select_character",
                params={"template_id": "iryna"},
                expected_revision=0,
                policy_version="policy-v1-obsolete",
            )
        )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_tenant_isolation_through_boundary(tmp_path):
    db_path = str(tmp_path / "state.db")
    context_a = RequestContext(Actor("actor-a"), "tenant-a")
    context_b = RequestContext(Actor("actor-b"), "tenant-b")
    ctx_a = GameContext(db_path)
    ctx_b = GameContext(db_path)  # same physical db, isolated tenant scopes
    app_a = HavocGiaApplication(ctx_a, request_context=context_a)
    app_b = HavocGiaApplication(ctx_b, request_context=context_b)
    try:
        session_id = app_a.create_session().data.id
        capability = app_a.project(ProjectRequest(session_id=session_id)).commands[0]

        with pytest.raises(ScopeMismatchError) as excinfo:
            app_b.execute(
                ExecuteRequest(
                    session_id=session_id,
                    capability_id=capability.id,
                    expected_revision=0,
                    params={"template_id": "iryna"},
                )
            )
        # ADR-0002: cross-tenant reuse must not reveal that the session exists.
        assert excinfo.value.details == {}
    finally:
        ctx_a.db.close()
        ctx_b.db.close()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_retry_through_boundary(application):
    app, session_id = application
    injured, _other = _force_between_scenes_with_two_injured_characters(app, session_id)
    revision = app.ctx.get_session(session_id).state_revision
    params = {"character_id": injured.id, "category": "1-2"}

    first = app.execute(
        ExecuteRequest(
            session_id=session_id, action="heal", params=params,
            expected_revision=revision, idempotency_key="heal-attempt-1",
        )
    )
    assert first.events and first.events[0].type == "InjuryHealed"
    assert app.ctx.db.get_character(injured.id).blood == 0

    # Retried with the same key/input and the (now-stale) original revision —
    # must return the original committed result rather than re-executing or
    # failing as stale.
    replay = app.execute(
        ExecuteRequest(
            session_id=session_id, action="heal", params=params,
            expected_revision=revision, idempotency_key="heal-attempt-1",
        )
    )
    assert replay.data == first.data
    assert [e.model_dump() for e in replay.events] == [e.model_dump() for e in first.events]
    assert app.ctx.db.get_character(injured.id).blood == 0  # not decremented twice

    with pytest.raises(IdempotencyConflictError):
        app.execute(
            ExecuteRequest(
                session_id=session_id, action="heal",
                params={"character_id": _other.id, "category": "1-2"},
                expected_revision=revision, idempotency_key="heal-attempt-1",
            )
        )


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def test_rollback_on_failure_through_boundary(application, monkeypatch):
    app, session_id = application
    injured, _other = _force_between_scenes_with_two_injured_characters(app, session_id)
    revision = app.ctx.get_session(session_id).state_revision

    def boom(self, decision):
        raise RuntimeError("simulated decision-recording failure")

    monkeypatch.setattr(GameDB, "record_decision", boom)
    decisions_before = len(app.ctx.db.get_session_decisions(session_id))

    with pytest.raises(RuntimeError):
        app.execute(
            ExecuteRequest(
                session_id=session_id, action="heal",
                params={"character_id": injured.id, "category": "1-2"},
                expected_revision=revision,
            )
        )

    # The character mutation, the revision claim, and the (never-reached)
    # decision record must all roll back together (ADR-0006).
    unchanged = app.ctx.db.get_character(injured.id)
    assert unchanged.blood == 3
    assert unchanged.injuries[0].minor_marked
    assert app.ctx.get_session(session_id).state_revision == revision
    assert len(app.ctx.db.get_session_decisions(session_id)) == decisions_before


# ---------------------------------------------------------------------------
# Concurrent mutation
# ---------------------------------------------------------------------------


def test_concurrent_execute_shares_one_revision_through_boundary(application):
    app, session_id = application
    first, second = _force_between_scenes_with_two_injured_characters(app, session_id)
    revision = app.ctx.get_session(session_id).state_revision

    def invoke(character_id: str) -> str:
        try:
            app.execute(
                ExecuteRequest(
                    session_id=session_id, action="heal",
                    params={"character_id": character_id, "category": "1-2"},
                    expected_revision=revision,
                )
            )
            return "ok"
        except StaleStateError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, [first.id, second.id]))

    assert sorted(outcomes) == ["ok", "stale"]
    healed_count = sum(
        1 for char_id in (first.id, second.id)
        if app.ctx.db.get_character(char_id).blood == 0
    )
    assert healed_count == 1  # exactly one heal committed, not two


# ---------------------------------------------------------------------------
# Facade / direct-service equivalence
# ---------------------------------------------------------------------------


def _execute_payload(result) -> dict:
    """Common shape for `ExecuteResult` (direct boundary) and
    `ActionResponse` (facade) — both expose the same four attributes."""
    return {
        "data": result.data,
        "affordances": [a.model_dump(mode="json", by_alias=True) for a in result.affordances],
        "events": [e.model_dump(mode="json") for e in result.events],
        "state_revision": result.state_revision,
    }


def _decision_summary(decision) -> dict:
    """A curated, normalization-safe subset of a `DecisionRecord`.

    Excludes `capability_set_hash` (a content hash of literal, session-local
    capability ids — legitimately different between two independent
    sessions, not an equivalence violation) and the raw
    `capability_snapshot`/`offered_capabilities`/`alternatives_not_selected`
    blobs (nested nondeterministic ids not fully covered by the id-normalizer).
    """
    return {
        "action": decision.action,
        "outcome": decision.outcome,
        "input": decision.input,
        "result_summary": decision.result_summary,
        "state_revision_before": decision.state_revision_before,
        "state_revision_after": decision.state_revision_after,
        "phase_before": decision.phase_before,
        "phase_after": decision.phase_after,
        "affordances_not_taken": sorted(decision.affordances_not_taken),
    }


def test_facade_and_direct_service_paths_are_equivalent():
    """Drives the same action sequence through (a) `GameRuntime` (the
    facade) and (b) a direct `HavocGiaApplication` against an independent
    session, then compares normalized capability sets, execute results, and
    provenance records.
    """
    from havoc_server.runtime import GameRuntime

    runtime = GameRuntime()
    ctx_b = GameContext(":memory:")
    app_b = HavocGiaApplication(ctx_b)
    try:
        session_a = runtime.create_session().data["id"]
        session_b = app_b.create_session().data.id

        cap_a = runtime.capability_set(session_a)
        cap_b = app_b.project(ProjectRequest(session_id=session_b))
        assert normalize(cap_a.model_dump(mode="json")) == normalize(cap_b.model_dump(mode="json"))

        select_a = _command(cap_a, "select_character", template_id="iryna")
        select_b = _command(cap_b, "select_character", template_id="iryna")

        act_a1 = runtime.act(
            capability_id=select_a.id, expected_revision=0,
            params={"template_id": "iryna"}, session_id=session_a, idempotency_key="k1",
        )
        act_b1 = app_b.execute(
            ExecuteRequest(
                session_id=session_b, capability_id=select_b.id, expected_revision=0,
                params={"template_id": "iryna"}, idempotency_key="k1",
            )
        )

        act_a2 = runtime.act(
            action="select_character", params={"template_id": "chuck"},
            expected_revision=act_a1.state_revision, session_id=session_a,
        )
        act_b2 = app_b.execute(
            ExecuteRequest(
                session_id=session_b, action="select_character",
                params={"template_id": "chuck"}, expected_revision=act_b1.state_revision,
            )
        )

        mission_a = runtime.act(
            action="start_mission", expected_revision=act_a2.state_revision, session_id=session_a,
        )
        mission_b = app_b.execute(
            ExecuteRequest(session_id=session_b, action="start_mission", expected_revision=act_b2.state_revision)
        )

        assert normalize(_execute_payload(mission_a)) == normalize(_execute_payload(mission_b))

        provenance_a = [_decision_summary(d) for d in runtime.ctx.db.get_session_provenance(session_a)]
        provenance_b = [_decision_summary(d) for d in ctx_b.db.get_session_provenance(session_b)]
        assert normalize(provenance_a) == normalize(provenance_b)
    finally:
        runtime.ctx.db.close()
        ctx_b.db.close()
