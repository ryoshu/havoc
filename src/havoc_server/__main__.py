"""Transport entry point for the Havoc GIA-GAS MCP server.

Run with ``python -m havoc_server``. This is the canonical application entry
point after RS-09.
"""

from __future__ import annotations

import os

from mcp.server.transport_security import TransportSecuritySettings

from .app import _allowed_hosts, mcp


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        host = os.environ.get("MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("MCP_PORT", "8000"))
        configured_hosts = os.environ.get("MCP_ALLOWED_HOSTS")
        raw_hosts = configured_hosts.split(",") if configured_hosts else [
            host,
            "localhost",
            "127.0.0.1",
        ]
        allowed_hosts = _allowed_hosts(raw_hosts, port)
        mcp.run(
            "streamable-http",
            host=host,
            port=port,
            stateless_http=True,
            transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts),
        )
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
