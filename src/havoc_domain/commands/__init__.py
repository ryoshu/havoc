"""Concrete Havoc command definitions (PR 18).

One `Command` owns its applicability, validation, and execution (ADR-0001).
Moved from `src/gia/commands/{blood,heal,engagement,exploration,completion,
setup,common}.py` — registered by `havoc_domain.kernel`, the sole
projector/dispatcher.
"""

from __future__ import annotations
