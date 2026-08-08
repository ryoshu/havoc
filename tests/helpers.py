"""Shared test helpers (PR 14 of the GIA/GAS 2.0 plan).

Hoisted out of ``test_gas_contracts.py``/``test_pr13_golden_fixtures.py``/
``test_actor_scope_policy.py``, which each had their own copy of one or
more of these. Behavior is unchanged from the versions they replace — this
is pure deduplication.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from gia_core.policy import Actor, RequestContext
from havoc_server.runtime import GameRuntime

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "gia_gas_pr13"

_ID_PATTERN = re.compile(r"\b(?:gs|ch|sc|dr|dc|req|outbox|cap|aff)-[0-9a-f]{6,}\b")
_OPAQUE_KEYS = {"created_at", "timestamp", "next_cursor", "cursor"}
_ORDER_INDEPENDENT_KEYS = {"commands", "binding_templates"}


def _command(response, name: str, **constants):
    candidates = [command for command in response.commands if command.command == name]
    for command in candidates:
        properties = command.input_schema.get("properties", {})
        if all(properties.get(key, {}).get("const") == value for key, value in constants.items()):
            return command
    raise AssertionError(f"No {name} capability matches {constants!r}")


def tenant_runtime(
    tmp_path, subject: str, tenant: str = "tenant-a", *, policy=None
) -> tuple[GameRuntime, RequestContext]:
    """A `GameRuntime` bound to one tenant/actor, backed by a shared sqlite
    file at `tmp_path` so multiple tenants can share one physical database
    while staying scope-isolated."""
    context = RequestContext(Actor(subject), tenant)
    return (
        GameRuntime(str(tmp_path / "state.db"), request_context=context, policy_provider=policy),
        context,
    )


def _normalize(value: Any, placeholders: dict[str, str], counters: dict[str, int]) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<OPAQUE>" if key in _OPAQUE_KEYS and val is not None else _normalize(val, placeholders, counters))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item, placeholders, counters) for item in value]
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            token = match.group(0)
            if token not in placeholders:
                prefix = token.split("-", 1)[0]
                counters[prefix] = counters.get(prefix, 0) + 1
                placeholders[token] = f"{prefix}-ID{counters[prefix]}"
            return placeholders[token]

        return _ID_PATTERN.sub(replace, value)
    return value


def _sort_key(item: Any) -> str:
    if isinstance(item, dict):
        item = {key: value for key, value in item.items() if key != "id"}
    return json.dumps(item, sort_keys=True, default=str)


def _canonicalize_order(value: Any) -> Any:
    """Sort `commands`/`binding_templates` lists before id-normalization.

    A `CapabilitySet` is a set (ADR-0003) — its wire order is an
    implementation detail of dict/DB iteration, not part of the contract,
    and varies run to run. Sorting by every field except the (also
    run-varying) id gives a stable order to normalize placeholder ids
    against. `data`/`events`/`links` are left untouched: their order is
    part of what these fixtures characterize.
    """
    if isinstance(value, dict):
        canonicalized = {key: _canonicalize_order(val) for key, val in value.items()}
        for key in _ORDER_INDEPENDENT_KEYS:
            if isinstance(canonicalized.get(key), list):
                canonicalized[key] = sorted(canonicalized[key], key=_sort_key)
        return canonicalized
    if isinstance(value, list):
        return [_canonicalize_order(item) for item in value]
    return value


def normalize(payload: Any) -> Any:
    canonical = _canonicalize_order(payload)
    return _normalize(canonical, placeholders={}, counters={})


def _assert_matches_fixture(name: str, payload: Any) -> None:
    normalized = normalize(payload)
    path = FIXTURES_DIR / f"{name}.json"
    if os.environ.get("GIA_UPDATE_FIXTURES"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    expected = json.loads(path.read_text())
    assert normalized == expected, (
        f"{name} fixture drifted from tests/fixtures/gia_gas_pr13/{name}.json — "
        "see tests/test_pr13_golden_fixtures.py's module docstring to regenerate "
        "after an intentional change."
    )


def _error_payload(error: Exception) -> dict[str, Any]:
    return {"error_code": error.code, "message": str(error), "details": error.details}
