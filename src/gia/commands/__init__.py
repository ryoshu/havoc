"""Command-policy kernel (PR 3 of the GIA/GAS 2.0 plan).

One `Command` owns its applicability, validation, and execution (ADR-0001),
so projection and dispatch stop re-declaring a command's phase/permission
rules independently. PR 3 registers one command (`heal`) as a vertical
slice; PR 4 migrates the rest of `src/gia/affordances.py` and
`src/gia/server.py` onto this package and deletes their conditional trees.
"""

from __future__ import annotations

from .base import Actor, Binding, Command, Snapshot
from .heal import HealCommand
from .kernel import dispatch, get_command, project_affordances, registry
from .registry import CommandRegistry, DuplicateCommandError

__all__ = [
    "Actor",
    "Binding",
    "Command",
    "CommandRegistry",
    "DuplicateCommandError",
    "HealCommand",
    "Snapshot",
    "dispatch",
    "get_command",
    "project_affordances",
    "registry",
]
