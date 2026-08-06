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

from ..context import GameContext
from ..domain import DomainError, DomainEvent
from ..models import Affordance, GameSession
from .base import Actor, Command, Snapshot
from .blood import ShareBloodCommand
from .common import ViewCharacterSheetCommand, ViewSceneCommand
from .completion import ChooseNextLocationCommand, TriggerLastStandCommand, ViewEpilogueCommand
from .engagement import AllocateDiceCommand, BuildDicePoolCommand, RetreatCommand, UseFlashbackCommand
from .exploration import (
    CheckInventoryCommand,
    EngageThreatCommand,
    LootCommand,
    MoveToLocationCommand,
    NextTurnCommand,
)
from .heal import HealCommand
from .registry import CommandRegistry
from .schema import finalize_affordances, normalize_schema
from .setup import SelectCharacterCommand, StartMissionCommand, ViewCharacterTemplateCommand

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

# There is no authenticated identity yet (PR 6); this mirrors the
# `DEFAULT_SUBJECT` placeholder `capabilities.adapters` already uses.
DEFAULT_ACTOR = Actor(subject="system")


def project_affordances(ctx: GameContext, session: GameSession) -> list[Affordance]:
    """Render every registered command's current bindings as legacy Affordances."""
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


def compute_affordances(ctx: GameContext, session_id: str) -> list[Affordance]:
    """Compute available actions for `session_id` based on current game state.

    The one remaining call site of `finalize_affordances`/ID assignment;
    `server.py` and `compat.py` call this exactly as they called the old
    `affordances.py::compute_affordances`.
    """
    session = ctx.get_session(session_id)
    if not session:
        return []
    return finalize_affordances(project_affordances(ctx, session))


def dispatch(
    ctx: GameContext, session: GameSession, action: str, params: dict
) -> tuple[dict, list[DomainEvent]]:
    """Revalidate `action` against a freshly projected binding and execute it.

    Bindings are recomputed from the current snapshot rather than trusted
    from an earlier projection (ADR-0002 — capabilities are references, not
    bearer authorization). Each candidate binding is tried in turn, the same
    way the outer `act()` schema check already tries every candidate
    affordance; an action with no binding that validates is rejected before
    any handler runs.
    """
    command = registry.get(action)
    if command is None:
        raise DomainError(f"Unknown action: {action}")

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
