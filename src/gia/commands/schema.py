"""Havoc-specific JSON-schema wiring (PR 4 of the GIA/GAS 2.0 plan).

The generic JSON-schema machinery moved to ``src.gia_core.schema`` (PR 14)
— it takes an ``optional_parameters`` set explicitly rather than assuming
one. This module binds that parameter to ``OPTIONAL_PARAMETERS``, the
kernel-wide set of Havoc input-schema fields that are optional (currently
only ``BuildDicePoolCommand``'s ``equipment_names``/``ability_name``/
``bonus_dice``), preserving the exact behavior every existing call site
(``commands/kernel.py``'s affordance/capability rendering) already relies
on. ``schema_errors``/``validate_parameters`` don't depend on
``optional_parameters`` at all and are re-exported unchanged.
"""

from __future__ import annotations

from typing import Any

from ...gia_core.contracts import Affordance
from ...gia_core.schema import JSON_SCHEMA_URI, schema_errors, validate_parameters
from ...gia_core.schema import finalize_affordances as _finalize_affordances_generic
from ...gia_core.schema import normalize_schema as _normalize_schema_generic

OPTIONAL_PARAMETERS = frozenset({"equipment_names", "ability_name", "bonus_dice"})

__all__ = [
    "JSON_SCHEMA_URI",
    "OPTIONAL_PARAMETERS",
    "normalize_schema",
    "finalize_affordances",
    "schema_errors",
    "validate_parameters",
]


def normalize_schema(raw_schema: dict[str, Any]) -> dict[str, Any]:
    return _normalize_schema_generic(raw_schema, optional_parameters=OPTIONAL_PARAMETERS)


def finalize_affordances(affordances: list[Affordance]) -> list[Affordance]:
    return _finalize_affordances_generic(affordances, optional_parameters=OPTIONAL_PARAMETERS)
