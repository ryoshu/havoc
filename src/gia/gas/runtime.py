"""Typed GAS 2.0 operations over :class:`gia.server.GameRuntime`.

The renderer owns view shaping only.  Cursors identify a read snapshot and
are rejected when state or policy changes; executable capabilities continue
to be re-derived by the GIA reference monitor at mutation time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from gas_protocol import cursor as _gas_cursor
from gas_protocol import errors as _gas_errors
from gas_protocol import pagination as _gas_pagination
from gas_protocol import uri as _gas_uri
from gas_protocol.contracts import Command as _GasCommand

from ..capabilities import BindingTemplate, Capability, CapabilitySet, Link
from ..capabilities.ids import compute_binding_key, compute_capability_id
from ..commands.kernel import diagnose_command
from ..domain import (
    DomainError,
    InvalidInputError,
    ResourceNotFoundError,
    StaleStateError,
    StaleViewError,
)
from ..policy import Scope
from .contracts import GasActionResponse, GasResourceResponse, WhyNotResponse

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

# GasRuntime is the deprecated, Havoc-coupled compatibility path (PR 15 of
# the GIA/GAS 2.0 plan): its cursor/pagination/URI *mechanics* now delegate
# to the independently-tested gas_protocol package, but it keeps raising
# exactly the gia_core errors it always has (server.py's MCP tool wrapper
# catches `DomainError` around every GAS call) rather than the new, separate
# `gas_protocol.errors.GasError` hierarchy. This maps the narrow set of
# gas_protocol errors those delegated calls can raise back to their
# gia_core equivalent. Mapping GIA failures to *GAS's own* stable error
# vocabulary for real is PR 16's job (the GiaGasAdapter), not this one's.
_ERROR_MAP: dict[type[_gas_errors.GasError], type[DomainError]] = {
    _gas_errors.InvalidInputError: InvalidInputError,
    _gas_errors.StaleViewError: StaleViewError,
}


def _translate(error: _gas_errors.GasError) -> DomainError:
    mapped = _ERROR_MAP.get(type(error), InvalidInputError)
    return mapped(str(error), details=error.details)


class GasRuntime:
    """Render the GIA kernel through the GAS 2.0 operation shape.

    ``max_commands`` and ``max_page_size`` are explicit payload budgets.  A
    caller can request a smaller page, but never a page larger than the
    renderer's deterministic budget.
    """

    def __init__(
        self,
        runtime: GameRuntime,
        session_id: str = "",
        *,
        max_commands: int = 64,
        max_page_size: int = 50,
    ):
        if isinstance(max_commands, bool) or max_commands <= 0:
            raise ValueError("max_commands must be a positive integer.")
        if isinstance(max_page_size, bool) or max_page_size <= 0:
            raise ValueError("max_page_size must be a positive integer.")
        self.runtime = runtime
        self._session_id = session_id
        self.max_commands = max_commands
        self.max_page_size = max_page_size

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
        scope = Scope.session(self.runtime.request_context.tenant_id, session_id)
        capability_set, _, has_more = self._capability_page(
            capabilities, scope=scope, command_offset=0, limit=None
        )
        return self._response(
            data=response.data,
            capability_set=capability_set,
            links=self._links("session", session_id),
            next_cursor=self._next_cursor(
                kind="capabilities",
                resource_type="session",
                resource_id=session_id,
                session_id=session_id,
                scope=scope,
                state_revision=capabilities.state_revision,
                policy_version=capabilities.policy_version,
                query={},
                data_offset=0,
                command_offset=self.max_commands,
            ) if has_more else None,
        )

    def get(
        self,
        resource_uri: str,
        view: str | None = None,
        at_revision: int | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> GasResourceResponse:
        resource_type, resource_id, session_id, query = self._parse_uri(resource_uri)
        self._validate_limit(limit)
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
        if stateful and not session_id:
            raise InvalidInputError(
                "A session-scoped resource URI must include a session id.",
                details={"resource_uri": resource_uri},
            )

        response = self.runtime.get(resource_type, resource_id, session_id)
        session = self.runtime.ctx.get_session(session_id) if session_id else None
        if session_id and not session:
            raise ResourceNotFoundError(
                f"Session {session_id} not found.",
                details={"resource_type": "session", "id": session_id},
            )
        if at_revision is not None:
            if not session_id:
                raise InvalidInputError(
                    "at_revision requires a session-scoped request.",
                    details={"parameter": "at_revision"},
                )
            if session and at_revision != session.state_revision:
                raise StaleStateError(
                    f"Session {session_id} is at revision {session.state_revision}, not {at_revision}.",
                    details={
                        "session_id": session_id,
                        "expected_revision": at_revision,
                        "current_revision": session.state_revision,
                    },
                )

        base = (
            self.runtime.capability_set(session_id)
            if session_id
            else self._empty_capability_set()
        )
        scope = self._scope_for_resource(resource_type, resource_id, session_id)
        local = bool(session_id and resource_type != "session")
        if local:
            base = self._localize(base, resource_type, resource_id, scope)
        else:
            base = self._recontextualize(base, scope)

        cursor_payload = self._prepare_cursor(
            cursor,
            kind="capabilities",
            resource_type=resource_type,
            resource_id=resource_id,
            session_id=session_id,
            scope=scope,
            state_revision=base.state_revision,
            policy_version=base.policy_version,
            query={},
        )
        offset = cursor_payload.get("command_offset", 0) if cursor_payload else 0
        page, end, has_more = self._capability_page(
            base,
            scope=scope,
            command_offset=offset,
            limit=limit,
            force_incomplete=local,
        )
        next_cursor = (
            self._next_cursor(
                kind="capabilities",
                resource_type=resource_type,
                resource_id=resource_id,
                session_id=session_id,
                scope=scope,
                state_revision=base.state_revision,
                policy_version=base.policy_version,
                query={},
                data_offset=0,
                command_offset=end,
            )
            if has_more
            else None
        )
        return self._response(
            data=response.data,
            capability_set=page,
            links=self._links(resource_type, resource_id, session_id or None),
            next_cursor=next_cursor,
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
        self._validate_limit(limit)
        if query is not None and not isinstance(query, Mapping):
            raise InvalidInputError(
                "query must be a mapping.",
                details={"parameter": "query"},
            )
        parsed = dict(query or {})
        scoped_session = session_id or str(parsed.pop("session_id", ""))
        base = (
            self.runtime.capability_set(scoped_session)
            if scoped_session
            else self._empty_capability_set()
        )
        scope = self._scope_for_collection(resource_type, scoped_session)
        base = self._recontextualize(base, scope)
        session = self.runtime.ctx.get_session(scoped_session) if scoped_session else None
        state_revision = session.state_revision if session else 0
        policy_version = self.runtime.ctx.policy_provider.version
        cursor_payload = self._prepare_cursor(
            cursor,
            kind="search",
            resource_type=resource_type,
            resource_id="",
            session_id=scoped_session,
            scope=scope,
            state_revision=state_revision,
            policy_version=policy_version,
            query=parsed,
        )
        data_offset = cursor_payload.get("data_offset", 0) if cursor_payload else 0
        command_offset = cursor_payload.get("command_offset", 0) if cursor_payload else 0

        response = self.runtime.search(resource_type, parsed, scoped_session)
        values = response.data if isinstance(response.data, list) else list(response.data or [])
        page_size = min(limit or self.max_page_size, self.max_page_size)
        if data_offset > len(values):
            raise InvalidInputError(
                "Cursor offset is outside the current result set.",
                details={"parameter": "cursor", "offset": data_offset},
            )
        data_page = values[data_offset : data_offset + page_size]
        data_end = data_offset + len(data_page)
        data_more = data_end < len(values)
        page, command_end, command_more = self._capability_page(
            base,
            scope=scope,
            command_offset=command_offset,
            limit=limit,
        )
        complete = not data_more and not command_more
        page = page.model_copy(update={"complete": complete})
        next_cursor = (
            self._next_cursor(
                kind="search",
                resource_type=resource_type,
                resource_id="",
                session_id=scoped_session,
                scope=scope,
                state_revision=state_revision,
                policy_version=policy_version,
                query=parsed,
                data_offset=data_end if data_more else len(values),
                command_offset=command_end,
            )
            if data_more or command_more
            else None
        )
        return self._response(
            data=data_page,
            capability_set=page,
            links=self._links(resource_type, None, scoped_session or None),
            next_cursor=next_cursor,
        )

    def act(
        self,
        capability_id: str,
        expected_revision: int,
        input: Mapping[str, Any] | None,
        idempotency_key: str,
        *,
        session_id: str = "",
        scope: str | None = None,
        request_id: str | None = None,
        client_metadata: Mapping[str, Any] | None = None,
        model_metadata: Mapping[str, Any] | None = None,
        untrusted_rationale: str | None = None,
        sensitive_fields: list[str] | tuple[str, ...] = (),
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
        request_context = self.runtime.request_context
        resolved_scope = (
            self._parse_scope(scope)
            if scope
            else self._infer_capability_scope(session_id, capability_id)
        )
        if resolved_scope.tenant_id != request_context.tenant_id:
            raise InvalidInputError(
                "scope does not belong to the authenticated tenant.",
                details={"parameter": "scope"},
            )
        response = self.runtime.act(
            "",
            dict(input or {}),
            session_id=session_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            capability_id=capability_id,
            request_context=request_context.for_scope(resolved_scope),
            request_id=request_id,
            client_metadata=client_metadata,
            model_metadata=model_metadata,
            untrusted_rationale=untrusted_rationale,
            sensitive_fields=tuple(sensitive_fields),
        )
        capabilities = self.runtime.capability_set(session_id)
        session_scope_value = Scope.session(request_context.tenant_id, session_id)
        page, _, has_more = self._capability_page(
            capabilities, scope=session_scope_value, command_offset=0, limit=None
        )
        return GasActionResponse(
            data=response.data,
            links=self._links("session", session_id, session_id),
            commands=page.commands,
            binding_templates=page.binding_templates,
            subject=page.subject,
            scope=page.scope,
            state_revision=page.state_revision,
            policy_version=page.policy_version,
            complete=page.complete and not has_more,
            next_cursor=(
                self._next_cursor(
                    kind="capabilities",
                    resource_type="session",
                    resource_id=session_id,
                    session_id=session_id,
                    scope=session_scope_value,
                    state_revision=page.state_revision,
                    policy_version=page.policy_version,
                    query={},
                    data_offset=0,
                    command_offset=self.max_commands,
                )
                if has_more
                else None
            ),
            events=response.events,
        )

    def why_not(
        self,
        resource_uri: str,
        command: str,
        input: Mapping[str, Any] | None = None,
    ) -> WhyNotResponse:
        """Explain an unavailable command without returning an execution path."""
        resource_type, resource_id, session_id, query = self._parse_uri(resource_uri)
        if query.get("session_id"):
            session_id = query["session_id"]
        if resource_type != "session":
            session_id = query.get("session_id", session_id)
        if not session_id:
            raise InvalidInputError(
                "why_not requires a session-scoped resource URI.",
                details={"parameter": "resource_uri"},
            )
        # Resolve through the runtime's tenant/scope guard before touching
        # mutable session state; diagnostics must not become an existence
        # oracle across tenants.
        self.runtime.capability_set(session_id)
        session = self.runtime.ctx.get_session(session_id)
        if not session:
            raise ResourceNotFoundError(
                f"Session {session_id} not found.",
                details={"resource_type": "session", "id": session_id},
            )
        if not isinstance(command, str) or not command.strip():
            raise InvalidInputError(
                "command is required for why_not.",
                details={"parameter": "command"},
            )
        command = command.strip()
        request = self.runtime.request_context
        scope = Scope.session(request.tenant_id, session_id)
        available, reasons, prerequisites = diagnose_command(
            self.runtime.ctx,
            session,
            command,
            request,
            dict(input) if input is not None else None,
        )
        return WhyNotResponse(
            data={
                "command": command,
                "available": available,
                "reasons": reasons,
                "prerequisites": prerequisites,
            },
            links=self._links(resource_type, resource_id, session_id),
            commands=[],
            binding_templates=[],
            subject=request.subject,
            scope=scope.key,
            state_revision=session.state_revision,
            policy_version=self.runtime.ctx.policy_provider.version,
            complete=True,
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

    def _capability_page(
        self,
        capability_set: CapabilitySet,
        *,
        scope: Scope,
        command_offset: int,
        limit: int | None,
        force_incomplete: bool = False,
    ) -> tuple[CapabilitySet, int, bool]:
        scoped = self._recontextualize(capability_set, scope)
        commands = sorted(scoped.commands, key=lambda value: value.id)
        try:
            sliced = _gas_pagination.paginate_commands(
                commands, offset=command_offset, limit=limit, max_page_size=self.max_commands
            )
        except _gas_errors.GasError as error:
            raise _translate(error) from error
        has_more = sliced.has_more
        templates = self._binding_templates(commands) if has_more else []
        page = CapabilitySet(
            subject=scoped.subject,
            scope=scoped.scope,
            state_revision=scoped.state_revision,
            policy_version=scoped.policy_version,
            complete=scoped.complete and not has_more and not force_incomplete,
            links=scoped.links,
            commands=sliced.commands,
            binding_templates=templates,
        )
        return page, sliced.end_offset, has_more

    @staticmethod
    def _binding_templates(commands: list[Capability]) -> list[BindingTemplate]:
        # gas_protocol.pagination.build_binding_templates constructs its own
        # gas_protocol.contracts.{Command,BindingTemplate} pydantic models
        # internally, which cannot accept GIA's Capability/EffectMetadata
        # instances directly (pydantic does not coerce across unrelated
        # model classes even when their fields match) — round-trip through
        # dicts at this boundary instead of duplicating the grouping and
        # schema-compaction algorithm here.
        generic_commands = [
            _GasCommand.model_validate(command.model_dump(mode="json")) for command in commands
        ]
        generic_templates = _gas_pagination.build_binding_templates(generic_commands)
        return [
            BindingTemplate.model_validate(template.model_dump(mode="json"))
            for template in generic_templates
        ]

    def _localize(
        self,
        capability_set: CapabilitySet,
        resource_type: str,
        resource_id: str,
        scope: Scope,
    ) -> CapabilitySet:
        commands: list[Capability] = []
        for command in capability_set.commands:
            if command.target and command.target.resource_type == resource_type and command.target.id == resource_id:
                commands.append(command)
            elif resource_type == "character" and command.command == "view_character_sheet":
                commands.append(command)
            elif resource_type == "scene" and command.command == "view_scene":
                commands.append(command)
        # Recompute IDs after narrowing the set: resource-local capabilities
        # must carry the resource scope in their contextual hash as well.
        return self._recontextualize(
            capability_set.model_copy(update={"commands": commands, "binding_templates": []}),
            scope,
        )

    def _recontextualize(self, capability_set: CapabilitySet, scope: Scope) -> CapabilitySet:
        if capability_set.scope == scope.key:
            return capability_set
        commands: list[Capability] = []
        for command in capability_set.commands:
            target = command.target.model_dump(mode="json") if command.target else None
            binding = compute_binding_key(
                command=command.command,
                target=target,
                input_schema=command.input_schema,
                constraints=command.constraints,
            )
            # Capability IDs are contextual to the authenticated subject.  The
            # source set carries that subject once for all of its commands.
            capability_id = compute_capability_id(
                command=command.command,
                binding=binding,
                subject=capability_set.subject,
                scope=scope.key,
                state_revision=command.valid_at_revision,
                policy_version=command.policy_version,
            )
            commands.append(command.model_copy(update={"id": capability_id}))
        return capability_set.model_copy(update={"scope": scope.key, "commands": commands})

    def _scope_for_resource(self, resource_type: str, resource_id: str, session_id: str) -> Scope:
        tenant = self.runtime.request_context.tenant_id
        if resource_type == "session":
            return Scope.session(tenant, session_id or resource_id)
        if session_id and resource_id:
            return Scope.resource(tenant, resource_type, resource_id)
        return Scope.tenant(tenant)

    def _scope_for_collection(self, resource_type: str, session_id: str) -> Scope:
        tenant = self.runtime.request_context.tenant_id
        return Scope.collection(tenant, resource_type)

    def _infer_capability_scope(self, session_id: str, capability_id: str) -> Scope:
        """Recover a renderer scope when local transport omits the hint.

        MCP clients normally pass the response ``scope`` on ``act``.  The
        local API also accepts the older shape without it, so compare the
        opaque ID against the finite set of scopes the renderer can have
        issued for this session.  No scope is trusted without re-projection.
        """
        tenant = self.runtime.request_context.tenant_id
        session_scope = Scope.session(tenant, session_id)
        base = self.runtime.capability_set(session_id)
        candidates: list[Scope] = [
            session_scope,
            *(Scope.collection(tenant, value) for value in ("characters", "locations", "enemies", "ubermenschen")),
        ]
        for command in base.commands:
            if command.target:
                candidates.append(
                    Scope.resource(tenant, command.target.resource_type, command.target.id)
                )
        # Read-only local views may bind a command without a target field.
        for character in self.runtime.ctx.db.get_session_characters(session_id):
            candidates.append(Scope.resource(tenant, "character", character.id))
        scene = self.runtime.ctx.get_active_scene(session_id)
        if scene:
            candidates.append(Scope.resource(tenant, "scene", scene.id))
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.key in seen:
                continue
            seen.add(candidate.key)
            scoped = self._recontextualize(base, candidate)
            if any(command.id == capability_id for command in scoped.commands):
                return candidate
        return session_scope

    @staticmethod
    def _parse_scope(value: str) -> Scope:
        try:
            return Scope.from_key(value)
        except (TypeError, ValueError) as error:
            raise InvalidInputError(
                "scope must use the canonical tenant/kind identifier form.",
                details={"parameter": "scope"},
            ) from error

    def _prepare_cursor(
        self,
        cursor: str | None,
        *,
        kind: str,
        resource_type: str,
        resource_id: str,
        session_id: str,
        scope: Scope,
        state_revision: int,
        policy_version: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        try:
            return _gas_cursor.prepare_cursor(
                cursor,
                kind=kind,
                resource_type=resource_type,
                resource_id=resource_id,
                session_id=session_id,
                scope=scope.key,
                state_revision=state_revision,
                policy_version=policy_version,
                query=query,
            )
        except _gas_errors.GasError as error:
            raise _translate(error) from error

    @staticmethod
    def _decode_cursor(cursor: str) -> dict[str, Any]:
        try:
            return _gas_cursor.decode_cursor(cursor)
        except _gas_errors.GasError as error:
            raise _translate(error) from error

    @staticmethod
    def _next_cursor(
        *,
        kind: str,
        resource_type: str,
        resource_id: str,
        session_id: str,
        scope: Scope,
        state_revision: int,
        policy_version: str,
        query: Mapping[str, Any],
        data_offset: int,
        command_offset: int,
    ) -> str:
        return _gas_cursor.encode_cursor(
            kind=kind,
            resource_type=resource_type,
            resource_id=resource_id,
            session_id=session_id,
            scope=scope.key,
            state_revision=state_revision,
            policy_version=policy_version,
            query=query,
            data_offset=data_offset,
            command_offset=command_offset,
        )

    @staticmethod
    def _response(
        *,
        data: Any,
        capability_set: CapabilitySet,
        links: list[Link],
        next_cursor: str | None = None,
    ) -> GasResourceResponse:
        return GasResourceResponse(
            data=data,
            links=links,
            commands=capability_set.commands,
            binding_templates=capability_set.binding_templates,
            subject=capability_set.subject,
            scope=capability_set.scope,
            state_revision=capability_set.state_revision,
            policy_version=capability_set.policy_version,
            complete=capability_set.complete,
            next_cursor=next_cursor,
        )

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is not None and (isinstance(limit, bool) or limit <= 0):
            raise InvalidInputError(
                "limit must be a positive integer.",
                details={"parameter": "limit"},
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
        try:
            parsed = _gas_uri.parse_resource_uri(resource_uri, scheme="gia")
        except _gas_errors.GasError as error:
            raise _translate(error) from error
        resource_type = parsed.resource_type
        if resource_type not in _RESOURCE_TYPES:
            raise InvalidInputError(
                f"Unknown resource type: {resource_type}",
                details={"resource_type": resource_type},
            )
        resource_id = parsed.resource_id
        query_values = parsed.query
        session_id = parsed.session_id
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
