"""Havoc composition object + compatibility re-export.

`GameRuntime` is the thin delegating facade over the GIA application
boundary (PR 14) that both the legacy JSON compatibility path
(`compat.py`/`gia.gas.GasRuntime`, still used by the Director and
playthrough runner) and the live MCP server (`havoc_server`, PR 17) build
on. MCP registration itself — the `MCPServer` instance, its resources and
tools, and the transport entry point — moved to `havoc_server` in PR 17
(`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`); `mcp` and `_allowed_hosts`
are re-exported below (lazily, so importing `GameRuntime` alone never
requires the `mcp` package to be installed) so every existing
`from src.gia.server import mcp, ...` keeps working, and
`uv run python -m src.gia.server` keeps working as a compatibility alias
for `uv run python -m havoc_server`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal

from .application import HavocGiaApplication
from .compat import JsonGameRuntimeAdapter
from .context import GameContext
from .domain import HavocEngine
from .gas import GasRuntime
from .policy import PolicyProvider, RequestContext
from .responses import ActionResponse, ResourceResponse, format_action_response, format_response
from gia_core.requests import ExecuteRequest, GetRequest, ProjectRequest, SearchRequest


class GameRuntime:
    """Thin delegating facade over the GIA application boundary (PR 14).

    Holds a `GameContext` and `HavocEngine` (kept for backward
    compatibility — several tests and adapters reach into `runtime.ctx`
    directly) plus a `HavocGiaApplication`, which owns every authorization,
    applicability, and mutation guarantee. This class's only job is
    building request DTOs and mapping their results back onto the existing
    `ResourceResponse`/`ActionResponse` wire shapes so every external
    consumer (`GasRuntime`, `JsonGameRuntimeAdapter`, `havoc_server`'s MCP
    tools) keeps working unchanged.
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
# Module-level runtime. Stateful requests must carry their session handle;
# importing this module does not create a game.
#
# Constructed through `gia._runtime_cache` (always the same, single bare
# module regardless of whether *this* file is currently executing as
# `gia.server` or `src.gia.server`) rather than directly, so the singleton
# is canonical across both import paths — see that module's docstring.
# ---------------------------------------------------------------------------

import gia._runtime_cache as _runtime_cache  # noqa: E402


def _configured_db_path() -> str:
    """Return the database path used by the module-level runtime."""
    return os.environ.get("GIA_DB_PATH", ":memory:")


if not hasattr(_runtime_cache, "_default"):
    _runtime_cache._default = GameRuntime(db_path=_configured_db_path())
    _runtime_cache._legacy = JsonGameRuntimeAdapter(_runtime_cache._default)
    _runtime_cache._gas = GasRuntime(_runtime_cache._default)
    _runtime_cache.ctx = _runtime_cache._default.ctx
    _runtime_cache.engine = _runtime_cache._default.engine

_default = _runtime_cache._default
_legacy = _runtime_cache._legacy
_gas = _runtime_cache._gas
ctx = _runtime_cache.ctx
engine = _runtime_cache.engine


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


# --- PR 17 compatibility re-export -----------------------------------------
#
# `mcp`/`_allowed_hosts` moved to `havoc_server` (the actual MCP composition
# root). Re-exported lazily via module `__getattr__` (PEP 562) so that
# `from src.gia.server import GameRuntime` — the overwhelming majority of
# this module's callers — never imports `havoc_server` or the `mcp`
# package; only a caller that actually asks for `mcp`/`_allowed_hosts`
# pays that cost.
def __getattr__(name: str) -> Any:
    if name in ("mcp", "_allowed_hosts"):
        from havoc_server import app as _havoc_server_app

        return getattr(_havoc_server_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    from havoc_server.__main__ import main

    main()
