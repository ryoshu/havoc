"""The command-policy kernel's runtime entry points (PR 3 built this for one
command; PR 4 registers every game command here and makes it the sole
projector/dispatcher).

`compute_affordances` and `dispatch` replace `affordances.py::compute_affordances`
and `server.py::GameRuntime._dispatch_action`'s conditional trees respectively.
Both modules now hold thin delegates to this one (ADR-0001): a command's
phase/binding/precondition logic exists exactly once, in its own module
under `src/gia/commands/`.

`wait_for_rescue` is deliberately not registered. Per docs/gia2/COMMAND-MATRIX.md
Gap A/B, it was advertised in the (structurally unreachable) `downed` phase
but had no dispatch branch and no domain mechanic in `HavocEngine` to
orchestrate — inventing rescue mechanics would violate PR 4's "preserve
domain mechanics, don't reimplement them" scope. Not registering it makes
the gap ADR-0001 names structurally impossible the way that ADR promises:
an unregistered command is never projected, so it can no longer be
advertised as executable when it isn't.
"""

from __future__ import annotations

from gia_core.capabilities import (
    Capability,
    CapabilitySet,
    capability_from_binding,
    compute_binding_key,
)
from gia_core.policy import Actor, DEFAULT_REQUEST_CONTEXT, RequestContext, Scope
from gia_core.command import Command, Snapshot
from gia_core.contracts import Affordance, DomainEvent
from gia_core.errors import DomainError, ScopeMismatchError
from gia_core.registry import CommandRegistry
from havoc_domain.commands.blood import ShareBloodCommand
from havoc_domain.commands.common import ViewCharacterSheetCommand, ViewSceneCommand
from havoc_domain.commands.completion import (
    ChooseNextLocationCommand,
    TriggerLastStandCommand,
    ViewEpilogueCommand,
)
from havoc_domain.commands.engagement import (
    AllocateDiceCommand,
    BuildDicePoolCommand,
    RetreatCommand,
    UseFlashbackCommand,
)
from havoc_domain.commands.exploration import (
    CheckInventoryCommand,
    EngageThreatCommand,
    LootCommand,
    MoveToLocationCommand,
    NextTurnCommand,
)
from havoc_domain.commands.heal import HealCommand
from havoc_domain.commands.setup import (
    SelectCharacterCommand,
    StartMissionCommand,
    ViewCharacterTemplateCommand,
)
from havoc_domain.context import GameContext
from havoc_domain.models import GameSession

from .schema import finalize_affordances, normalize_schema

registry = CommandRegistry()
for _command in (
    SelectCharacterCommand(),
    ViewCharacterTemplateCommand(),
    StartMissionCommand(),
    ViewCharacterSheetCommand(),
    ViewSceneCommand(),
    MoveToLocationCommand(),
    EngageThreatCommand(),
    LootCommand(),
    CheckInventoryCommand(),
    NextTurnCommand(),
    ShareBloodCommand(),
    BuildDicePoolCommand(),
    RetreatCommand(),
    AllocateDiceCommand(),
    UseFlashbackCommand(),
    HealCommand(),
    ChooseNextLocationCommand(),
    TriggerLastStandCommand(),
    ViewEpilogueCommand(),
):
    registry.register(_command)
del _command

# The legacy action adapter uses this explicit compatibility context. New
# projection/execution callers should pass the server-derived context.
DEFAULT_ACTOR = DEFAULT_REQUEST_CONTEXT.actor


def _request_context(request_context: RequestContext | None) -> RequestContext:
    return request_context or DEFAULT_REQUEST_CONTEXT


def session_scope(
    session: GameSession,
    request_context: RequestContext,
    *,
    requested_scope: Scope | None = None,
) -> Scope:
    """Resolve and validate the tenant-qualified scope for a session.

    Failures intentionally do not include the session's tenant or resource
    details. This is the cross-tenant non-existence guarantee from ADR-0002.
    """
    if session.tenant_id != request_context.tenant_id:
        raise ScopeMismatchError("The requested scope is not available.")
    scope = requested_scope or request_context.scope
    if scope is None:
        return Scope.session(request_context.tenant_id, session.id)
    if scope.tenant_id != request_context.tenant_id or not scope.contains_session(session.id):
        raise ScopeMismatchError("The requested scope is not available.")
    return scope


def _policy_allows(
    ctx: GameContext,
    request_context: RequestContext,
    scope: Scope,
    command: Command,
    binding,
    snapshot: Snapshot,
) -> bool:
    return bool(
        ctx.policy_provider.allows(
            actor=request_context.actor,
            request=request_context,
            scope=scope,
            command=command.name,
            binding=binding,
            snapshot=snapshot,
        )
    )


def project_bindings(
    ctx: GameContext,
    session: GameSession,
    request_context: RequestContext | None = None,
    *,
    scope: Scope | None = None,
) -> list[tuple[Command, object]]:
    """Project policy-filtered bindings for an authenticated request."""
    request = _request_context(request_context)
    resolved_scope = session_scope(session, request, requested_scope=scope)
    snapshot = Snapshot(ctx=ctx, session=session)
    projected: list[tuple[Command, object]] = []
    for command in registry:
        for binding in command.applicable(snapshot, request.actor):
            if _policy_allows(ctx, request, resolved_scope, command, binding, snapshot):
                projected.append((command, binding))
    return projected


def project_capability_set(
    ctx: GameContext,
    session: GameSession,
    request_context: RequestContext | None = None,
    *,
    scope: Scope | None = None,
) -> CapabilitySet:
    """Build the contextual capability IR for one authenticated session."""
    request = _request_context(request_context)
    resolved_scope = session_scope(session, request, requested_scope=scope)
    policy_version = ctx.policy_provider.version
    return CapabilitySet(
        subject=request.subject,
        scope=resolved_scope.key,
        state_revision=session.state_revision,
        policy_version=policy_version,
        complete=True,
        commands=[
            capability_from_binding(
                binding,
                effects=command.effects,
                input_schema=normalize_schema(binding.input_schema),
                subject=request.subject,
                scope=resolved_scope.key,
                state_revision=session.state_revision,
                policy_version=policy_version,
            )
            for command, binding in project_bindings(
                ctx, session, request, scope=resolved_scope
            )
        ],
    )


# Descriptive alias for callers that use ``compute_*`` naming alongside the
# existing legacy ``compute_affordances`` entry point.
compute_capability_set = project_capability_set


def resolve_capability(
    ctx: GameContext,
    session: GameSession,
    capability_id: str,
    request_context: RequestContext | None = None,
) -> tuple[Command, object, Capability] | None:
    """Resolve a capability ID against current actor, scope, state, and policy."""
    request = _request_context(request_context)
    resolved_scope = session_scope(session, request)
    policy_version = ctx.policy_provider.version
    for command, binding in project_bindings(ctx, session, request, scope=resolved_scope):
        capability = capability_from_binding(
            binding,
            effects=command.effects,
            input_schema=normalize_schema(binding.input_schema),
            subject=request.subject,
            scope=resolved_scope.key,
            state_revision=session.state_revision,
            policy_version=policy_version,
        )
        if capability.id == capability_id:
            return command, binding, capability
    return None


def diagnose_command(
    ctx: GameContext,
    session: GameSession,
    command_name: str,
    request_context: RequestContext | None = None,
    input: dict | None = None,
) -> tuple[bool, list[dict[str, str]], list[str]]:
    """Return a safe, non-executable explanation for a command's availability.

    This keeps registry, applicability, and policy inspection in GIA.  GAS
    only renders the resulting diagnostic and never receives a dispatch hook.
    Details intentionally avoid binding/target data so a denied command cannot
    become an entity-existence oracle.
    """
    request = _request_context(request_context)
    resolved_scope = session_scope(session, request)
    command = registry.get(command_name)
    if command is None:
        return False, [{"code": "unknown_command", "message": "Command is not part of this game."}], []
    snapshot = Snapshot(ctx=ctx, session=session)
    raw_bindings = command.applicable(snapshot, request.actor)
    allowed_bindings = [
        binding
        for current, binding in project_bindings(
            ctx, session, request, scope=resolved_scope
        )
        if current.name == command_name
    ]
    if raw_bindings and not allowed_bindings:
        return False, [{"code": "policy_denied", "message": "The command is not available in this scope."}], []
    if not raw_bindings:
        return (
            False,
            [{"code": "prerequisite_unsatisfied", "message": "Current game state does not satisfy the command prerequisites."}],
            [f"command is applicable in phase {session.phase.value}"],
        )
    if input is not None:
        for binding in allowed_bindings:
            try:
                command.validate(snapshot, request.actor, binding, input)
            except DomainError:
                continue
            return True, [], []
        return False, [{"code": "invalid_input", "message": "Input does not satisfy an available binding."}], []
    return True, [], []


def project_affordances(
    ctx: GameContext,
    session: GameSession,
    request_context: RequestContext | None = None,
) -> list[Affordance]:
    """Render policy-filtered bindings as legacy affordances."""
    affordances: list[Affordance] = []
    for command, binding in project_bindings(ctx, session, request_context):
        affordances.append(
            Affordance(
                action=binding.command,
                description=binding.title,
                schema_=normalize_schema(binding.input_schema),
                constraints=binding.constraints,
            )
        )
    return affordances


def compute_affordances(
    ctx: GameContext,
    session_id: str,
    request_context: RequestContext | None = None,
) -> list[Affordance]:
    """Compute available actions for `session_id` based on current game state.

    The one remaining call site of `finalize_affordances`/ID assignment;
    `server.py` and `compat.py` call this exactly as they called the old
    `affordances.py::compute_affordances`.
    """
    session = ctx.get_session(session_id)
    if not session:
        return []
    return finalize_affordances(project_affordances(ctx, session, request_context))


def dispatch(
    ctx: GameContext,
    session: GameSession,
    action: str,
    params: dict,
    *,
    request_context: RequestContext | None = None,
    binding=None,
) -> tuple[dict, list[DomainEvent]]:
    """Revalidate `action` against a freshly projected binding and execute it.

    Bindings are recomputed from the current snapshot rather than trusted
    from an earlier projection (ADR-0002 — capabilities are references, not
    bearer authorization). Each candidate binding is tried in turn, the same
    way the outer `act()` schema check already tries every candidate
    affordance; an action with no binding that validates is rejected before
    any handler runs.
    """
    request = _request_context(request_context)
    resolved_scope = session_scope(session, request)
    command = registry.get(action)
    if command is None:
        raise DomainError(f"Unknown action: {action}")

    snapshot = Snapshot(ctx=ctx, session=session)
    bindings = [
        candidate
        for current_command, candidate in project_bindings(ctx, session, request, scope=resolved_scope)
        if current_command.name == action
    ]
    if binding is not None:
        expected_key = compute_binding_key(
            command=binding.command,
            target=binding.target,
            input_schema=binding.input_schema,
            constraints=binding.constraints,
        )
        bindings = [
            candidate
            for candidate in bindings
            if compute_binding_key(
                command=candidate.command,
                target=candidate.target,
                input_schema=candidate.input_schema,
                constraints=candidate.constraints,
            ) == expected_key
        ]
    if not bindings:
        raise DomainError(f"{action} is not currently available.")

    errors: list[str] = []
    for binding in bindings:
        try:
            command.validate(snapshot, request.actor, binding, params)
        except DomainError as error:
            errors.append(str(error))
            continue
        return command.execute(snapshot, request.actor, binding, params)

    raise DomainError(
        f"No current binding for {action} accepts params {params!r}: {'; '.join(errors)}"
    )


def get_command(action: str) -> Command | None:
    return registry.get(action)
