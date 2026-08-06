"""Canonical scope values used in capability IDs and policy decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScopeKind(str, Enum):
    tenant = "tenant"
    session = "session"
    resource = "resource"
    collection = "collection"
    workflow = "workflow"


@dataclass(frozen=True, slots=True)
class Scope:
    """A tenant-qualified boundary for projection and execution.

    The canonical string is deliberately opaque enough for capability IDs but
    readable in logs.  Tenant identity is part of every non-tenant scope, so a
    capability copied between tenants never resolves to the same reference.
    """

    tenant_id: str
    kind: ScopeKind
    identifier: str

    def __post_init__(self) -> None:
        tenant = self.tenant_id.strip() if isinstance(self.tenant_id, str) else ""
        identifier = self.identifier.strip() if isinstance(self.identifier, str) else ""
        if not tenant:
            raise ValueError("Scope tenant_id must be a non-empty string.")
        if not identifier:
            raise ValueError("Scope identifier must be a non-empty string.")
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "identifier", identifier)
        if not isinstance(self.kind, ScopeKind):
            object.__setattr__(self, "kind", ScopeKind(self.kind))

    @classmethod
    def tenant(cls, tenant_id: str) -> "Scope":
        return cls(tenant_id, ScopeKind.tenant, tenant_id)

    @classmethod
    def session(cls, tenant_id: str, session_id: str) -> "Scope":
        return cls(tenant_id, ScopeKind.session, session_id)

    @classmethod
    def resource(cls, tenant_id: str, resource_type: str, resource_id: str) -> "Scope":
        return cls(tenant_id, ScopeKind.resource, f"{resource_type}/{resource_id}")

    @classmethod
    def collection(cls, tenant_id: str, resource_type: str) -> "Scope":
        return cls(tenant_id, ScopeKind.collection, resource_type)

    @classmethod
    def workflow(cls, tenant_id: str, workflow_id: str) -> "Scope":
        """Scope a capability set to a named workflow or task.

        Workflow scopes are intentionally transport-neutral.  They let a
        renderer expose a small task-local decision surface without changing
        the identity or authorization of the authenticated request.
        """
        return cls(tenant_id, ScopeKind.workflow, workflow_id)

    @property
    def key(self) -> str:
        return f"tenant:{self.tenant_id}/{self.kind.value}:{self.identifier}"

    def __str__(self) -> str:
        return self.key

    def contains_session(self, session_id: str) -> bool:
        """Whether this scope is permitted to address ``session_id``."""
        if self.kind is ScopeKind.tenant:
            return True
        if self.kind is ScopeKind.session:
            return self.identifier == session_id
        # Resource, collection, and workflow scopes are derived by a trusted
        # renderer from a session request.  Their identifiers constrain the
        # capability hash; the kernel still re-projects the binding against
        # the authoritative session before execution.
        return True

    @classmethod
    def from_key(cls, key: str) -> "Scope":
        """Parse the canonical ``tenant:<t>/<kind>:<identifier>`` form."""
        if not isinstance(key, str) or "/" not in key or ":" not in key:
            raise ValueError("Scope key must use tenant:<id>/<kind>:<identifier>.")
        tenant_part, scope_part = key.split("/", 1)
        if not tenant_part.startswith("tenant:") or ":" not in scope_part:
            raise ValueError("Scope key must use tenant:<id>/<kind>:<identifier>.")
        tenant_id = tenant_part.removeprefix("tenant:")
        kind_text, identifier = scope_part.split(":", 1)
        if not tenant_id or not identifier:
            raise ValueError("Scope key must include tenant and identifier.")
        return cls(tenant_id, ScopeKind(kind_text), identifier)
