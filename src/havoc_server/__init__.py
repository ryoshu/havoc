"""The Havoc application composition root (PR 17 of the GIA/GAS separation plan).

Wires `havoc_domain`-bucket code (`gia.server.GameRuntime`, still living
under `src/gia/` until PR 18), `gia_gas_adapter.GiaGasAdapter`,
`gas_protocol.service.GasService`, and `gas_mcp` together, replacing
`src/gia/server.py` as the actual MCP composition root. `src/gia/server.py`
now re-exports `mcp` from here for backward compatibility.

`_allowed_hosts`/`build_mcp_server`/`mcp` are re-exported lazily via module
`__getattr__` (PEP 562), the same pattern `gia.server` already uses for its
own `mcp`/`_allowed_hosts` re-export: importing `.app` eagerly here runs its
module-level `mcp, _runtime = build_mcp_server()`, which opens a live
`GameRuntime`/SQLite database as a side effect. RS-03
(docs/GIA-REPOSITORY-SPLIT-PLAN.md) moved the native MCP renderer into this
package as `havoc_server.native_mcp`; without this laziness, merely
importing that renderer — which itself does not need a live server — would
have silently booted the full application.
"""

from __future__ import annotations

from typing import Any

__all__ = ["_allowed_hosts", "build_mcp_server", "mcp"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import app as _app

        return getattr(_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
