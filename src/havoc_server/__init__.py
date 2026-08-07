"""The Havoc application composition root (PR 17 of the GIA/GAS separation plan).

Wires `havoc_domain`-bucket code (`gia.server.GameRuntime`, still living
under `src/gia/` until PR 18), `gia_gas_adapter.GiaGasAdapter`,
`gas_protocol.service.GasService`, and `gas_mcp` together, replacing
`src/gia/server.py` as the actual MCP composition root. `src/gia/server.py`
now re-exports `mcp` from here for backward compatibility.
"""

from __future__ import annotations

from .app import _allowed_hosts, build_mcp_server, mcp

__all__ = ["_allowed_hosts", "build_mcp_server", "mcp"]
