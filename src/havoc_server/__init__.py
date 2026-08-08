"""Havoc application package.

The canonical runtime/composition lives in :mod:`havoc_server.runtime` and
MCP registration/transport lives in :mod:`havoc_server.app`. App imports
stay lazy here so importing the native renderer does not construct a live
SQLite-backed MCP server as a side effect.
"""

from __future__ import annotations

from typing import Any

__all__ = ["_allowed_hosts", "build_mcp_server", "mcp"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import app as _app

        return getattr(_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
