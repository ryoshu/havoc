"""The Havoc composition root (RS-09 of the repository split plan).

Wires configuration, the Havoc domain (`GameRuntime`), GIA (the
`HavocGiaApplication` application boundary), the GIA-GAS adapter
(`GiaGasAdapter`/`GasService`), and MCP transport (`gas_mcp`) together.
This is the application composition root; reusable packages depend only on
the lower-level contracts documented in the repository split plan.

The live MCP server built here runs on `GiaGasAdapter`/`GasService`, via
`havoc_server.runtime.build_gas_service`. Capability-rejection errors
therefore surface GAS's
own stable error vocabulary (e.g. `invalid_input`) rather than `gia_core`'s
raw domain codes (e.g. `action_unavailable`) — a deliberate,
already-documented translation (`gia_gas_adapter.adapter._ERROR_MAP`) that
was built in PR 16 and is wired to the live server for the first time
here.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer
from mcp.server.caching import CacheHint

from gas_mcp import install_gas_mcp
from . import runtime as _runtime
from .runtime import GameRuntime, build_gas_service
from havoc_domain.context import ONTOLOGY_PATH


def _resource_json(value: Any) -> str:
    """Serialize immutable knowledge deterministically for MCP resources."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def build_mcp_server(runtime: GameRuntime | None = None) -> tuple[MCPServer, GameRuntime]:
    """Build a GIA-backed GAS MCP server over ``runtime``.

    Defaults to the canonical Havoc runtime singleton
    (``havoc_server.runtime._default``) so the module-level server shares the
    same state as other first-party callers. Callers that want an isolated
    server (tests) pass their own ``runtime``.
    """
    runtime = runtime if runtime is not None else _runtime._default
    service = build_gas_service(runtime)

    server = MCPServer(
        name="gia-eat-the-reich",
        title="GIA — EAT THE REICH",
        description="Capability-driven TTRPG backend for the EAT THE REICH campaign.",
        instructions=(
            "Create a session before stateful requests. Pass the returned session_id "
            "in the session resource URI and on act/search scope fields. Read the "
            "commands returned by get/search, then call act with the capability_id, "
            "expected_revision, input, and idempotency_key. Capability IDs are "
            "references, not bearer authorization."
        ),
        version="0.2.0",
        cache_hints={
            "resources/list": CacheHint(ttl_ms=3_600_000, scope="public"),
            "resources/read": CacheHint(ttl_ms=3_600_000, scope="public"),
        },
    )

    _install_knowledge_resources(server, runtime)
    install_gas_mcp(server, service)

    return server, runtime


def _install_knowledge_resources(server: MCPServer, runtime: GameRuntime) -> None:
    """Register the static, session-independent knowledge resources.

    These need `runtime.ctx` (Havoc-specific), so they live in the
    composition root rather than the domain-neutral `gas_mcp` installer.
    """

    @server.resource(
        "gia://rules",
        name="rules",
        title="EAT THE REICH rules",
        description="Immutable game rules and mechanics.",
        mime_type="application/json",
    )
    def rules_resource() -> str:
        return _resource_json(runtime.ctx.graph.get_rules())

    @server.resource(
        "gia://characters",
        name="characters",
        title="Playable characters",
        description="Immutable playable character templates.",
        mime_type="application/json",
    )
    def characters_resource() -> str:
        return _resource_json([
            template.model_dump(mode="json")
            for template in runtime.ctx.get_all_character_templates()
        ])

    @server.resource(
        "gia://enemies",
        name="enemies",
        title="Enemy catalogue",
        description="Immutable enemy and Übermensch templates.",
        mime_type="application/json",
    )
    def enemies_resource() -> str:
        return _resource_json(runtime.ctx.graph.get_all_enemies())

    @server.resource(
        "gia://locations",
        name="locations",
        title="Paris locations",
        description="Immutable location, objective, and route templates.",
        mime_type="application/json",
    )
    def locations_resource() -> str:
        return _resource_json([
            location.model_dump(mode="json")
            for location in runtime.ctx.get_all_locations()
        ])

    @server.resource(
        "gia://ontology",
        name="ontology",
        title="GIA ontology",
        description="The immutable EAT THE REICH RDF ontology.",
        mime_type="text/turtle",
    )
    def ontology_resource() -> str:
        return ONTOLOGY_PATH.read_text(encoding="utf-8")


def _allowed_hosts(raw_hosts: list[str], port: int) -> list[str]:
    """Normalize configured hostnames to the complete Host header values."""
    allowed_hosts = []
    for item in raw_hosts:
        item = item.strip()
        if not item:
            continue
        # TransportSecuritySettings matches the complete Host header. A bare
        # hostname therefore needs the bound port appended; callers can still
        # opt into all ports with the SDK's ``:*`` syntax.
        if ":" not in item:
            item = f"{item}:{port}"
        allowed_hosts.append(item)
    return allowed_hosts


mcp, _runtime = build_mcp_server()
