"""Concrete Eat the Reich game runtime.

This module owns domain-specific state, persistence, and mechanics. The
application-level GIA-to-GAS composition is separate in
``havoc_server.runtime`` so the domain package remains independent of MCP
transport and application wiring.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gia_core.policy import PolicyProvider, RequestContext
from gia_core.responses import ActionResponse, ResourceResponse, format_action_response, format_response
from gia_core.requests import ExecuteRequest, GetRequest, ProjectRequest, SearchRequest
from havoc_domain.application import HavocGiaApplication
from havoc_domain.context import GameContext
from havoc_domain.engine import HavocEngine


class GameRuntime:
    """Thin delegating facade over the GIA application boundary (PR 14).

    Holds a `GameContext` and `HavocEngine` (kept for backward
    compatibility — several tests and adapters reach into `runtime.ctx`
    directly) plus a `HavocGiaApplication`, which owns every authorization,
    applicability, and mutation guarantee. This class's only job is
    building request DTOs and mapping their results back onto the existing
    `ResourceResponse`/`ActionResponse` wire shapes so every external
    consumer (`havoc_server.runtime.build_gas_service`'s `GasService`,
    `havoc_server`'s
    MCP tools) keeps working unchanged.
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
