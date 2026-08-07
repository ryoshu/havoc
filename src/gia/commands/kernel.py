"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/kernel.py``.

Moved to ``havoc_domain.kernel`` in PR 18 (the concrete command
projector/dispatcher). Kept here so existing imports
(``from gia.commands.kernel import ...``) keep working; PR 19 migrates
callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.kernel import (
    DEFAULT_ACTOR,
    compute_affordances,
    compute_capability_set,
    diagnose_command,
    dispatch,
    get_command,
    project_affordances,
    project_bindings,
    project_capability_set,
    registry,
    resolve_capability,
    session_scope,
)

__all__ = [
    "DEFAULT_ACTOR",
    "compute_affordances",
    "compute_capability_set",
    "diagnose_command",
    "dispatch",
    "get_command",
    "project_affordances",
    "project_bindings",
    "project_capability_set",
    "registry",
    "resolve_capability",
    "session_scope",
]
