"""Closed-world, deterministic policy provider primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol

from .context import Actor, RequestContext
from .scope import Scope


class PolicyProvider(Protocol):
    """The minimal policy surface consumed by the command kernel."""

    @property
    def version(self) -> str:
        """Content/monotonic version identifying the active policy."""

    def allows(
        self,
        *,
        actor: Actor,
        request: RequestContext,
        scope: Scope,
        command: str,
        binding: Any,
        snapshot: Any,
    ) -> bool:
        """Return whether this actor may use this command binding."""


@dataclass
class DeterministicPolicyProvider:
    """Small Python policy engine used until a real policy needs more power.

    Unlisted commands are allowed, preserving the pre-PR6 game behavior.
    ``command_roles`` is closed-world for listed commands: at least one role
    must match.  ``denied_commands`` provides explicit deny rules useful for
    policy-change tests and operational kill switches.
    """

    _version: str = "policy-v1"
    command_roles: Mapping[str, frozenset[str] | set[str] | Iterable[str]] = field(
        default_factory=dict
    )
    denied_commands: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self._version, str) or not self._version.strip():
            raise ValueError("Policy version must be a non-empty string.")
        object.__setattr__(self, "_version", self._version.strip())
        normalized = {
            command: frozenset(role for role in roles if isinstance(role, str) and role)
            for command, roles in self.command_roles.items()
        }
        self.command_roles = normalized
        self.denied_commands = frozenset(self.denied_commands)

    @property
    def version(self) -> str:
        return self._version

    def set_version(self, version: str) -> None:
        """Advance policy identity; capability IDs change without state writes."""
        value = version.strip() if isinstance(version, str) else ""
        if not value:
            raise ValueError("Policy version must be a non-empty string.")
        self._version = value

    def allows(
        self,
        *,
        actor: Actor,
        request: RequestContext,
        scope: Scope,
        command: str,
        binding: Any,
        snapshot: Any,
    ) -> bool:
        if command in self.denied_commands:
            return False
        required = self.command_roles.get(command)
        if required and not actor.roles.intersection(required):
            return False
        return True


DEFAULT_POLICY_VERSION = "policy-v1"
