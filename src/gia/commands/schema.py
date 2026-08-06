"""Generic JSON-schema machinery for the command-policy kernel (PR 4).

Moved here from ``src/gia/affordances.py`` (now a deprecated re-export
shim — see that module's docstring). This is transport/domain-independent
plumbing shared by every command's projection and validation, not policy
itself, so it belongs in the kernel package rather than duplicated per
command or left behind in the module PR 4 empties out.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..models import Affordance

JSON_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
OPTIONAL_PARAMETERS = {"equipment_names", "ability_name", "bonus_dice"}


def _normalize_property(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(spec)
    if normalized.get("type") == "object":
        properties = normalized.get("properties", {})
        normalized["properties"] = {
            name: _normalize_property(value)
            for name, value in properties.items()
        }
        normalized["required"] = normalized.get("required", [])
        normalized["additionalProperties"] = False
    return normalized


def normalize_schema(raw_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert binding/affordance field fragments into closed JSON Schema objects."""
    if "properties" in raw_schema and raw_schema.get("type") == "object":
        properties = raw_schema["properties"]
    else:
        properties = raw_schema
    normalized_properties = {
        name: _normalize_property(spec)
        for name, spec in properties.items()
    }
    return {
        "$schema": JSON_SCHEMA_URI,
        "type": "object",
        "properties": normalized_properties,
        "required": [
            name
            for name, spec in normalized_properties.items()
            if "default" not in spec and name not in OPTIONAL_PARAMETERS
        ],
        "additionalProperties": False,
    }


def finalize_affordances(affordances: list[Affordance]) -> list[Affordance]:
    """Attach deterministic IDs and complete schemas to generated affordances."""
    finalized = []
    occurrences: dict[str, int] = {}
    for affordance in affordances:
        schema = normalize_schema(affordance.schema_)
        identity = json.dumps(
            {
                "action": affordance.action,
                "schema": schema,
                "constraints": affordance.constraints,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        affordance_id = f"aff-{hashlib.sha256(f'{identity}:{occurrence}'.encode()).hexdigest()[:16]}"
        finalized.append(
            affordance.model_copy(update={"id": affordance_id, "schema_": schema})
        )
    return finalized


def _validate_value(name: str, value: Any, schema: dict[str, Any], errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{name} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{name} must be one of {schema['enum']!r}")

    schema_type = schema.get("type")
    type_matches = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
    }
    if schema_type in type_matches and not type_matches[schema_type](value):
        errors.append(f"{name} must be a {schema_type}")
        return
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{name} must be >= {schema['minimum']}")
    if schema_type == "array":
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_value(f"{name}[{index}]", item, item_schema, errors)
    if schema_type == "object":
        properties = schema.get("properties", {})
        missing = [key for key in schema.get("required", []) if key not in value]
        errors.extend(f"{name}.{key} is required" for key in missing)
        extras = [key for key in value if key not in properties]
        errors.extend(f"{name}.{key} is not allowed" for key in extras)
        for key, item in value.items():
            if key in properties:
                _validate_value(f"{name}.{key}", item, properties[key], errors)


def schema_errors(schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Return schema violations of `params` against a normalized JSON Schema object."""
    errors: list[str] = []
    _validate_value("params", params, schema, errors)
    return errors


def validate_parameters(affordance: Affordance, params: dict[str, Any]) -> list[str]:
    """Return schema violations for one affordance invocation."""
    return schema_errors(affordance.schema_, params)
