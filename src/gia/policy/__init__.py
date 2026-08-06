"""Identity, scope, and executable policy primitives for GIA.

The policy package deliberately stops at the domain boundary.  It describes
the authenticated request supplied by a transport adapter and evaluates
deterministic application policy; it does not authenticate a bearer token or
depend on MCP/HTTP types.
"""

from .context import (
    Actor,
    AuthenticatedActor,
    AuthenticatedRequestContext,
    DEFAULT_REQUEST_CONTEXT,
    RequestContext,
)
from .provider import DeterministicPolicyProvider, PolicyProvider
from .scope import Scope, ScopeKind

__all__ = [
    "Actor",
    "AuthenticatedActor",
    "AuthenticatedRequestContext",
    "DeterministicPolicyProvider",
    "DEFAULT_REQUEST_CONTEXT",
    "PolicyProvider",
    "RequestContext",
    "Scope",
    "ScopeKind",
]
