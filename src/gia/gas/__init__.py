"""GAS 2.0 transport contracts and the typed runtime adapter.

GAS is deliberately a renderer over the GIA capability kernel.  The package
does not own command policy or mutation semantics; it only maps resource URIs
and protocol-shaped requests to the transport-neutral runtime.
"""

from .contracts import (
    ActRequest,
    ActResponse,
    GasActRequest,
    GasActionResponse,
    GasGetRequest,
    GasResourceResponse,
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
    "GasSearchRequest",
    "GasRuntime",
    "GetRequest",
    "GetResponse",
    "SearchRequest",
    "SearchResponse",
]
