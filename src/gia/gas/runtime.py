"""Typed GAS 2.0 operations over :class:`gia.server.GameRuntime`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlparse

from ..capabilities import CapabilitySet, Link
from ..domain import InvalidInputError, ResourceNotFoundError, StaleStateError
from ..policy import Scope
from .contracts import GasActionResponse, GasResourceResponse

if TYPE_CHECKING:
    from ..server import GameRuntime


_RESOURCE_TYPES = {
    "session",
    "character",
    "character_template",
    "location",
    "scene",
    "enemy",
    "rules",
}


class GasRuntime:
    """Render the GIA kernel through the GAS 2.0 operation shape.

    The wrapper intentionally has no command registry or policy logic.  It
    delegates reads and mutations to ``GameRuntime`` and renders its
    contextual ``CapabilitySet`` as ``links`` and ``commands``.
    """

    def __init__(self, runtime: GameRuntime, session_id: str = ""):
        self.runtime = runtime
        self._session_id = session_id

    @property
    def ctx(self):
        return self.runtime.ctx

    @property
    def engine(self):
        return self.runtime.engine

    @property
    def default_session_id(self) -> str:
        """Compatibility convenience for local playthrough callers."""
        return self._session_id or getattr(self.runtime, "session_id", "")

    def create_session(self) -> GasResourceResponse:
        response = self.runtime.create_session()
        session_id = response.data["id"]
        self._session_id = session_id
        capabilities = self.runtime.capability_set(session_id)
        return self._response(
            data=response.data,
            capability_set=capabilities,
            links=self._links("session", session_id),
        )

    def get(
        self,
        resource_uri: str,
        view: str | None = None,
        at_revision: int | None = None,
    ) -> GasResourceResponse:
        resource_type, resource_id, session_id, query = self._parse_uri(resource_uri)
        if view not in (None, "state", "capabilities", "default"):
            raise InvalidInputError(
                f"Unknown view: {view}",
                details={"parameter": "view", "view": view},
            )
        if query.get("session_id"):
            session_id = query["session_id"]
        stateful = resource_type in {"session", "character", "scene"}
        if stateful and not session_id:
            session_id = resource_id if resource_type == "session" else ""
        response = self.runtime.get(resource_type, resource_id, session_id)
        if stateful:
            if not session_id:
                raise InvalidInputError(
                    "A session-scoped resource URI must include a session id.",
                    details={"resource_uri": resource_uri},
                )
            session = self.runtime.ctx.get_session(session_id)
            if not session:
                raise ResourceNotFoundError(
                    f"Session {session_id} not found.",
                    details={"resource_type": "session", "id": session_id},
                )
            if at_revision is not None and at_revision != session.state_revision:
                raise StaleStateError(
                    f"Session {session_id} is at revision {session.state_revision}, "
                    f"not {at_revision}.",
                    details={
                        "session_id": session_id,
                        "expected_revision": at_revision,
                        "current_revision": session.state_revision,
                    },
                )
            capability_set = self.runtime.capability_set(session_id)
        else:
            if at_revision is not None:
                raise InvalidInputError(
                    "at_revision is only valid for session-scoped resources.",
                    details={"parameter": "at_revision"},
                )
            capability_set = self._empty_capability_set()
        return self._response(
            data=response.data,
            capability_set=capability_set,
            links=self._links(resource_type, resource_id, session_id or None),
        )

    def search(
        self,
        resource_type: str,
        query: Mapping[str, Any] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        *,
        session_id: str = "",
    ) -> GasResourceResponse:
        if cursor:
            raise InvalidInputError(
                "Pagination cursors are not available until GAS PR8.",
                details={"parameter": "cursor", "cursor": cursor},
            )
        if limit is not None and (isinstance(limit, bool) or limit <= 0):
            raise InvalidInputError(
                "limit must be a positive integer.",
                details={"parameter": "limit"},
            )
        if query is not None and not isinstance(query, Mapping):
            raise InvalidInputError(
                "query must be a mapping.",
                details={"parameter": "query"},
            )
        parsed = dict(query or {})
        # The public contract keeps scope in the request context.  Local
        # callers may use this reserved query key until MCP auth supplies a
        # request-scoped session context.
        scoped_session = session_id or str(parsed.pop("session_id", ""))
        response = self.runtime.search(resource_type, parsed, scoped_session)
        capabilities = (
            self.runtime.capability_set(scoped_session)
            if scoped_session
            else self._empty_capability_set()
        )
        return self._response(
            data=response.data,
            capability_set=capabilities,
            links=self._links(resource_type, None, scoped_session or None),
        )

    def act(
        self,
        capability_id: str,
        expected_revision: int,
        input: Mapping[str, Any] | None,
        idempotency_key: str,
        *,
        session_id: str = "",
    ) -> GasActionResponse:
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise InvalidInputError(
                "capability_id is required for GAS act.",
                details={"parameter": "capability_id"},
            )
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise InvalidInputError(
                "expected_revision must be an integer.",
                details={"parameter": "expected_revision"},
            )
        if not isinstance(session_id, str) or not session_id.strip():
            raise InvalidInputError(
                "session_id is required for GAS act in the local runtime.",
                details={"parameter": "session_id"},
            )
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise InvalidInputError(
                "idempotency_key is required for GAS act.",
                details={"parameter": "idempotency_key"},
            )
        if input is not None and not isinstance(input, Mapping):
            raise InvalidInputError(
                "input must be a mapping.",
                details={"parameter": "input"},
            )
        response = self.runtime.act(
            "",
            dict(input or {}),
            session_id=session_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            capability_id=capability_id,
        )
        capabilities = self.runtime.capability_set(session_id)
        return GasActionResponse(
            data=response.data,
            links=self._links("session", session_id, session_id),
            commands=capabilities.commands,
            subject=capabilities.subject,
            scope=capabilities.scope,
            state_revision=capabilities.state_revision,
            policy_version=capabilities.policy_version,
            complete=capabilities.complete,
            next_cursor=capabilities.next_cursor,
            events=response.events,
        )

    def _empty_capability_set(self) -> CapabilitySet:
        request = self.runtime.request_context
        scope = request.scope or Scope.tenant(request.tenant_id)
        return CapabilitySet(
            subject=request.subject,
            scope=scope.key,
            state_revision=0,
            policy_version=self.runtime.ctx.policy_provider.version,
            complete=True,
        )

    @staticmethod
    def _response(
        *, data: Any, capability_set: CapabilitySet, links: list[Link]
    ) -> GasResourceResponse:
        return GasResourceResponse(
            data=data,
            links=links,
            commands=capability_set.commands,
            subject=capability_set.subject,
            scope=capability_set.scope,
            state_revision=capability_set.state_revision,
            policy_version=capability_set.policy_version,
            complete=capability_set.complete,
            next_cursor=capability_set.next_cursor,
        )

    @staticmethod
    def _links(
        resource_type: str,
        resource_id: str | None = None,
        session_id: str | None = None,
    ) -> list[Link]:
        links = [Link(rel="self", resource_type=resource_type, id=resource_id)]
        if session_id and resource_type == "session":
            links.extend(
                [
                    Link(rel="characters", resource_type="characters"),
                    Link(rel="scene", resource_type="scene"),
                    Link(rel="locations", resource_type="locations"),
                ]
            )
        return links

    @staticmethod
    def _parse_uri(resource_uri: str) -> tuple[str, str, str, dict[str, str]]:
        if not isinstance(resource_uri, str) or not resource_uri.strip():
            raise InvalidInputError(
                "resource_uri must be a non-empty URI.",
                details={"parameter": "resource_uri"},
            )
        parsed = urlparse(resource_uri)
        if parsed.scheme != "gia" or not parsed.netloc:
            raise InvalidInputError(
                "resource_uri must use the gia:// scheme.",
                details={"parameter": "resource_uri"},
            )
        resource_type = unquote(parsed.netloc)
        if resource_type not in _RESOURCE_TYPES:
            raise InvalidInputError(
                f"Unknown resource type: {resource_type}",
                details={"resource_type": resource_type},
            )
        segments = [unquote(part) for part in parsed.path.split("/") if part]
        if len(segments) > 1:
            raise InvalidInputError(
                "resource_uri may contain only one resource id segment.",
                details={"parameter": "resource_uri"},
            )
        resource_id = segments[0] if segments else ""
        query_values = {
            key: values[-1]
            for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
            if values
        }
        session_id = query_values.get("session_id", "")
        if resource_type == "session" and not resource_id:
            raise InvalidInputError(
                "A session URI must include a session id.",
                details={"parameter": "resource_uri"},
            )
        if resource_type != "rules" and resource_type not in {"session"} and not resource_id:
            raise InvalidInputError(
                f"A {resource_type} URI must include a resource id.",
                details={"parameter": "resource_uri"},
            )
        if resource_type == "session":
            session_id = resource_id
        return resource_type, resource_id, session_id, query_values
