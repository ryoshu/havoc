"""Deprecated legacy adapter (PR 4 of the GIA/GAS 2.0 plan).

Every command's phase/binding/precondition logic used to live in this
module's `compute_affordances()` conditional tree, duplicated by a matching
tree in `server.py::GameRuntime._dispatch_action` (ADR-0001's
`wait_for_rescue` gap was the proof they could disagree). PR 4 moved that
logic into `src/gia/commands/`, one command per definition, registered in
`src/gia/commands/kernel.py`.

This module is kept only so existing imports (`server.py`, `compat.py`,
tests) keep working without an interim rename; PR 7's GAS 2.0 cutover is
expected to remove it once callers reference `commands.kernel` directly.
"""

from __future__ import annotations

from .commands.kernel import compute_affordances
from .commands.schema import finalize_affordances, normalize_schema, validate_parameters

__all__ = [
    "compute_affordances",
    "finalize_affordances",
    "normalize_schema",
    "validate_parameters",
]
