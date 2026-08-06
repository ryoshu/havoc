"""Typed contracts for the capability-set IR (PR 2 of the GIA/GAS 2.0 plan).

Field shapes follow the "Target contracts" section of
``docs/GIA-GAS-2.0-IMPLEMENTATION-PLAN.md``. ``Capability`` adds two fields
not in that sketch: ``constraints`` (free-text rule descriptions carried over
from the legacy ``Affordance`` model) and ``legacy_id`` (the original
``Affordance.id``, preserved so the adapter can round-trip losslessly even
though ``Capability.id`` uses a different, context-sensitive hash — see
``ids.py``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResourceRef(BaseModel):
    """A reference to a concrete entity a capability or link targets."""

    model_config = ConfigDict(frozen=True)

    resource_type: str
    id: str


class EffectMetadata(BaseModel):
    """Declares what executing a capability does, independent of transport."""

    model_config = ConfigDict(frozen=True)

    mutating: bool
    idempotent: bool = True
    destructive: bool = False


class Link(BaseModel):
    """A navigation/read option. Distinct from a ``Capability`` (ADR-0005)."""

    model_config = ConfigDict(frozen=True)

    rel: str
    resource_type: str
    id: str | None = None


class Capability(BaseModel):
    """A single advertised, executable command binding."""

    model_config = ConfigDict(frozen=True)

    id: str
    command: str
    target: ResourceRef | None = None
    title: str
    input_schema: dict
    effects: EffectMetadata
    valid_at_revision: int
    policy_version: str
    constraints: list[str] = Field(default_factory=list)
    legacy_id: str | None = None


class CapabilitySet(BaseModel):
    """The full contextual set of links and capabilities for one subject."""

    model_config = ConfigDict(frozen=True)

    subject: str
    scope: str
    state_revision: int
    policy_version: str
    complete: bool = True
    links: list[Link] = Field(default_factory=list)
    commands: list[Capability] = Field(default_factory=list)
    next_cursor: str | None = None
