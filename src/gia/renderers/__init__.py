"""Backward-compatible home for the MCP-dependent capability renderer.

``CapabilityRenderer``/``DebugRenderer`` moved to the transport-neutral
``gia_core.renderers`` in RS-02 (`docs/GIA-REPOSITORY-SPLIT-PLAN.md`) since
they have nothing to do with MCP and must stay importable without the
optional `mcp` package installed. ``NativeMcpRenderer``/``NativeMcpTool``
stay here — re-exported from `.native_mcp`, itself a shim over
``gas_mcp.native`` — because they are the only MCP-dependent names in this
package (PR 17 review finding: an eager import here made `from gia.renderers
import DebugRenderer` fail in an mcp-less install). Resolved lazily via
module `__getattr__` (PEP 562), the same pattern `gia.server` already uses
for its own `mcp`/`_allowed_hosts` re-export.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "NativeMcpRenderer",
    "NativeMcpTool",
]

_LAZY = {"NativeMcpRenderer": "native_mcp", "NativeMcpTool": "native_mcp"}


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    return getattr(module, name)
