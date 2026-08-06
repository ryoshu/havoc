"""Temporary JSON compatibility boundary for pre-MCP-v2 callers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from .affordances import compute_affordances
from .domain import DomainError, InvalidInputError
from .responses import ResourceResponse, format_error

if TYPE_CHECKING:
    from .server import GameRuntime


ResponseT = TypeVar("ResponseT", bound=ResourceResponse)


class JsonGameRuntimeAdapter:
    """Preserve the original JSON-string API around a typed ``GameRuntime``.

    This adapter is intentionally temporary. MCP v2 transports will consume the
    typed runtime directly after the server migration, while legacy playthrough
    and evaluation callers can continue to parse JSON strings in the meantime.
    """

    def __init__(self, runtime: GameRuntime, session_id: str = ""):
        self.runtime = runtime
        self.session_id = session_id

    @property
    def ctx(self):
        return self.runtime.ctx

    @property
    def engine(self):
        return self.runtime.engine

    @property
    def default_session_id(self) -> str:
        """Compatibility name for callers that explicitly provision a session."""
        return self.session_id

    def create_session(self) -> str:
        """Provision a session for a CLI/playthrough entry point.

        The returned handle is intentionally not stored as an implicit default;
        callers must pass it on every stateful request.
        """
        response = self.runtime.create_session()
        return self._serialize(response)

    def _resolve_session_id(self, session_id: str) -> str:
        return session_id or self.session_id

    @staticmethod
    def _parse_mapping(value: str | Mapping[str, Any] | None, name: str) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        if not isinstance(value, str):
            raise InvalidInputError(f"{name} must be a JSON object or mapping.")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise InvalidInputError(
                f"Malformed JSON in {name}: {error.msg}.",
                details={"parameter": name},
            ) from error
        if not isinstance(parsed, dict):
            raise InvalidInputError(
                f"{name} must decode to a JSON object.",
                details={"parameter": name},
            )
        return parsed

    @staticmethod
    def _legacy_payload(payload: dict) -> dict:
        """Downgrade complete schemas for callers written against PR 2 JSON."""
        for affordance in payload.get("affordances", []):
            schema = affordance.get("schema", {})
            if schema.get("type") == "object" and "properties" in schema:
                affordance["schema"] = schema["properties"]
        return payload

    @staticmethod
    def _serialize(response: ResourceResponse) -> str:
        payload = response.model_dump(mode="json", by_alias=True)
        if payload.get("events") == []:
            payload.pop("events")
        return json.dumps(JsonGameRuntimeAdapter._legacy_payload(payload), indent=2)

    def _invoke(
        self,
        operation: Callable[[], ResponseT],
        session_id: str,
    ) -> str:
        try:
            return self._serialize(operation())
        except DomainError as error:
            sid = self._resolve_session_id(session_id)
            affordances = compute_affordances(self.ctx, sid) if sid else []
            session = self.ctx.get_session(sid) if sid else None
            response = format_error(
                error,
                affordances,
                state_revision=session.state_revision if session else None,
            )
            payload = response.model_dump(mode="json", by_alias=True)
            payload["error"] = payload["error"]["message"]
            return json.dumps(self._legacy_payload(payload), indent=2)

    def get(self, resource_type: str, id: str = "", session_id: str = "") -> str:
        return self._invoke(
            lambda: self.runtime.get(resource_type, id, self._resolve_session_id(session_id)),
            self._resolve_session_id(session_id),
        )

    def search(
        self,
        resource_type: str,
        filters: str | Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        return self._invoke(
            lambda: self.runtime.search(
                resource_type,
                self._parse_mapping(filters, "filters"),
                self._resolve_session_id(session_id),
            ),
            self._resolve_session_id(session_id),
        )

    def act(
        self,
        action: str,
        params: str | Mapping[str, Any] | None = None,
        session_id: str = "",
        expected_revision: int | None = None,
        affordance_id: str | None = None,
    ) -> str:
        def operation():
            revision = expected_revision
            if revision is None:
                sid = self._resolve_session_id(session_id)
                revision = self.runtime.get("session", session_id=sid).state_revision
            return self.runtime.act(
                action,
                self._parse_mapping(params, "params"),
                self._resolve_session_id(session_id),
                revision,
                affordance_id,
            )

        return self._invoke(
            operation,
            self._resolve_session_id(session_id),
        )
