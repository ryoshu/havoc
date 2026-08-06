"""Deterministic, opaque capability IDs.

Per PR 2 of the GIA/GAS 2.0 plan: capability IDs are computed over the
command name, its binding, subject, scope, state revision, and policy
version. They are references, not bearer authorization (ADR-0002) — the
executor must still re-derive actor identity and re-evaluate policy rather
than trusting the ID's presence.

``canonical_json`` fixes key ordering so equivalent payloads hash the same
way regardless of construction order or process. Hashing is per-capability,
so the position of a capability within a ``CapabilitySet.commands`` list
never affects its ID.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_ID_DIGEST_LENGTH = 24


def canonical_json(value: Any) -> str:
    """Serialize ``value`` with stable key ordering and no incidental whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_binding_key(
    *,
    command: str,
    target: dict | None,
    input_schema: dict,
    constraints: list[str],
) -> str:
    """Canonical identity of *what* a capability lets you do, independent of context.

    Two capabilities have the same binding when they offer the same command
    against the same target with the same schema and constraints — e.g. two
    ``select_character`` affordances bound to different template IDs have
    different bindings because their schemas differ.
    """
    return canonical_json(
        {
            "command": command,
            "target": target,
            "input_schema": input_schema,
            "constraints": constraints,
        }
    )


def compute_capability_id(
    *,
    command: str,
    binding: str,
    subject: str,
    scope: str,
    state_revision: int,
    policy_version: str,
) -> str:
    """Hash a capability's full context into a stable, opaque reference ID."""
    payload = canonical_json(
        {
            "command": command,
            "binding": binding,
            "subject": subject,
            "scope": scope,
            "state_revision": state_revision,
            "policy_version": policy_version,
        }
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:_ID_DIGEST_LENGTH]
    return f"cap-{digest}"
