"""Command-policy kernel primitives (PR 3 of the GIA/GAS 2.0 plan).

ADR-0001 requires one owned definition per command: its applicability
(binding/phase logic), validation, and execution. This module defines that
shared contract so a projector and a dispatcher can no longer duplicate a
command's rules in two places (the `wait_for_rescue` gap ADR-0001 names).

`Actor` and `Snapshot` are intentionally minimal. There is no authenticated
identity or multi-tenancy yet — PR 6 generalizes `Actor` beyond a single
system subject, matching the `DEFAULT_SUBJECT` placeholder already used by
`capabilities.adapters`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..capabilities import EffectMetadata
from ..context import GameContext
from ..domain import DomainError, DomainEvent
from ..models import GameSession
from .schema import normalize_schema, schema_errors


class Actor:
    """The identity a binding is projected for and executed as."""

    __slots__ = ("subject",)

    def __init__(self, subject: str) -> None:
        self.subject = subject

    def __repr__(self) -> str:
        return f"Actor(subject={self.subject!r})"


class Snapshot:
    """Read-only view of authoritative state a command projects/validates against."""

    __slots__ = ("ctx", "session")

    def __init__(self, ctx: GameContext, session: GameSession) -> None:
        self.ctx = ctx
        self.session = session


class Binding:
    """One concrete way a command currently applies: a target, schema, and constraints.

    Carries the fields `capabilities.adapters` needs to render a `Capability`
    (ADR-0003 — capability sets are contextual), minus the id/state-revision/
    policy-version fields computed at capability-set assembly time.
    """

    __slots__ = ("command", "target", "title", "input_schema", "constraints")

    def __init__(
        self,
        *,
        command: str,
        target: dict | None,
        title: str,
        input_schema: dict,
        constraints: list[str] | None = None,
    ) -> None:
        self.command = command
        self.target = target
        self.title = title
        self.input_schema = input_schema
        self.constraints = constraints or []


class Command(ABC):
    """One authoritative definition of a command's policy and behavior (ADR-0001).

    `applicable` and `execute` must consult the same binding rather than
    letting a projector and a dispatcher redeclare it independently.
    """

    name: str
    effects: EffectMetadata

    @abstractmethod
    def applicable(self, snapshot: Snapshot, actor: Actor) -> list[Binding]:
        """Return every binding this command currently offers this actor."""

    def validate(self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict) -> None:
        """Raise a DomainError if `input` does not satisfy `binding` against `snapshot`.

        The default checks `input` against `binding.input_schema` — the same
        generic shape check the outer `act()` boundary already runs against
        a projected affordance. Most commands only need this; a command with
        a domain-level precondition beyond input shape (e.g. `heal`'s Blood
        and injury-category check) overrides this and typically re-derives
        that precondition from `snapshot` rather than trusting `binding`.
        """
        errors = schema_errors(normalize_schema(binding.input_schema), input)
        if errors:
            raise DomainError(
                f"Invalid parameters for {binding.command}: {'; '.join(errors)}."
            )

    @abstractmethod
    def execute(
        self, snapshot: Snapshot, actor: Actor, binding: Binding, input: dict
    ) -> tuple[dict, list[DomainEvent]]:
        """Mutate state and return the result payload plus emitted domain events."""
