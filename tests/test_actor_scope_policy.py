"""PR6 coverage: authenticated actors, tenant scopes, and policy versions."""

from __future__ import annotations

import pytest

from src.gia.commands.execution import execute
from src.gia.commands.kernel import project_capability_set
from src.gia.domain import ScopeMismatchError, UnavailableActionError
from src.gia.policy import Actor, DeterministicPolicyProvider, RequestContext, Scope, ScopeKind
from src.gia.server import GameRuntime


def _runtime(tmp_path, subject: str, tenant: str = "tenant-a", *, policy=None):
    context = RequestContext(Actor(subject), tenant)
    return GameRuntime(
        str(tmp_path / "state.db"),
        request_context=context,
        policy_provider=policy,
    ), context


def test_capability_set_is_bound_to_actor_and_scope(tmp_path):
    runtime_a, context_a = _runtime(tmp_path, "actor-a")
    runtime_b, context_b = _runtime(tmp_path, "actor-b")
    try:
        session_id = runtime_a.create_session().data["id"]
        session = runtime_a.ctx.get_session(session_id)

        set_a = project_capability_set(runtime_a.ctx, session, context_a)
        set_b = project_capability_set(runtime_b.ctx, session, context_b)

        assert set_a.subject == "actor-a"
        assert set_b.subject == "actor-b"
        assert set_a.scope == set_b.scope
        assert {c.id for c in set_a.commands}.isdisjoint({c.id for c in set_b.commands})

        cap_a = next(c for c in set_a.commands if c.command == "select_character")
        with pytest.raises(UnavailableActionError) as error:
            execute(
                runtime_b.ctx,
                session_id,
                "",
                {"template_id": "iryna"},
                0,
                request_context=context_b,
                capability_id=cap_a.id,
            )
        assert str(error.value) == "Capability is not currently available."
        assert "tenant" not in error.value.details
    finally:
        runtime_a.ctx.db.close()
        runtime_b.ctx.db.close()


def test_cross_tenant_capability_reuse_is_rejected_without_existence_leak(tmp_path):
    runtime_a, context_a = _runtime(tmp_path, "actor-a", "tenant-a")
    runtime_b, context_b = _runtime(tmp_path, "actor-b", "tenant-b")
    try:
        session_id = runtime_a.create_session().data["id"]
        cap_a = project_capability_set(
            runtime_a.ctx,
            runtime_a.ctx.get_session(session_id),
            context_a,
        ).commands[0]

        with pytest.raises(ScopeMismatchError) as error:
            execute(
                runtime_b.ctx,
                session_id,
                "",
                {"template_id": "iryna"},
                0,
                request_context=context_b,
                capability_id=cap_a.id,
            )
        assert str(error.value) == "The requested scope is not available."
        assert error.value.details == {}
    finally:
        runtime_a.ctx.db.close()
        runtime_b.ctx.db.close()


def test_role_policy_changes_projection_without_changing_game_state(tmp_path):
    policy = DeterministicPolicyProvider(
        command_roles={"select_character": {"player"}},
    )
    runtime, player = _runtime(tmp_path, "actor", policy=policy)
    try:
        session_id = runtime.create_session().data["id"]
        session = runtime.ctx.get_session(session_id)
        player = RequestContext(Actor("actor", roles={"player"}), "tenant-a")
        observer = RequestContext(Actor("actor", roles={"observer"}), "tenant-a")
        player_set = project_capability_set(runtime.ctx, session, player)
        observer_set = project_capability_set(runtime.ctx, session, observer)

        assert any(cap.command == "select_character" for cap in player_set.commands)
        assert not any(cap.command == "select_character" for cap in observer_set.commands)
        assert session.state_revision == 0
        assert player_set.policy_version == observer_set.policy_version == "policy-v1"
    finally:
        runtime.ctx.db.close()


def test_policy_version_invalidates_capability_at_same_state_revision(tmp_path):
    policy = DeterministicPolicyProvider()
    runtime, context = _runtime(tmp_path, "actor", policy=policy)
    try:
        session_id = runtime.create_session().data["id"]
        session = runtime.ctx.get_session(session_id)
        before = project_capability_set(runtime.ctx, session, context)
        before_cap = next(c for c in before.commands if c.command == "select_character")

        policy.set_version("policy-v2")
        after = project_capability_set(runtime.ctx, session, context)
        after_cap = next(c for c in after.commands if c.command == "select_character")

        assert session.state_revision == 0
        assert before.policy_version == "policy-v1"
        assert after.policy_version == "policy-v2"
        assert before_cap.id != after_cap.id
        with pytest.raises(UnavailableActionError):
            execute(
                runtime.ctx,
                session_id,
                "",
                {"template_id": "iryna"},
                0,
                request_context=context,
                capability_id=before_cap.id,
            )
    finally:
        runtime.ctx.db.close()


def test_committed_decision_persists_actor_scope_and_policy_version(tmp_path):
    policy = DeterministicPolicyProvider()
    runtime, context = _runtime(tmp_path, "actor", policy=policy)
    try:
        session_id = runtime.create_session().data["id"]
        session = runtime.ctx.get_session(session_id)
        policy.set_version("policy-v2")
        current = project_capability_set(runtime.ctx, session, context)
        cap = next(c for c in current.commands if c.command == "select_character")

        execute(
            runtime.ctx,
            session_id,
            "",
            {"template_id": "iryna"},
            0,
            request_context=context,
            capability_id=cap.id,
            policy_version="policy-v2",
        )

        committed = runtime.ctx.db.get_session(session_id)
        decision = runtime.ctx.db.get_session_decisions(session_id)[0]
        assert committed.policy_version == "policy-v2"
        assert decision.actor_id == "actor"
        assert decision.tenant_id == "tenant-a"
        assert decision.scope == f"tenant:tenant-a/session:{session_id}"
        assert decision.state_revision == 1
        assert decision.policy_version == "policy-v2"
    finally:
        runtime.ctx.db.close()


def test_scope_canonicalization_covers_supported_scope_kinds():
    tenant = Scope.tenant("tenant-a")
    session = Scope.session("tenant-a", "gs-1")
    resource = Scope.resource("tenant-a", "character", "ch-1")
    collection = Scope.collection("tenant-a", "characters")

    assert tenant.kind is ScopeKind.tenant
    assert session.contains_session("gs-1")
    assert not session.contains_session("gs-2")
    assert resource.key != collection.key != session.key
    assert session.key.startswith("tenant:tenant-a/")
