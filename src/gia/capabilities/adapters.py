"""Lossless adapter between the legacy ``Affordance`` model and the capability IR.

PR 2 exit criterion: MCP handlers can return legacy affordances rendered
from the IR. This module proves that direction is lossless; production call
sites are not rewired in this PR (the plan's "expand" phase adds the IR
behind existing responses — PR 3/4 do the rewiring).

There is no actor or policy-versioning system yet (that's PR 6), so
``DEFAULT_SUBJECT`` and ``DEFAULT_POLICY_VERSION`` are explicit placeholders
until then.
"""

from __future__ import annotations

from ..models import Affordance
from .ids import compute_binding_key, compute_capability_id
from .legacy_effects import effect_metadata_for
from .models import Capability, CapabilitySet, Link

DEFAULT_SUBJECT = "system"
DEFAULT_POLICY_VERSION = "unversioned"


def capability_from_affordance(
    affordance: Affordance,
    *,
    subject: str,
    scope: str,
    state_revision: int,
    policy_version: str,
) -> Capability:
    """Render one legacy ``Affordance`` as a capability in the given context."""
    binding = compute_binding_key(
        command=affordance.action,
        target=None,
        input_schema=affordance.schema_,
        constraints=affordance.constraints,
    )
    capability_id = compute_capability_id(
        command=affordance.action,
        binding=binding,
        subject=subject,
        scope=scope,
        state_revision=state_revision,
        policy_version=policy_version,
    )
    return Capability(
        id=capability_id,
        command=affordance.action,
        target=None,
        title=affordance.description,
        input_schema=affordance.schema_,
        effects=effect_metadata_for(affordance.action),
        valid_at_revision=state_revision,
        policy_version=policy_version,
        constraints=affordance.constraints,
        legacy_id=affordance.id,
    )


def affordance_from_capability(capability: Capability) -> Affordance:
    """Recover the original legacy ``Affordance`` from a rendered capability.

    Uses ``legacy_id`` rather than recomputing an ``aff-`` hash so the
    round trip is exact even though ``Capability.id`` uses a different,
    context-sensitive hashing scheme (see ``ids.py``).
    """
    return Affordance(
        id=capability.legacy_id or capability.id,
        action=capability.command,
        description=capability.title,
        schema_=capability.input_schema,
        constraints=capability.constraints,
    )


def capability_set_from_affordances(
    affordances: list[Affordance],
    *,
    scope: str,
    state_revision: int,
    subject: str = DEFAULT_SUBJECT,
    policy_version: str = DEFAULT_POLICY_VERSION,
    links: list[Link] | None = None,
    complete: bool = True,
) -> CapabilitySet:
    """Render a full legacy affordance list as a ``CapabilitySet``."""
    return CapabilitySet(
        subject=subject,
        scope=scope,
        state_revision=state_revision,
        policy_version=policy_version,
        complete=complete,
        links=links or [],
        commands=[
            capability_from_affordance(
                affordance,
                subject=subject,
                scope=scope,
                state_revision=state_revision,
                policy_version=policy_version,
            )
            for affordance in affordances
        ],
    )


def affordances_from_capability_set(capability_set: CapabilitySet) -> list[Affordance]:
    """Recover the legacy affordance list carried by a ``CapabilitySet``."""
    return [affordance_from_capability(capability) for capability in capability_set.commands]
