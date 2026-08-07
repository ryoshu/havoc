"""The Havoc-backed concrete implementation of the GIA application boundary
(PR 14 of the GIA/GAS 2.0 plan; moved here, and its ``get``/``search``
resource-type conditional trees replaced by a registry, in PR 18).

``HavocGiaApplication`` implements both ``gia_core.ports.ResourceProvider``
and ``gia_core.ports.CapabilityAuthority`` over one ``GameContext``. It is
intentionally Havoc-coupled inside — it dispatches on concrete resource
types and calls into the concrete command kernel/execution service — the
same way a ``Command`` subclass is Havoc-coupled while the ``Command`` ABC
itself is not. What matters for ``gia_core``'s own neutrality is that
nothing in ``gia_core`` imports this module or any Havoc type — see
``src/gia_core/approval_workflow.py`` for a second, unrelated domain
implementing the same two ports with none of this.

``get``/``search`` dispatch through ``gia_core.resource_registry
.ResourceRegistry`` (one instance per operation, built once in
``__init__``) instead of an inline ``if resource_type == "..."`` chain —
the same shape ``gia_core.registry.CommandRegistry`` already uses for
command dispatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gia.capabilities import CapabilitySet
from gia.policy import RequestContext
from gia_core.errors import (
    InvalidInputError,
    ResourceNotFoundError,
    ScopeMismatchError,
    UnsupportedOperationError,
)
from gia_core.requests import (
    DiagnoseRequest,
    DiagnoseResult,
    ExecuteRequest,
    ExecuteResult,
    GetRequest,
    GetResult,
    ProjectRequest,
    SearchRequest,
    SearchResult,
)
from gia_core.resource_registry import ResourceRegistry
from havoc_domain.context import GameContext
from havoc_domain.execution import execute as execute_action
from havoc_domain.kernel import compute_affordances, diagnose_command, project_capability_set
from havoc_domain.models import GameSession


class HavocGiaApplication:
    """Havoc's `ResourceProvider` + `CapabilityAuthority` implementation."""

    def __init__(
        self,
        ctx: GameContext,
        *,
        request_context: RequestContext | None = None,
    ) -> None:
        self.ctx = ctx
        self.request_context = request_context or RequestContext.system()
        self._get_registry: ResourceRegistry[GetRequest, GetResult] = ResourceRegistry()
        self._search_registry: ResourceRegistry[SearchRequest, SearchResult] = ResourceRegistry()
        self._register_resource_handlers()

    # --- Shared helpers ---

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise InvalidInputError(
                "session_id is required for stateful operations.",
                details={"parameter": "session_id"},
            )
        return session_id

    @staticmethod
    def _session_id(request: GetRequest | SearchRequest) -> str:
        return request.session_id.strip() if isinstance(request.session_id, str) else ""

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

    def _assert_session_scope(
        self, session_id: str, request_context: RequestContext
    ) -> GameSession | None:
        session = self.ctx.get_session(session_id)
        if session and session.tenant_id != request_context.tenant_id:
            # Deliberately avoid returning the session's tenant or existence.
            raise ScopeMismatchError("The requested scope is not available.")
        return session

    def _state_revision(self, session_id: str | None) -> int | None:
        if not session_id:
            return None
        session = self.ctx.get_session(session_id)
        return session.state_revision if session else None

    # --- Session bootstrapping (not part of either protocol) ---

    def create_session(self) -> GetResult:
        """Create an isolated game session and return its initial state."""
        session = self.ctx.db.create_session(
            tenant_id=self.request_context.tenant_id,
            policy_version=self.ctx.policy_provider.version,
        )
        affordances = compute_affordances(self.ctx, session.id, self.request_context)
        return GetResult(data=session, affordances=affordances, state_revision=session.state_revision)

    # --- ResourceProvider ---

    def get(self, request: GetRequest) -> GetResult:
        handler = self._get_registry.get(request.resource_type)
        if handler is None:
            raise UnsupportedOperationError(
                f"Unknown resource type: {request.resource_type}",
                details={"operation": "get", "resource_type": request.resource_type},
            )
        return handler(request)

    def search(self, request: SearchRequest) -> SearchResult:
        handler = self._search_registry.get(request.resource_type)
        if handler is None:
            raise UnsupportedOperationError(
                f"Unknown search type: {request.resource_type}",
                details={"operation": "search", "resource_type": request.resource_type},
            )
        return handler(request)

    def _register_resource_handlers(self) -> None:
        self._get_registry.register("session", self._get_session)
        self._get_registry.register("character", self._get_character)
        self._get_registry.register("character_template", self._get_character_template)
        self._get_registry.register("location", self._get_location)
        self._get_registry.register("scene", self._get_scene)
        self._get_registry.register("enemy", self._get_enemy)
        self._get_registry.register("rules", self._get_rules)

        self._search_registry.register("characters", self._search_characters)
        self._search_registry.register("locations", self._search_locations)
        self._search_registry.register("enemies", self._search_enemies)
        self._search_registry.register("ubermenschen", self._search_ubermenschen)

    # --- `get` handlers ---

    def _get_session(self, request: GetRequest) -> GetResult:
        context = request.request_context or self.request_context
        sid = self._require_session_id(self._session_id(request))
        target_id = request.id or sid
        session = self.ctx.get_session(target_id)
        if not session:
            raise ResourceNotFoundError(
                f"Session {target_id} not found.",
                details={"resource_type": "session", "id": target_id},
            )
        self._assert_session_scope(target_id, context)
        affordances = compute_affordances(self.ctx, target_id, context)
        return GetResult(data=session, affordances=affordances, state_revision=self._state_revision(target_id))

    def _get_character(self, request: GetRequest) -> GetResult:
        context = request.request_context or self.request_context
        sid = self._require_session_id(self._session_id(request))
        char = self.ctx.db.get_character(request.id)
        if not char or char.session_id != sid:
            raise ResourceNotFoundError(
                f"Character {request.id} not found.",
                details={"resource_type": "character", "id": request.id},
            )
        sheet = self.ctx.get_character_sheet(request.id)
        self._assert_session_scope(sid, context)
        affordances = compute_affordances(self.ctx, sid, context)
        return GetResult(data=sheet, affordances=affordances, state_revision=self._state_revision(sid))

    def _get_character_template(self, request: GetRequest) -> GetResult:
        template = self.ctx.get_character_template(request.id)
        if not template:
            raise ResourceNotFoundError(
                f"Character template {request.id} not found.",
                details={"resource_type": "character_template", "id": request.id},
            )
        return GetResult(data=template, affordances=[], state_revision=None)

    def _get_location(self, request: GetRequest) -> GetResult:
        loc = self.ctx.get_location_template(request.id)
        if not loc:
            raise ResourceNotFoundError(
                f"Location {request.id} not found.",
                details={"resource_type": "location", "id": request.id},
            )
        return GetResult(data=loc, affordances=[], state_revision=None)

    def _get_scene(self, request: GetRequest) -> GetResult:
        context = request.request_context or self.request_context
        sid = self._require_session_id(self._session_id(request))
        scene = self.ctx.get_active_scene(sid)
        if not scene:
            raise ResourceNotFoundError(
                "No active scene.",
                details={"resource_type": "scene", "session_id": sid},
            )
        self._assert_session_scope(sid, context)
        affordances = compute_affordances(self.ctx, sid, context)
        return GetResult(data=scene, affordances=affordances, state_revision=self._state_revision(sid))

    def _get_enemy(self, request: GetRequest) -> GetResult:
        enemy = self.ctx.get_enemy_template(request.id)
        if not enemy:
            raise ResourceNotFoundError(
                f"Enemy {request.id} not found.",
                details={"resource_type": "enemy", "id": request.id},
            )
        return GetResult(data=enemy, affordances=[], state_revision=None)

    def _get_rules(self, request: GetRequest) -> GetResult:
        rules = self.ctx.graph.get_rules()
        return GetResult(data=rules, affordances=[], state_revision=None)

    # --- `search` handlers ---

    def _search_characters(self, request: SearchRequest) -> SearchResult:
        context = request.request_context or self.request_context
        sid = self._session_id(request)
        templates = self.ctx.get_all_character_templates()
        results = [{"id": t.id, "name": t.name, "description": t.description[:100]} for t in templates]
        affordances = compute_affordances(
            self.ctx, self._require_session_id(sid), context,
        ) if sid else []
        return SearchResult(data=results, affordances=affordances, state_revision=self._state_revision(sid or None))

    def _search_locations(self, request: SearchRequest) -> SearchResult:
        context = request.request_context or self.request_context
        sid = self._session_id(request)
        parsed = self._require_mapping(request.filters, "filters")
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
            self.ctx, self._require_session_id(sid), context,
        ) if sid else []
        return SearchResult(data=results, affordances=affordances, state_revision=self._state_revision(sid or None))

    def _search_enemies(self, request: SearchRequest) -> SearchResult:
        context = request.request_context or self.request_context
        sid = self._session_id(request)
        results = self.ctx.graph.get_all_enemies()
        affordances = compute_affordances(
            self.ctx, self._require_session_id(sid), context,
        ) if sid else []
        return SearchResult(data=results, affordances=affordances, state_revision=self._state_revision(sid or None))

    def _search_ubermenschen(self, request: SearchRequest) -> SearchResult:
        context = request.request_context or self.request_context
        sid = self._session_id(request)
        results = self.ctx.graph.get_ubermenschen()
        affordances = compute_affordances(
            self.ctx, self._require_session_id(sid), context,
        ) if sid else []
        return SearchResult(data=results, affordances=affordances, state_revision=self._state_revision(sid or None))

    # --- CapabilityAuthority ---

    def project(self, request: ProjectRequest) -> CapabilitySet:
        sid = self._require_session_id(request.session_id)
        context = request.request_context or self.request_context
        session = self._assert_session_scope(sid, context)
        if not session:
            raise ResourceNotFoundError(
                f"Session {sid} not found.",
                details={"resource_type": "session", "id": sid},
            )
        return project_capability_set(self.ctx, session, context, scope=request.scope)

    def execute(self, request: ExecuteRequest) -> ExecuteResult:
        sid = self._require_session_id(request.session_id)
        params = self._require_mapping(request.params, "params")
        context = request.request_context or self.request_context
        result, events = execute_action(
            self.ctx,
            sid,
            request.action,
            params,
            request.expected_revision,
            request.affordance_id,
            request.idempotency_key,
            request_context=context,
            capability_id=request.capability_id,
            policy_version=request.policy_version,
            request_id=request.request_id,
            client_metadata=request.client_metadata,
            model_metadata=request.model_metadata,
            untrusted_rationale=request.untrusted_rationale,
            sensitive_fields=request.sensitive_fields,
        )
        affordances = compute_affordances(self.ctx, sid, context)
        return ExecuteResult(
            data=result,
            affordances=affordances,
            events=events,
            state_revision=self._state_revision(sid),
        )

    def diagnose(self, request: DiagnoseRequest) -> DiagnoseResult:
        sid = self._require_session_id(request.session_id)
        context = request.request_context or self.request_context
        # Resolve through the tenant/scope guard before touching mutable
        # session state; diagnostics must not become an existence oracle
        # across tenants (mirrors gia_gas_adapter.adapter.GiaGasAdapter.why_not).
        session = self._assert_session_scope(sid, context)
        if not session:
            raise ResourceNotFoundError(
                f"Session {sid} not found.",
                details={"resource_type": "session", "id": sid},
            )
        command = request.command
        if not isinstance(command, str) or not command.strip():
            raise InvalidInputError(
                "command is required for diagnose.",
                details={"parameter": "command"},
            )
        available, reasons, details = diagnose_command(
            self.ctx,
            session,
            command.strip(),
            context,
            dict(request.input) if request.input is not None else None,
        )
        return DiagnoseResult(available=available, reasons=reasons, details=details)
