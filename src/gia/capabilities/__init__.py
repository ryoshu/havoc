"""Transport-independent capability-set intermediate representation (IR).

This package has no dependency on MCP types (see ADR-0009). It defines the
contracts described in ``docs/GIA-GAS-2.0-IMPLEMENTATION-PLAN.md`` PR 2 and a
lossless adapter to and from the legacy ``Affordance`` model.
"""

from __future__ import annotations

from .adapters import (
    affordance_from_capability,
    affordances_from_capability_set,
    capability_from_affordance,
    capability_from_binding,
    capability_set_from_affordances,
)
from .ids import canonical_json, compute_binding_key, compute_capability_id
from .models import BindingTemplate, Capability, CapabilitySet, EffectMetadata, Link, ResourceRef

__all__ = [
    "Capability",
    "CapabilitySet",
    "BindingTemplate",
    "EffectMetadata",
    "Link",
    "ResourceRef",
    "affordance_from_capability",
    "affordances_from_capability_set",
    "canonical_json",
    "capability_from_affordance",
    "capability_from_binding",
    "capability_set_from_affordances",
    "compute_binding_key",
    "compute_capability_id",
]
