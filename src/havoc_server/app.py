"""The Havoc composition root (PR 17 of the GIA/GAS separation plan).

Wires configuration, the Havoc domain (`GameRuntime`), GIA (the
`HavocGiaApplication` application boundary), the GIA-GAS adapter
(`GiaGasAdapter`/`GasService`), and MCP transport (`gas_mcp`) together.
This is the only module in the reusable cores allowed to import all of
them at once — see the `composition_root` row of
`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`'s dependency-rules table
("havoc-server | all selected components | domain or policy behavior
implemented directly in the composition root").

The live MCP server built here runs on `GiaGasAdapter`/`GasService`, not
the deprecated `GasRuntime` (`gia.gas.GasRuntime` stays the compatibility
path for the legacy JSON entry points `compat.py` and the Director /
playthrough still use). Capability-rejection errors therefore surface
GAS's own stable error vocabulary (e.g. `invalid_input`) rather than
`gia_core`'s raw domain codes (e.g. `action_unavailable`) — a deliberate,
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
from gas_protocol.service import GasService
from gia.context import ONTOLOGY_PATH
from gia.server import GameRuntime
from gia import server as _gia_server
from gia_gas_adapter import GiaGasAdapter


def _resource_json(value: Any) -> str:
    """Serialize immutable knowledge deterministically for MCP resources."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def build_mcp_server(runtime: GameRuntime | None = None) -> tuple[MCPServer, GameRuntime]:
    """Build a GIA-backed GAS MCP server over ``runtime``.

    Defaults to ``gia.server``'s own module-level singleton (`_default`) so
    the module-level server built below shares the *same* runtime instance
    as the legacy JSON entry points (`gia.server.create_session`/`get`/
    `search`/`act`, still used by `compat.py`/the Director/playthrough) —
    two independently constructed `GameRuntime`s would each open their own
    `:memory:` SQLite database and silently diverge. `gia.server`'s
    singleton is itself canonicalized across the `gia.server`/
    `src.gia.server` import-path duality via `gia._runtime_cache` (see that
    module's docstring), so this stays correct regardless of which spelling
    a caller used to reach `gia.server` first. Callers that want an
    isolated server (tests) pass their own `runtime`.
    """
    runtime = runtime if runtime is not None else _gia_server._default

    adapter = GiaGasAdapter(
        runtime._application,
        runtime._application,
        runtime._application,
        policy_provider=runtime.ctx.policy_provider,
        request_context=runtime.request_context,
    )
    service = GasService(adapter, scheme="gia")

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
