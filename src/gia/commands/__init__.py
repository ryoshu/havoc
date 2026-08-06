"""Command-policy kernel (PR 3-5 of the GIA/GAS 2.0 plan).

One `Command` owns its applicability, validation, and execution (ADR-0001),
so projection and dispatch stop re-declaring a command's phase/permission
rules independently. PR 3 proved this with one command (`heal`); PR 4
registered every other game command here and reduced `src/gia/affordances.py`
and `src/gia/server.py::GameRuntime._dispatch_action` to thin delegates —
see `kernel.py`'s module docstring for the one deliberate exception
(`wait_for_rescue` is never registered). PR 5 added `execution.execute`, the
one place any of this reaches a mutation: transaction ownership, revision
claiming, idempotency, and decision provenance, independent of MCP.
"""

from __future__ import annotations

from .base import Actor, Binding, Command, Snapshot
from .execution import execute
from .heal import HealCommand
from .kernel import compute_affordances, dispatch, get_command, project_affordances, registry
from .registry import CommandRegistry, DuplicateCommandError

__all__ = [
    "Actor",
    "Binding",
    "Command",
    "CommandRegistry",
    "DuplicateCommandError",
    "HealCommand",
    "Snapshot",
    "compute_affordances",
    "dispatch",
    "execute",
    "get_command",
    "project_affordances",
    "registry",
]
