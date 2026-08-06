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

from .commands.execution import execute as execute_action
from .commands.kernel import compute_affordances, project_capability_set
from .compat import JsonGameRuntimeAdapter
from .context import ONTOLOGY_PATH, GameContext
from .domain import (
    DomainError,
    HavocEngine,
    InvalidInputError,
    ResourceNotFoundError,
    ScopeMismatchError,
    UnsupportedOperationError,
)
from .gas import GasActionResponse, GasResourceResponse, GasRuntime
from .policy import PolicyProvider, RequestContext
from .responses import (
    ActionResponse,
    ResourceResponse,
    format_action_response,
    format_response,
)


class GameRuntime:
    """Encapsulates game state for a single runtime instance.

    Holds a GameContext, HavocEngine, and transient roll state.
    Sessions are created explicitly and are never selected implicitly.
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

    def create_session(self) -> ResourceResponse:
        """Create an isolated game session and return its initial state."""
        session = self.ctx.db.create_session(
            tenant_id=self.request_context.tenant_id,
            policy_version=self.ctx.policy_provider.version,
        )
        return self._format_response(
            session,
            compute_affordances(self.ctx, session.id, self.request_context),
            session.id,
        )

    def _assert_session_scope(self, session_id: str):
        session = self.ctx.get_session(session_id)
        if session and session.tenant_id != self.request_context.tenant_id:
            # Deliberately avoid returning the session's tenant or existence.
            raise ScopeMismatchError("The requested scope is not available.")
        return session

    def capability_set(self, session_id: str):
        """Return the contextual GIA capability IR for this runtime actor."""
        sid = self._require_session_id(session_id)
        session = self._assert_session_scope(sid)
        if not session:
            raise ResourceNotFoundError(
                f"Session {sid} not found.",
                details={"resource_type": "session", "id": sid},
            )
        return project_capability_set(self.ctx, session, self.request_context)

    # Explicit name for callers that prefer a getter-shaped API.
    get_capability_set = capability_set

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise InvalidInputError(
                "session_id is required for stateful operations.",
                details={"parameter": "session_id"},
            )
        return session_id

    def _state_revision(self, session_id: str | None) -> int | None:
        if not session_id:
            return None
        session = self.ctx.get_session(session_id)
        return session.state_revision if session else None

    def _format_response(self, data: Any, affordances: list, session_id: str | None) -> ResourceResponse:
        return format_response(
            data,
            affordances,
            state_revision=self._state_revision(session_id),
        )

    def _format_action_response(
        self,
        data: Any,
        affordances: list,
        events: list,
        session_id: str,
    ) -> ActionResponse:
        return format_action_response(
            data,
            affordances,
            events,
            state_revision=self._state_revision(session_id),
        )

    @staticmethod
    def _require_mapping(
        value: Mapping[str, Any] | None,
        parameter_name: str,
    ) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise InvalidInputError(f"{parameter_name} must be a mapping.")
        return dict(value)

    def get(
        self,
        resource_type: str,
        id: str = "",
        session_id: str = "",
    ) -> ResourceResponse:
        """Retrieve a resource by type and ID."""
        sid = session_id.strip() if isinstance(session_id, str) else ""
        if resource_type == "session":
            sid = self._require_session_id(sid)
            target_id = id or sid
            session = self.ctx.get_session(target_id)
            if not session:
                raise ResourceNotFoundError(
                    f"Session {target_id} not found.",
                    details={"resource_type": "session", "id": target_id},
                )
            self._assert_session_scope(target_id)
            affordances = compute_affordances(self.ctx, target_id, self.request_context)
            return self._format_response(session, affordances, target_id)
        if resource_type == "character":
            sid = self._require_session_id(sid)
            char = self.ctx.db.get_character(id)
            if not char or char.session_id != sid:
                raise ResourceNotFoundError(
                    f"Character {id} not found.",
                    details={"resource_type": "character", "id": id},
                )
            sheet = self.ctx.get_character_sheet(id)
            self._assert_session_scope(sid)
            affordances = compute_affordances(self.ctx, sid, self.request_context)
            return self._format_response(sheet, affordances, sid)
        if resource_type == "character_template":
            template = self.ctx.get_character_template(id)
            if not template:
                raise ResourceNotFoundError(
                    f"Character template {id} not found.",
                    details={"resource_type": "character_template", "id": id},
                )
            return self._format_response(template, [], None)
        if resource_type == "location":
            loc = self.ctx.get_location_template(id)
            if not loc:
                raise ResourceNotFoundError(
                    f"Location {id} not found.",
                    details={"resource_type": "location", "id": id},
                )
            return self._format_response(loc, [], None)
        if resource_type == "scene":
            sid = self._require_session_id(sid)
            scene = self.ctx.get_active_scene(sid)
            if not scene:
                raise ResourceNotFoundError(
                    "No active scene.",
                    details={"resource_type": "scene", "session_id": sid},
                )
            self._assert_session_scope(sid)
            affordances = compute_affordances(self.ctx, sid, self.request_context)
            return self._format_response(scene, affordances, sid)
        if resource_type == "enemy":
            enemy = self.ctx.get_enemy_template(id)
            if not enemy:
                raise ResourceNotFoundError(
                    f"Enemy {id} not found.",
                    details={"resource_type": "enemy", "id": id},
                )
            return self._format_response(enemy, [], None)
        if resource_type == "rules":
            rules = self.ctx.graph.get_rules()
            return self._format_response(rules, [], None)
        raise UnsupportedOperationError(
            f"Unknown resource type: {resource_type}",
            details={"operation": "get", "resource_type": resource_type},
        )

    def search(
        self,
        resource_type: str,
        filters: Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> ResourceResponse:
        """Search or browse resources."""
        sid = session_id.strip() if isinstance(session_id, str) else ""
        parsed = self._require_mapping(filters, "filters")
        if resource_type == "characters":
            templates = self.ctx.get_all_character_templates()
            results = [{"id": t.id, "name": t.name, "description": t.description[:100]} for t in templates]
            affordances = compute_affordances(
                self.ctx, self._require_session_id(sid),
                self.request_context,
            ) if sid else []
            return self._format_response(results, affordances, sid or None)
        if resource_type == "locations":
            locations = self.ctx.get_all_locations()
            if "sector" in parsed:
                locations = [l for l in locations if l.sector == parsed["sector"]]
            results = [
                {
                    "id": l.id, "name": l.name, "sector": l.sector,
                    "objective": l.objective.name, "objective_rating": l.objective.rating,
                }
                for l in locations
            ]
            affordances = compute_affordances(
                self.ctx, self._require_session_id(sid),
                self.request_context,
            ) if sid else []
            return self._format_response(results, affordances, sid or None)
        if resource_type == "enemies":
            results = self.ctx.graph.get_all_enemies()
            affordances = compute_affordances(
                self.ctx, self._require_session_id(sid),
                self.request_context,
            ) if sid else []
            return self._format_response(results, affordances, sid or None)
        if resource_type == "ubermenschen":
            results = self.ctx.graph.get_ubermenschen()
            affordances = compute_affordances(
                self.ctx, self._require_session_id(sid),
                self.request_context,
            ) if sid else []
            return self._format_response(results, affordances, sid or None)
        raise UnsupportedOperationError(
            f"Unknown search type: {resource_type}",
            details={"operation": "search", "resource_type": resource_type},
        )

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
    ) -> ActionResponse:
        """Execute one action through the execution service (PR 5).

        This method's only job is request shaping and response formatting;
        `commands.execution.execute` owns every mutation guarantee
        (revalidation, transaction, idempotency, decision provenance) and
        needs nothing from `GameRuntime` or MCP to do it.
        """
        sid = self._require_session_id(session_id)
        parsed = self._require_mapping(params, "params")
        result, events = execute_action(
            self.ctx,
            sid,
            action,
            parsed,
            expected_revision,
            affordance_id,
            idempotency_key,
            request_context=self.request_context,
            capability_id=capability_id,
            policy_version=policy_version,
        )
        affordances = compute_affordances(self.ctx, sid, self.request_context)
        return self._format_action_response(result, affordances, events, sid)


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
) -> GasResourceResponse:
    return _call_gas(lambda: _gas.get(resource_uri, view, at_revision))


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
) -> GasActionResponse:
    return _call_gas(
        lambda: _gas.act(
            capability_id,
            expected_revision,
            input,
            idempotency_key,
            session_id=session_id,
        )
    )


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
