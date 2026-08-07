"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/schema.py``.

Moved to ``havoc_domain.schema`` in PR 18 (the Havoc-specific
``OPTIONAL_PARAMETERS`` binding — this was never a domain-neutral
``gia_core`` module, unlike its sibling ``base.py``/``registry.py``). Kept
here so existing imports (``from gia.commands.schema import ...``) keep
working; PR 19 migrates callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.schema import (
    JSON_SCHEMA_URI,
    OPTIONAL_PARAMETERS,
    finalize_affordances,
    normalize_schema,
    schema_errors,
    validate_parameters,
)

__all__ = [
    "JSON_SCHEMA_URI",
    "OPTIONAL_PARAMETERS",
    "normalize_schema",
    "finalize_affordances",
    "schema_errors",
    "validate_parameters",
]
