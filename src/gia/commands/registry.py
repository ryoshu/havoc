"""Command registry: one authoritative lookup for command definitions.

Moved to ``gia_core.registry`` (PR 14 of the GIA/GAS 2.0 plan) — it
never referenced a Havoc concept. Re-exported here for backward
compatibility.
"""

from __future__ import annotations

from gia_core.registry import CommandRegistry, DuplicateCommandError

__all__ = ["CommandRegistry", "DuplicateCommandError"]
