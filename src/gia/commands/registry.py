"""Command registry: one authoritative lookup for command definitions.

Registration is explicit and eager rather than decorator-based discovery, so
a missing import cannot silently leave a command unregistered — the registry
either has a command under a name or it does not.
"""

from __future__ import annotations

from collections.abc import Iterator

from .base import Command


class DuplicateCommandError(Exception):
    """Raised when two command definitions claim the same name."""


class CommandRegistry:
    """A name -> Command lookup that rejects duplicate registrations."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        existing = self._commands.get(command.name)
        if existing is not None:
            raise DuplicateCommandError(
                f"Command {command.name!r} is already registered to "
                f"{type(existing).__name__}; cannot also register {type(command).__name__}."
            )
        self._commands[command.name] = command

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._commands

    def __iter__(self) -> Iterator[Command]:
        return iter(self._commands.values())

    def __len__(self) -> int:
        return len(self._commands)

    def names(self) -> frozenset[str]:
        return frozenset(self._commands)
