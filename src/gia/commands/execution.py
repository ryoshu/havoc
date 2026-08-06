"""The execution service (PR 5 of the GIA/GAS 2.0 plan): the one place a
mutating request is allowed to reach a `Command.execute()` handler.

Before this module existed, the pieces of this guarantee were split across
`GameRuntime._act_impl`/`_dispatch_and_record`/`_dispatch_action` in
`server.py` — reachable only through the MCP-facing runtime, and only
testable by driving that runtime. `execute()` below needs nothing but a
`GameContext`: it owns transaction boundaries, revision claiming, capability
(re)resolution through `commands.kernel`, idempotency, decision recording,
and typed failure modes, independently of MCP or any other client (the PR's
stated goal). `server.py::GameRuntime.act` is now a thin caller.

Idempotency is scoped to `(session_id, actor_id, idempotency_key)` — a key
is only unique per actor per session (see `db.py::save_idempotent_result`),
so the same key value reused in a different session is simply a different,
unrelated record rather than a collision. There is no authenticated actor
system yet (PR 6), so `actor_id` here is the session's active character (or
`"system"`), exactly as `DecisionRecord.actor_id` already computed it.

A repeated call with the same key and the same `(action, params)` returns
the originally committed result without re-executing the handler or
re-validating the (possibly now-stale) `expected_revision` — it is a retry
of a decision already made, not a new one. The same key with different
`(action, params)` is a caller bug, not an ambiguous request to guess at,
so it raises `IdempotencyConflictError` rather than silently executing.
"""

from __future__ import annotations

from ..context import GameContext
from ..domain import (
    DomainError,
    IdempotencyConflictError,
    InvalidInputError,
    InvalidParameterError,
    PolicyChangedError,
    ResourceNotFoundError,
    StaleStateError,
    UnavailableActionError,
)
from ..models import DecisionRecord, DomainEvent
from ..policy import RequestContext
from .kernel import compute_affordances, resolve_capability, session_scope
from .kernel import dispatch as kernel_dispatch
from .schema import validate_parameters


def execute(
    ctx: GameContext,
    session_id: str,
    action: str,
    params: dict,
    expected_revision: int,
    affordance_id: str | None = None,
    idempotency_key: str | None = None,
    *,
    request_context: RequestContext | None = None,
    capability_id: str | None = None,
    policy_version: str | None = None,
) -> tuple[dict, list[DomainEvent]]:
    """Validate, execute, and record one mutating action. The sole entry
    point `GameRuntime.act` (or any other caller) must use to reach a
    command handler.

    Serialized by `ctx.db.connection_lock` so idempotency lookups and the
    transaction they guard cannot race within one process.
    """
    with ctx.db.connection_lock:
        return _execute_locked(
            ctx,
            session_id,
            action,
            params,
            expected_revision,
            affordance_id,
            idempotency_key,
            request_context,
            capability_id,
            policy_version,
        )


def _execute_locked(
    ctx: GameContext,
    session_id: str,
    action: str,
    params: dict,
    expected_revision: int,
    affordance_id: str | None,
    idempotency_key: str | None,
    request_context: RequestContext | None,
    capability_id: str | None,
    expected_policy_version: str | None,
) -> tuple[dict, list[DomainEvent]]:
    session_before = ctx.get_session(session_id)
    if not session_before:
        raise ResourceNotFoundError(
            f"Session {session_id} not found.",
            details={"resource_type": "session", "id": session_id},
        )
    # The pre-PR6 action API had no authenticated context. Keep its actor-id
    # behavior for legacy callers while requiring explicit context for the
    # capability-ID path.
    legacy_context = request_context is None
    request = request_context or RequestContext.system(session_before.tenant_id)
    scope = session_scope(session_before, request)
    actor_id = (
        (session_before.active_character_id or "system")
        if legacy_context
        else request.subject
    )
    current_policy_version = ctx.policy_provider.version
    if (
        expected_policy_version is not None
        and expected_policy_version != current_policy_version
    ):
        raise PolicyChangedError(
            "The policy version for this request is no longer current.",
            details={
                "expected_policy_version": expected_policy_version,
                "current_policy_version": current_policy_version,
            },
        )

    if idempotency_key:
        cached = ctx.db.get_idempotent_result(session_id, actor_id, idempotency_key)
        if cached is not None:
            if cached["action"] != action or cached["params"] != params:
                raise IdempotencyConflictError(
                    f"Idempotency key {idempotency_key!r} was already used for a "
                    f"different request.",
                    details={
                        "idempotency_key": idempotency_key,
                        "original_action": cached["action"],
                        "requested_action": action,
                    },
                )
            return cached["result"], [DomainEvent(**e) for e in cached["events"]]

    if expected_revision is None:
        raise InvalidInputError(
            "expected_revision is required for mutating actions.",
            details={"parameter": "expected_revision"},
        )
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise InvalidInputError(
            "expected_revision must be an integer.",
            details={"parameter": "expected_revision"},
        )

    selected_binding = None
    if capability_id:
        resolved = resolve_capability(ctx, session_before, capability_id, request)
        if resolved is None:
            # Do not distinguish actor, tenant, state, or policy mismatch;
            # capability IDs are references and never reveal another scope.
            raise UnavailableActionError(
                "Capability is not currently available.",
                details={"capability_id": capability_id},
            )
        command, selected_binding, capability = resolved
        if action and action != command.name:
            raise UnavailableActionError(
                "Capability does not authorize the requested action.",
                details={"capability_id": capability_id},
            )
        action = command.name
        if capability.policy_version != current_policy_version:
            raise PolicyChangedError(
                "The capability was issued under an obsolete policy version.",
                details={
                    "expected_policy_version": capability.policy_version,
                    "current_policy_version": current_policy_version,
                },
            )

    pre_affordances = compute_affordances(ctx, session_id, request)
    if affordance_id:
        by_id = [a for a in pre_affordances if a.id == affordance_id]
        if by_id and by_id[0].action != action:
            raise UnavailableActionError(
                f"Affordance {affordance_id} does not authorize action {action}.",
                details={"affordance_id": affordance_id, "action": action},
            )
    candidates = [a for a in pre_affordances if a.action == action]
    if not candidates:
        raise UnavailableActionError(
            f"Action {action} is not currently available.",
            details={
                "action": action,
                "affordance_id": affordance_id,
                "state_revision": session_before.state_revision,
            },
        )
    validated = [(candidate, validate_parameters(candidate, params)) for candidate in candidates]
    matching = [candidate for candidate, errors in validated if not errors]
    if not matching:
        parameter_errors = min((errors for _, errors in validated), key=len)
        raise InvalidParameterError(
            f"Invalid parameters for {action}: {'; '.join(parameter_errors)}.",
            details={"action": action, "errors": parameter_errors},
        )
    if expected_revision != session_before.state_revision:
        raise StaleStateError(
            f"Session {session_id} is at revision {session_before.state_revision}, "
            f"not {expected_revision}.",
            details={
                "session_id": session_id,
                "expected_revision": expected_revision,
                "current_revision": session_before.state_revision,
            },
        )

    try:
        result, events = _claim_and_dispatch(
            ctx, session_id, action, params, expected_revision,
            session_before,
            pre_affordances,
            actor_id,
            idempotency_key,
            request,
            scope,
            capability_id,
            selected_binding,
            expected_policy_version,
        )
    except KeyError as error:
        missing = str(error.args[0]) if error.args else "unknown"
        raise InvalidInputError(
            f"Missing required action parameter: {missing}.",
            details={"action": action, "parameter": missing},
        ) from error
    return result, events


def _claim_and_dispatch(
    ctx: GameContext,
    session_id: str,
    action: str,
    params: dict,
    expected_revision: int,
    session_before,
    pre_affordances: list,
    actor_id: str,
    idempotency_key: str | None,
    request: RequestContext,
    scope,
    capability_id: str | None,
    selected_binding,
    expected_policy_version: str | None,
) -> tuple[dict, list[DomainEvent]]:
    """Atomically claim a revision, re-resolve and execute the command, and
    record decision provenance (and, if requested, the idempotent result) —
    all inside one transaction, so a failure anywhere rolls all of it back
    together (ADR-0006: the transactional store is authoritative)."""
    with ctx.db.transaction():
        if not ctx.db.claim_session_revision(session_id, expected_revision):
            current = ctx.get_session(session_id)
            raise StaleStateError(
                f"Session {session_id} changed while the action was being validated.",
                details={
                    "session_id": session_id,
                    "expected_revision": expected_revision,
                    "current_revision": current.state_revision if current else None,
                },
            )

        phase_before = session_before.phase.value
        actor_name = ""
        if actor_id != "system":
            actor_char = ctx.db.get_character(actor_id)
            actor_name = actor_char.name if actor_char else ""

        affordances_snapshot = [
            {
                "id": a.id,
                "action": a.action,
                "description": a.description,
                "schema": a.schema_,
                "constraints": a.constraints,
            }
            for a in pre_affordances
        ]
        affordances_not_taken = [a.action for a in pre_affordances if a.action != action]

        session = ctx.get_session(session_id)
        if not session:
            raise DomainError(f"Session {session_id} not found.")
        current_policy_version = ctx.policy_provider.version
        if (
            expected_policy_version is not None
            and expected_policy_version != current_policy_version
        ):
            raise PolicyChangedError(
                "The policy version for this request is no longer current.",
                details={
                    "expected_policy_version": expected_policy_version,
                    "current_policy_version": current_policy_version,
                },
            )
        if capability_id:
            # ``claim_session_revision`` advances the revision before the
            # handler runs. Resolve the advertised reference against the
            # caller's expected snapshot; the domain state itself has not yet
            # changed, so this remains an atomic revalidation.
            capability_snapshot = session.model_copy(
                update={"state_revision": expected_revision}
            )
            resolved = resolve_capability(
                ctx, capability_snapshot, capability_id, request
            )
            if resolved is None:
                raise UnavailableActionError(
                    "Capability is not currently available.",
                    details={"capability_id": capability_id},
                )
            command, selected_binding, _capability = resolved
            if command.name != action:
                raise UnavailableActionError(
                    "Capability does not authorize the requested action.",
                    details={"capability_id": capability_id},
                )
        result, events = kernel_dispatch(
            ctx,
            session,
            action,
            params,
            request_context=request,
            binding=selected_binding,
        )

        session_after = ctx.get_session(session_id)
        if session_after:
            # A policy change need not mutate game state, but the policy used
            # for this commit is still persisted for replay/audit.
            session_after.policy_version = current_policy_version
            ctx.db.update_session(session_after)
        phase_after = session_after.phase.value if session_after else phase_before
        result_data = result if isinstance(result, dict) else {}
        decision = DecisionRecord(
            session_id=session_id,
            tenant_id=request.tenant_id,
            scope=scope.key,
            state_revision=session_after.state_revision if session_after else expected_revision + 1,
            policy_version=current_policy_version,
            actor_id=actor_id,
            actor_name=(request.subject if request.subject != "system" else actor_name),
            action=action,
            params=params,
            affordances_snapshot=affordances_snapshot,
            affordances_not_taken=list(set(affordances_not_taken)),
            result_summary=result_data.get("message", "")[:200],
            events=[e.model_dump() for e in events],
            phase_before=phase_before,
            phase_after=phase_after,
        )
        ctx.db.record_decision(decision)

        if idempotency_key:
            ctx.db.save_idempotent_result(
                session_id,
                actor_id,
                idempotency_key,
                action,
                params,
                result_data,
                [e.model_dump() for e in events],
                session_after.state_revision if session_after else expected_revision + 1,
                current_policy_version,
            )

        return result, events
