"""Alternative renderings of the transport-independent GIA capability IR."""

from __future__ import annotations

from typing import Any

from .debug import DebugRenderer, render_debug
from .protocol import CapabilityRenderer

__all__ = [
    "CapabilityRenderer",
    "DebugRenderer",
    "NativeMcpRenderer",
    "NativeMcpTool",
    "render_debug",
]

# `NativeMcpRenderer`/`NativeMcpTool` (re-exported from `.native_mcp`, itself
# a shim over `gas_mcp.native`) are the only MCP-dependent names in this
# package. `DebugRenderer`/`CapabilityRenderer` have nothing to do with MCP
# and must stay importable without the optional `mcp` package installed
# (PR 17 review finding: an eager import here made `from gia.renderers
# import DebugRenderer` fail in an mcp-less install). Resolved lazily via
# module `__getattr__` (PEP 562), the same pattern `gia.server` already uses
# for its own `mcp`/`_allowed_hosts` re-export.
_LAZY = {"NativeMcpRenderer": "native_mcp", "NativeMcpTool": "native_mcp"}


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    return getattr(module, name)

