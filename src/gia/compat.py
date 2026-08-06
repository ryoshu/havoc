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

    def __init__(self, runtime: GameRuntime):
        self.runtime = runtime

    @property
    def ctx(self):
        return self.runtime.ctx

    @property
    def engine(self):
        return self.runtime.engine

    @property
    def default_session_id(self) -> str:
        return self.runtime.default_session_id

    @property
    def _pending_rolls(self) -> dict[str, dict]:
        return self.runtime._pending_rolls

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
    def _serialize(response: ResourceResponse) -> str:
        payload = response.model_dump(mode="json", by_alias=True)
        if payload.get("events") == []:
            payload.pop("events")
        return json.dumps(payload, indent=2)

    def _invoke(
        self,
        operation: Callable[[], ResponseT],
        session_id: str,
    ) -> str:
        try:
            return self._serialize(operation())
        except DomainError as error:
            sid = session_id or self.default_session_id
            affordances = compute_affordances(self.ctx, sid)
            response = format_error(error, affordances)
            payload = response.model_dump(mode="json", by_alias=True)
            payload["error"] = payload["error"]["message"]
            return json.dumps(payload, indent=2)

    def get(self, resource_type: str, id: str = "", session_id: str = "") -> str:
        return self._invoke(
            lambda: self.runtime.get(resource_type, id, session_id),
            session_id,
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
                session_id,
            ),
            session_id,
        )

    def act(
        self,
        action: str,
        params: str | Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        return self._invoke(
            lambda: self.runtime.act(
                action,
                self._parse_mapping(params, "params"),
                session_id,
            ),
            session_id,
        )
