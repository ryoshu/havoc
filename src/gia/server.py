"""GAS 2.0 MCP server — get, search, and capability-ID act."""

from __future__ import annotations

import os
import json
from collections.abc import Mapping
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError

from .application import HavocGiaApplication
from .compat import JsonGameRuntimeAdapter
from .context import ONTOLOGY_PATH, GameContext
from .domain import DomainError, HavocEngine
from .gas import GasActionResponse, GasResourceResponse, GasRuntime, WhyNotResponse
from .policy import PolicyProvider, RequestContext
from .responses import ActionResponse, ResourceResponse, format_action_response, format_response
from ..gia_core.requests import ExecuteRequest, GetRequest, ProjectRequest, SearchRequest


class GameRuntime:
    """Thin delegating facade over the GIA application boundary (PR 14).

    Holds a `GameContext` and `HavocEngine` (kept for backward
    compatibility — several tests and adapters reach into `runtime.ctx`
    directly) plus a `HavocGiaApplication`, which owns every authorization,
    applicability, and mutation guarantee. This class's only job is
    building request DTOs and mapping their results back onto the existing
    `ResourceResponse`/`ActionResponse` wire shapes so every external
    consumer (`GasRuntime`, `JsonGameRuntimeAdapter`, the MCP tool
    functions) keeps working unchanged.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        request_context: RequestContext | None = None,
        policy_provider: PolicyProvider | None = None,
    ):
        self.request_context = request_context or RequestContext.system()
        self.ctx = GameContext(db_path=db_path, policy_provider=policy_provider)
        self.engine = HavocEngine()
        self._application = HavocGiaApplication(self.ctx, request_context=self.request_context)

    def create_session(self) -> ResourceResponse:
        """Create an isolated game session and return its initial state."""
        result = self._application.create_session()
        return format_response(result.data, result.affordances, state_revision=result.state_revision)

    def capability_set(self, session_id: str):
        """Return the contextual GIA capability IR for this runtime actor."""
        return self._application.project(ProjectRequest(session_id=session_id))

    # Explicit name for callers that prefer a getter-shaped API.
    get_capability_set = capability_set

    def get(
        self,
        resource_type: str,
        id: str = "",
        session_id: str = "",
    ) -> ResourceResponse:
        """Retrieve a resource by type and ID."""
        result = self._application.get(
            GetRequest(resource_type=resource_type, id=id, session_id=session_id)
        )
        return format_response(result.data, result.affordances, state_revision=result.state_revision)

    def search(
        self,
        resource_type: str,
        filters: Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> ResourceResponse:
        """Search or browse resources."""
        result = self._application.search(
            SearchRequest(resource_type=resource_type, filters=filters, session_id=session_id)
        )
        return format_response(result.data, result.affordances, state_revision=result.state_revision)

    def act(
        self,
        action: str = "",
        params: Mapping[str, Any] | None = None,
        session_id: str = "",
        expected_revision: int | None = None,
        affordance_id: str | None = None,
        idempotency_key: str | None = None,
        capability_id: str | None = None,
        policy_version: str | None = None,
        request_context: RequestContext | None = None,
        request_id: str | None = None,
        client_metadata: Mapping[str, Any] | None = None,
        model_metadata: Mapping[str, Any] | None = None,
        untrusted_rationale: str | None = None,
        sensitive_fields: tuple[str, ...] = (),
    ) -> ActionResponse:
        """Execute one action through the execution service (PR 5).

        This method's only job is request shaping and response formatting;
        `commands.execution.execute` (via `HavocGiaApplication.execute`)
        owns every mutation guarantee (revalidation, transaction,
        idempotency, decision provenance) and needs nothing from
        `GameRuntime` or MCP to do it.
        """
        result = self._application.execute(
            ExecuteRequest(
                session_id=session_id,
                action=action,
                params=params,
                expected_revision=expected_revision,
                affordance_id=affordance_id,
                idempotency_key=idempotency_key,
                request_context=request_context,
                capability_id=capability_id,
                policy_version=policy_version,
                request_id=request_id,
                client_metadata=client_metadata,
                model_metadata=model_metadata,
                untrusted_rationale=untrusted_rationale,
                sensitive_fields=sensitive_fields,
            )
        )
        return format_action_response(
            result.data, result.affordances, result.events, state_revision=result.state_revision
        )


# ---------------------------------------------------------------------------
# Module-level server entry point. Stateful requests must carry their session
# handle; importing this module does not create a game.
# ---------------------------------------------------------------------------

def _configured_db_path() -> str:
    """Return the database path used by the module-level MCP runtime."""
    return os.environ.get("GIA_DB_PATH", ":memory:")


_default = GameRuntime(db_path=_configured_db_path())
_legacy = JsonGameRuntimeAdapter(_default)
_gas = GasRuntime(_default)
ctx = _default.ctx
engine = _default.engine


# --- Tools ---

mcp = MCPServer(
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


def _resource_json(value: Any) -> str:
    """Serialize immutable knowledge deterministically for MCP resources."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


@mcp.resource(
    "gia://rules",
    name="rules",
    title="EAT THE REICH rules",
    description="Immutable game rules and mechanics.",
    mime_type="application/json",
)
def rules_resource() -> str:
    return _resource_json(_default.ctx.graph.get_rules())


@mcp.resource(
    "gia://characters",
    name="characters",
    title="Playable characters",
    description="Immutable playable character templates.",
    mime_type="application/json",
)
def characters_resource() -> str:
    return _resource_json([
        template.model_dump(mode="json")
        for template in _default.ctx.get_all_character_templates()
    ])


@mcp.resource(
    "gia://enemies",
    name="enemies",
    title="Enemy catalogue",
    description="Immutable enemy and Übermensch templates.",
    mime_type="application/json",
)
def enemies_resource() -> str:
    return _resource_json(_default.ctx.graph.get_all_enemies())


@mcp.resource(
    "gia://locations",
    name="locations",
    title="Paris locations",
    description="Immutable location, objective, and route templates.",
    mime_type="application/json",
)
def locations_resource() -> str:
    return _resource_json([
        location.model_dump(mode="json")
        for location in _default.ctx.get_all_locations()
    ])


@mcp.resource(
    "gia://ontology",
    name="ontology",
    title="GIA ontology",
    description="The immutable EAT THE REICH RDF ontology.",
    mime_type="text/turtle",
)
def ontology_resource() -> str:
    return ONTOLOGY_PATH.read_text(encoding="utf-8")


ResourceType = Literal[
    "session",
    "character",
    "character_template",
    "location",
    "scene",
    "enemy",
    "rules",
]
SearchType = Literal["characters", "locations", "enemies", "ubermenschen"]
ActionName = Literal[
    "allocate_dice",
    "build_dice_pool",
    "check_inventory",
    "choose_next_location",
    "engage_threat",
    "heal",
    "loot",
    "move_to_location",
    "next_turn",
    "retreat",
    "select_character",
    "share_blood",
    "start_mission",
    "trigger_last_stand",
    "use_flashback",
    "view_character_sheet",
    "view_character_template",
    "view_epilogue",
    "view_scene",
]

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
MUTATION_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


@mcp.tool(
    name="create_session",
    title="Create game session",
    description="Create an isolated game session and return its handle and initial GAS capability set.",
    annotations=MUTATION_ANNOTATIONS,
    structured_output=True,
)
def mcp_create_session() -> GasResourceResponse:
    return _gas.create_session()


def _call_gas(operation):
    """Translate typed domain failures into stable MCP protocol errors."""
    try:
        return operation()
    except DomainError as error:
        raise MCPError(
            -32000,
            error.code,
            {
                "code": error.code,
                "message": str(error),
                "details": error.details,
            },
        ) from error


@mcp.tool(
    name="get",
    title="Get game resource",
    description="Read a GAS resource URI. Stateful URIs carry their session scope; immutable knowledge needs no session.",
    annotations=READ_ONLY_ANNOTATIONS,
    structured_output=True,
)
def mcp_get(
    resource_uri: str,
    view: str | None = None,
    at_revision: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> GasResourceResponse:
    return _call_gas(lambda: _gas.get(resource_uri, view, at_revision, cursor, limit))


@mcp.tool(
    name="search",
    title="Search game knowledge",
    description="Search game knowledge with a typed query. Results carry links and the contextual GAS command set when scoped.",
    annotations=READ_ONLY_ANNOTATIONS,
    structured_output=True,
)
def mcp_search(
    resource_type: SearchType,
    query: dict[str, Any] | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    session_id: str = "",
) -> GasResourceResponse:
    return _call_gas(lambda: _gas.search(resource_type, query, cursor, limit, session_id=session_id))


@mcp.tool(
    name="act",
    title="Execute game action",
    description="Execute a previously advertised GAS capability. The capability ID binds the command, target, actor, scope, revision, and policy; action names are not accepted.",
    annotations=MUTATION_ANNOTATIONS,
    structured_output=True,
)
def mcp_act(
    capability_id: str,
    expected_revision: int,
    input: dict[str, Any],
    idempotency_key: str,
    session_id: str = "",
    scope: str | None = None,
    request_id: str | None = None,
    client_metadata: dict[str, Any] | None = None,
    model_metadata: dict[str, Any] | None = None,
    untrusted_rationale: str | None = None,
    sensitive_fields: list[str] | None = None,
) -> GasActionResponse:
    return _call_gas(
        lambda: _gas.act(
            capability_id,
            expected_revision,
            input,
            idempotency_key,
            session_id=session_id,
            scope=scope,
            request_id=request_id,
            client_metadata=client_metadata,
            model_metadata=model_metadata,
            untrusted_rationale=untrusted_rationale,
            sensitive_fields=sensitive_fields or (),
        )
    )


@mcp.tool(
    name="why_not",
    title="Diagnose unavailable command",
    description=(
        "Read-only diagnostic for a command that is unavailable in the current "
        "state or policy. It never returns an executable capability."
    ),
    annotations=READ_ONLY_ANNOTATIONS,
    structured_output=True,
)
def mcp_why_not(
    resource_uri: str,
    command: str,
    input: dict[str, Any] | None = None,
) -> WhyNotResponse:
    return _call_gas(lambda: _gas.why_not(resource_uri, command, input))


# Legacy JSON entry points remain explicit and undecorated. They are used by
# the playthrough/evaluation adapters until PR10 removes the compatibility
# boundary.
def create_session() -> str:
    """Legacy JSON session creation wrapper."""
    return _legacy.create_session()


def get(resource_type: str, id: str = "", session_id: str = "") -> str:
    """Retrieve a resource by type and ID. Returns data + available affordances.

    resource_type: "session", "character", "character_template", "location", "scene", "enemy", "rules"
    id: resource ID (template_id for templates, character_id for characters, etc.)
    session_id: required for stateful resources; omit for immutable knowledge
    """
    return _legacy.get(resource_type, id, session_id)


def search(resource_type: str, filters: str = "{}", session_id: str = "") -> str:
    """Search/browse resources. Returns results + available affordances.

    resource_type: "characters", "locations", "enemies", "ubermenschen"
    filters: JSON string, e.g. {"sector": 3} for locations
    session_id: required only when requesting state affordances
    """
    return _legacy.search(resource_type, filters, session_id)


def act(
    action: str,
    params: str = "{}",
    session_id: str = "",
    expected_revision: int | None = None,
    affordance_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Execute an action discovered via affordances. Returns result + next affordances.

    action: action name from affordances
    params: JSON string of action parameters
    session_id: required
    """
    return _legacy.act(action, params, session_id, expected_revision, affordance_id, idempotency_key)


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


if __name__ == "__main__":
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
