"""Shared enforced-mode contracts for the GAS evaluation runtimes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field


class GasContractAffordance(BaseModel):
    id: str
    action: str
    description: str
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    constraints: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class GasResourceResponse(BaseModel):
    mode: str
    data: Any
    affordances: list[GasContractAffordance] = Field(default_factory=list)
    state_revision: int


class GasActionResponse(GasResourceResponse):
    events: list[dict[str, Any]] = Field(default_factory=list)


class GasError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class GasErrorResponse(BaseModel):
    mode: str
    error: GasError
    affordances: list[GasContractAffordance] = Field(default_factory=list)
    state_revision: int | None = None


class GasContractError(Exception):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _normalize_schema(raw_schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = raw_schema.get("properties", raw_schema)
    normalized = {
        name: dict(spec) if isinstance(spec, Mapping) else spec
        for name, spec in properties.items()
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": normalized,
        "required": [
            name for name, spec in normalized.items()
            if isinstance(spec, Mapping) and "default" not in spec
        ],
        "additionalProperties": False,
    }


def contract_affordances(affordances: list[Any]) -> list[GasContractAffordance]:
    result: list[GasContractAffordance] = []
    occurrences: dict[str, int] = {}
    for affordance in affordances:
        schema = _normalize_schema(affordance.schema_)
        identity = json.dumps(
            {"action": affordance.action, "schema": schema, "constraints": affordance.constraints},
            sort_keys=True,
            separators=(",", ":"),
        )
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        identifier = hashlib.sha256(f"{identity}:{occurrence}".encode()).hexdigest()[:16]
        result.append(
            GasContractAffordance(
                id=f"aff-{identifier}",
                action=affordance.action,
                description=affordance.description,
                schema=schema,
                constraints=affordance.constraints,
            )
        )
    return result


def _validate_value(name: str, value: Any, schema: Mapping[str, Any], errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{name} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{name} must be one of {schema['enum']!r}")
    schema_type = schema.get("type")
    matches = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
    }
    if schema_type in matches and not matches[schema_type](value):
        errors.append(f"{name} must be a {schema_type}")
        return
    if schema_type == "object":
        properties = schema.get("properties", {})
        errors.extend(
            f"{name}.{key} is required"
            for key in schema.get("required", [])
            if key not in value
        )
        errors.extend(
            f"{name}.{key} is not allowed"
            for key in value
            if key not in properties
        )
        for key, item in value.items():
            if key in properties and isinstance(properties[key], Mapping):
                _validate_value(f"{name}.{key}", item, properties[key], errors)


def validate_contract(affordance: GasContractAffordance, params: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _validate_value("params", params, affordance.schema_, errors)
    return errors


def error_response(mode: str, error: GasContractError, affordances: list[Any], revision: int | None):
    return GasErrorResponse(
        mode=mode,
        error=GasError(code=error.code, message=str(error), details=error.details),
        affordances=contract_affordances(affordances),
        state_revision=revision,
    )


class EnforcedGasMixin:
    """Typed, affordance-enforced facade shared by the three GAS runtimes."""

    def _contract_affordances(self, session_id: str) -> list[Any]:
        raise NotImplementedError

    def _contract_revision(self, session_id: str) -> int:
        revisions = getattr(self, "_contract_revisions", None)
        if revisions is None:
            revisions = self._contract_revisions = {}
        return revisions.get(session_id, 0)

    def _contract_error(self, error: GasContractError, session_id: str):
        return error_response(
            self.mode,
            error,
            self._contract_affordances(session_id) if session_id else [],
            self._contract_revision(session_id) if session_id else None,
        )

    def _require_contract_session(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise GasContractError("invalid_input", "session_id is required in gas-enforced mode.", details={"parameter": "session_id"})
        if not self.ctx.get_session(session_id):
            raise GasContractError("resource_not_found", f"Session '{session_id}' not found.")

    def get_enforced(self, resource_type: str, id: str = "", *, session_id: str) -> GasResourceResponse | GasErrorResponse:
        try:
            self._require_contract_session(session_id)
            payload = json.loads(self.get(resource_type, id, session_id))
            if "error" in payload:
                raise GasContractError("resource_not_found", payload["error"])
            return GasResourceResponse(
                mode=self.mode,
                data=payload.get("data"),
                affordances=contract_affordances(self._contract_affordances(session_id)),
                state_revision=self._contract_revision(session_id),
            )
        except GasContractError as error:
            return self._contract_error(error, session_id)

    def search_enforced(self, resource_type: str, filters: Mapping[str, Any] | None = None, *, session_id: str) -> GasResourceResponse | GasErrorResponse:
        try:
            self._require_contract_session(session_id)
            payload = json.loads(self.search(resource_type, json.dumps(dict(filters or {})), session_id))
            if "error" in payload:
                raise GasContractError("invalid_input", payload["error"])
            return GasResourceResponse(
                mode=self.mode,
                data=payload.get("data"),
                affordances=contract_affordances(self._contract_affordances(session_id)),
                state_revision=self._contract_revision(session_id),
            )
        except GasContractError as error:
            return self._contract_error(error, session_id)

    def act_enforced(
        self,
        action: str,
        params: Mapping[str, Any] | None = None,
        *,
        session_id: str,
        expected_revision: int | None,
    ) -> GasActionResponse | GasErrorResponse:
        try:
            self._require_contract_session(session_id)
            if expected_revision is None:
                raise GasContractError("invalid_input", "expected_revision is required in gas-enforced mode.")
            current_revision = self._contract_revision(session_id)
            if expected_revision != current_revision:
                raise GasContractError(
                    "stale_state",
                    f"Session revision is {current_revision}, not {expected_revision}.",
                    details={"expected_revision": expected_revision, "current_revision": current_revision},
                )
            parsed = dict(params or {})
            candidates = [a for a in contract_affordances(self._contract_affordances(session_id)) if a.action == action]
            if not candidates:
                raise GasContractError("action_unavailable", f"Action '{action}' is not currently available.")
            errors = [validate_contract(candidate, parsed) for candidate in candidates]
            if not any(not item for item in errors):
                best = min(errors, key=len)
                raise GasContractError("invalid_parameters", "; ".join(best))

            payload = json.loads(self.act(action, json.dumps(parsed), session_id))
            if "error" in payload:
                raise GasContractError("domain_error", payload["error"])
            revision = current_revision + 1
            self._contract_revisions[session_id] = revision
            return GasActionResponse(
                mode=self.mode,
                data=payload.get("data"),
                affordances=contract_affordances(self._contract_affordances(session_id)),
                state_revision=revision,
                events=payload.get("events", []),
            )
        except GasContractError as error:
            return self._contract_error(error, session_id)
