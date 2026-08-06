"""Authenticated request context passed from the server boundary.

Authentication-provider integration is intentionally outside this module.  A
transport adapter constructs a :class:`RequestContext` only after it has
verified the actor, tenant, roles, and any delegated authority.  The kernel
then treats the value as immutable input; command callers cannot supply a
different actor or role as an action parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .scope import Scope


class Actor:
    """An authenticated subject and the roles granted to that subject."""

    __slots__ = ("subject", "roles", "delegated_by")

    def __init__(
        self,
        subject: str,
        roles: Iterable[str] | None = None,
        delegated_by: str | None = None,
    ) -> None:
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("Actor subject must be a non-empty string.")
        normalized_roles = frozenset(
            role.strip() for role in (roles or ())
            if isinstance(role, str) and role.strip()
        )
        self.subject = subject.strip()
        self.roles = normalized_roles
        self.delegated_by = delegated_by.strip() if isinstance(delegated_by, str) and delegated_by.strip() else None

    def __repr__(self) -> str:
        return (
            f"Actor(subject={self.subject!r}, roles={sorted(self.roles)!r}, "
            f"delegated_by={self.delegated_by!r})"
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Actor)
            and self.subject == other.subject
            and self.roles == other.roles
            and self.delegated_by == other.delegated_by
        )

    def __hash__(self) -> int:
        return hash((self.subject, self.roles, self.delegated_by))


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Server-derived identity and tenant context for one request.

    ``scope`` is optional at construction because a server often authenticates
    a tenant before it knows which session/resource will be addressed.  The
    GIA projection and execution entry points derive a session scope from the
    authenticated tenant and reject a supplied scope that does not contain
    that session.
    """

    actor: Actor
    tenant_id: str = "default"
    scope: Scope | None = None
    delegated_authority: str | None = None

    def __post_init__(self) -> None:
        tenant = self.tenant_id.strip() if isinstance(self.tenant_id, str) else ""
        if not tenant:
            raise ValueError("Request tenant_id must be a non-empty string.")
        object.__setattr__(self, "tenant_id", tenant)
        if self.delegated_authority is not None:
            value = self.delegated_authority.strip()
            object.__setattr__(self, "delegated_authority", value or None)

    @property
    def subject(self) -> str:
        return self.actor.subject

    @property
    def roles(self) -> frozenset[str]:
        return self.actor.roles

    @property
    def delegated_by(self) -> str | None:
        """Compatibility alias for callers that name the delegating subject."""
        return self.actor.delegated_by or self.delegated_authority

    def for_scope(self, scope: Scope) -> "RequestContext":
        """Return the same authenticated identity bound to ``scope``."""
        if scope.tenant_id != self.tenant_id:
            raise ValueError("A request scope must belong to the request tenant.")
        return RequestContext(
            actor=self.actor,
            tenant_id=self.tenant_id,
            scope=scope,
            delegated_authority=self.delegated_authority,
        )

    @classmethod
    def system(cls, tenant_id: str = "default") -> "RequestContext":
        """Compatibility context used only by the legacy adapter."""
        return cls(actor=Actor("system"), tenant_id=tenant_id)


# Names used by transport adapters can be explicit without making the domain
# kernel depend on a specific authentication implementation.
AuthenticatedActor = Actor
AuthenticatedRequestContext = RequestContext


DEFAULT_REQUEST_CONTEXT = RequestContext.system()
