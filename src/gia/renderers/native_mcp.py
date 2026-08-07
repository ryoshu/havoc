"""Backward-compatible re-export.

``NativeMcpRenderer``/``NativeMcpTool`` moved to ``gas_mcp.native`` in PR 17
(`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`) — this was PR 13's mapped
target for this file (see ``docs/gia2/DEPENDENCY-BOUNDARIES.md``'s
``mcp_transport`` bucket). Re-exported here so every existing
``from .renderers.native_mcp import ...``/``from gia.renderers import
NativeMcpRenderer`` import keeps working unchanged.
"""

from __future__ import annotations

from gas_mcp.native import NativeMcpRenderer, NativeMcpTool

__all__ = ["NativeMcpRenderer", "NativeMcpTool"]
