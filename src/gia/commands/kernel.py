"""Glue between the command-policy kernel and the current runtime (PR 3).

`project_affordances` and `dispatch` are the two call sites that let
`affordances.py` and `server.py` route a migrated command through
`Command.applicable`/`validate`/`execute` instead of duplicating its policy
(ADR-0001). PR 3 only wires `heal`; PR 4 grows the registry to every action
and deletes the legacy conditional trees this module currently sits beside.

Both call sites do their `..affordances` import locally: `affordances.py`
imports this module, so a module-level import back would be circular. The
cycle is between two temporary shims, not the domain — PR 4 resolves it by
deleting `affordances.py`'s conditional tree entirely.
"""

from __future__ import annotations

from ..context import GameContext
from ..domain import DomainError, DomainEvent
from ..models import Affordance, GameSession
from .base import Actor, Command, Snapshot
from .heal import HealCommand
from .registry import CommandRegistry

registry = CommandRegistry()
registry.register(HealCommand())

# There is no authenticated identity yet (PR 6); this mirrors the
# `DEFAULT_SUBJECT` placeholder `capabilities.adapters` already uses.
DEFAULT_ACTOR = Actor(subject="system")


def project_affordances(ctx: GameContext, session: GameSession) -> list[Affordance]:
    """Render every kernel-migrated command's current bindings as legacy Affordances."""
    from ..affordances import normalize_schema

    snapshot = Snapshot(ctx=ctx, session=session)
    affordances: list[Affordance] = []
    for command in registry:
        for binding in command.applicable(snapshot, DEFAULT_ACTOR):
            affordances.append(
                Affordance(
                    action=binding.command,
                    description=binding.title,
                    schema_=normalize_schema(binding.input_schema),
                    constraints=binding.constraints,
                )
            )
    return affordances


def dispatch(
    ctx: GameContext, session: GameSession, action: str, params: dict
) -> tuple[dict, list[DomainEvent]]:
    """Revalidate `action` against a freshly projected binding and execute it.

    Bindings are recomputed from the current snapshot rather than trusted
    from an earlier projection (ADR-0002 — capabilities are references, not
    bearer authorization). Each candidate binding is tried in turn, the same
    way `server.py`'s outer schema check already tries every candidate
    affordance; an action with no binding that validates is rejected before
    any handler runs.
    """
    command = registry.get(action)
    if command is None:
        raise DomainError(f"No kernel command is registered for {action!r}.")

    snapshot = Snapshot(ctx=ctx, session=session)
    bindings = command.applicable(snapshot, DEFAULT_ACTOR)
    if not bindings:
        raise DomainError(f"{action} is not currently available.")

    errors: list[str] = []
    for binding in bindings:
        try:
            command.validate(snapshot, DEFAULT_ACTOR, binding, params)
        except DomainError as error:
            errors.append(str(error))
            continue
        return command.execute(snapshot, DEFAULT_ACTOR, binding, params)

    raise DomainError(
        f"No current binding for {action} accepts params {params!r}: {'; '.join(errors)}"
    )


def get_command(action: str) -> Command | None:
    return registry.get(action)
