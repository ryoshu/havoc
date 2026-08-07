"""GAS 2.0 transport contracts and the typed runtime adapter.

GAS is deliberately a renderer over the GIA capability kernel.  The package
does not own command policy or mutation semantics; it only maps resource URIs
and protocol-shaped requests to the transport-neutral runtime.

Deprecated as of PR 15 (`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`): this
is now the Havoc-coupled compatibility path — `GasRuntime` keeps its GIA
types and `gia_core` errors for existing callers (`server.py`'s MCP tools,
`compat.py`, `playthrough/`), delegating only its cursor/pagination/URI
*mechanics* to `gas_protocol`, the reusable, domain-independent
implementation. New GAS-shaped work should build on `gas_protocol`
directly. PR 19 relocates this package out of `src/gia/`.
"""

from .contracts import (
    ActRequest,
    ActResponse,
    GasActRequest,
    GasActionResponse,
    GasGetRequest,
    GasResourceResponse,
    WhyNotResponse,
    GasSearchRequest,
    GetRequest,
    GetResponse,
    SearchRequest,
    SearchResponse,
)
from .runtime import GasRuntime

__all__ = [
    "ActRequest",
    "ActResponse",
    "GasActRequest",
    "GasActionResponse",
    "GasGetRequest",
    "GasResourceResponse",
    "WhyNotResponse",
    "GasSearchRequest",
    "GasRuntime",
    "GetRequest",
    "GetResponse",
    "SearchRequest",
    "SearchResponse",
]
