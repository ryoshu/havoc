"""PR 13 golden fixtures (docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md).

Freezes representative GIA `CapabilitySet` and GAS `get`/`search`/`act`/
`why_not` payloads, plus the stale-revision, stale-cursor, unavailable/
unknown-capability, scope, policy-version, and idempotent-retry cases named
in that plan's PR 13 work items — so PR 15 (gas-protocol extraction) and
PR 16 (the GIA-GAS adapter) have a frozen baseline to diff their new output
against for parity, per those PRs' own exit criteria.

IDs are opaque and regenerated every run (session/character ids are
``uuid4().hex``-based, capability ids hash the session's scope — see
``src/gia/db.py:_uid`` and ``src/gia/capabilities/ids.py``), so this file
compares *normalized* payloads: every id-shaped token is replaced with a
stable placeholder in first-seen order before comparing against the
committed fixture in ``tests/fixtures/gia_gas_pr13/``. That freezes
response *shape* (keys, error codes, structural relationships) rather than
literal random values.

To regenerate the committed fixtures after an intentional contract change:

    GIA_UPDATE_FIXTURES=1 uv run pytest tests/test_pr13_golden_fixtures.py -v

Review the resulting diff like any other characterization-test update.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.gia.commands.execution import execute
from src.gia.commands.kernel import project_capability_set
from src.gia.domain import (
    PolicyChangedError,
    ScopeMismatchError,
    StaleStateError,
    StaleViewError,
    UnavailableActionError,
)
from src.gia.gas import GasRuntime
from src.gia.policy import Actor, RequestContext
from src.gia.server import GameRuntime

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "gia_gas_pr13"

_ID_PATTERN = re.compile(r"\b(?:gs|ch|sc|dr|dc|req|outbox|cap)-[0-9a-f]{6,}\b")
_OPAQUE_KEYS = {"created_at", "timestamp", "next_cursor", "cursor"}


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


_ORDER_INDEPENDENT_KEYS = {"commands", "binding_templates"}


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
        "see this file's module docstring to regenerate after an intentional change."
    )


def _error_payload(error: Exception) -> dict[str, Any]:
    return {"error_code": error.code, "message": str(error), "details": error.details}


def _command(response, name: str, **constants):
    candidates = [command for command in response.commands if command.command == name]
    for command in candidates:
        properties = command.input_schema.get("properties", {})
        if all(properties.get(key, {}).get("const") == value for key, value in constants.items()):
            return command
    raise AssertionError(f"No {name} capability matches {constants!r}")


# ---------------------------------------------------------------------------
# GIA: CapabilitySet
# ---------------------------------------------------------------------------


def test_capability_set_golden_fixture():
    runtime = GameRuntime()
    try:
        session_id = runtime.create_session().data["id"]
        session = runtime.ctx.get_session(session_id)
        capability_set = project_capability_set(runtime.ctx, session, runtime.request_context)
        _assert_matches_fixture("capability_set", capability_set.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


# ---------------------------------------------------------------------------
# GAS: get / search / act / why_not
# ---------------------------------------------------------------------------


def test_gas_get_session_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.get(f"gia://session/{session_id}")
        _assert_matches_fixture("gas_get_session", response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_gas_search_locations_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.search("locations", {"sector": 3}, session_id=session_id)
        _assert_matches_fixture("gas_search_locations", response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_gas_act_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        state = gas.get(f"gia://session/{session_id}")
        capability = _command(state, "select_character", template_id="iryna")

        response = gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr13-fixture-select-character",
            session_id=session_id,
        )
        _assert_matches_fixture("gas_act_select_character", response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_gas_why_not_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.why_not(f"gia://session/{session_id}", "start_mission")
        _assert_matches_fixture("gas_why_not_start_mission", response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


# ---------------------------------------------------------------------------
# Stale revision / stale cursor
# ---------------------------------------------------------------------------


def test_stale_revision_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        state = gas.get(f"gia://session/{session_id}")
        capability = _command(state, "select_character", template_id="iryna")

        try:
            gas.act(
                capability.id,
                state.state_revision + 1,
                {"template_id": "iryna"},
                "pr13-fixture-stale-revision",
                session_id=session_id,
            )
            raise AssertionError("expected StaleStateError")
        except StaleStateError as error:
            _assert_matches_fixture("error_stale_revision", _error_payload(error))
    finally:
        runtime.ctx.db.close()


def test_stale_cursor_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime, max_page_size=1)
    try:
        session_id = gas.create_session().data["id"]
        first = gas.search("locations", limit=1, session_id=session_id)
        state = gas.get(f"gia://session/{session_id}")
        capability = _command(state, "select_character", template_id="iryna")
        gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr13-fixture-stale-cursor",
            session_id=session_id,
        )

        try:
            gas.search("locations", cursor=first.next_cursor, limit=1, session_id=session_id)
            raise AssertionError("expected StaleViewError")
        except StaleViewError as error:
            _assert_matches_fixture("error_stale_cursor", _error_payload(error))
    finally:
        runtime.ctx.db.close()


# ---------------------------------------------------------------------------
# Unavailable and unknown capability — ADR-0002: both are indistinguishable
# by design, so both scenarios freeze to the same error shape.
# ---------------------------------------------------------------------------


def test_unknown_capability_golden_fixture():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        state = gas.get(f"gia://session/{session_id}")

        try:
            gas.act(
                "cap-0000000000000000deadbeef",
                state.state_revision,
                {},
                "pr13-fixture-unknown-capability",
                session_id=session_id,
            )
            raise AssertionError("expected UnavailableActionError")
        except UnavailableActionError as error:
            _assert_matches_fixture("error_unknown_capability", _error_payload(error))
    finally:
        runtime.ctx.db.close()


def test_unavailable_capability_golden_fixture():
    """A capability that *was* valid, replayed after the state that
    projected it has moved on — resolves to the same error shape as an
    unknown id (see module note above)."""
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        state = gas.get(f"gia://session/{session_id}")
        capability = _command(state, "select_character", template_id="iryna")
        gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr13-fixture-advance-state",
            session_id=session_id,
        )

        try:
            gas.act(
                capability.id,
                state.state_revision,
                {"template_id": "iryna"},
                "pr13-fixture-unavailable-capability",
                session_id=session_id,
            )
            raise AssertionError("expected UnavailableActionError")
        except UnavailableActionError as error:
            _assert_matches_fixture("error_unavailable_capability", _error_payload(error))
    finally:
        runtime.ctx.db.close()


def test_unknown_and_unavailable_capability_errors_are_indistinguishable():
    unknown = json.loads((FIXTURES_DIR / "error_unknown_capability.json").read_text())
    unavailable = json.loads((FIXTURES_DIR / "error_unavailable_capability.json").read_text())
    assert unknown == unavailable, (
        "ADR-0002: capability references must not reveal whether a stale "
        "id was ever valid — the two failure fixtures must serialize "
        "identically."
    )


# ---------------------------------------------------------------------------
# Scope and policy-version failures
# ---------------------------------------------------------------------------


def _tenant_runtime(tmp_path, subject: str, tenant: str) -> tuple[GameRuntime, RequestContext]:
    context = RequestContext(Actor(subject), tenant)
    return GameRuntime(str(tmp_path / "state.db"), request_context=context), context


def test_scope_mismatch_golden_fixture(tmp_path):
    runtime_a, context_a = _tenant_runtime(tmp_path, "actor-a", "tenant-a")
    runtime_b, context_b = _tenant_runtime(tmp_path, "actor-b", "tenant-b")
    try:
        session_id = runtime_a.create_session().data["id"]
        capability = project_capability_set(
            runtime_a.ctx, runtime_a.ctx.get_session(session_id), context_a
        ).commands[0]

        try:
            execute(
                runtime_b.ctx,
                session_id,
                "",
                {"template_id": "iryna"},
                0,
                request_context=context_b,
                capability_id=capability.id,
            )
            raise AssertionError("expected ScopeMismatchError")
        except ScopeMismatchError as error:
            _assert_matches_fixture("error_scope_mismatch", _error_payload(error))
    finally:
        runtime_a.ctx.db.close()
        runtime_b.ctx.db.close()


def test_policy_changed_golden_fixture(tmp_path):
    """`policy_version` is the caller's *expected* current policy version —
    passing a value that disagrees with the live one raises
    PolicyChangedError before any resolution or mutation runs (see
    `src/gia/commands/execution.py::_execute_locked`)."""
    runtime, context = _tenant_runtime(tmp_path, "actor", "tenant-a")
    try:
        session_id = runtime.create_session().data["id"]

        try:
            execute(
                runtime.ctx,
                session_id,
                "select_character",
                {"template_id": "iryna"},
                0,
                request_context=context,
                policy_version="policy-v0-obsolete",
            )
            raise AssertionError("expected PolicyChangedError")
        except PolicyChangedError as error:
            _assert_matches_fixture("error_policy_changed", _error_payload(error))
    finally:
        runtime.ctx.db.close()


# ---------------------------------------------------------------------------
# Idempotent retry
# ---------------------------------------------------------------------------


def test_idempotent_retry_golden_fixture():
    """Exercises the public `GasRuntime.act(capability_id=...)` path — the
    one an actual GAS client uses. This used to raise
    `IdempotencyConflictError` on replay instead of returning the cached
    result: the cache comparison ran against the caller's un-resolved
    action ("" for a capability-id request) while the cache was written
    with the post-resolution action name. Fixed in
    `src/gia/commands/execution.py` by comparing/storing on
    `capability_id or action` (a stable identity available before
    resolution) instead of the resolved action name. Also asserts the
    replay records no second decision and performs no second mutation —
    the property the bug would otherwise have silently violated.
    """
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        session_id = gas.create_session().data["id"]
        state = gas.get(f"gia://session/{session_id}")
        capability = _command(state, "select_character", template_id="iryna")

        first = gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr13-fixture-idempotent-retry",
            session_id=session_id,
        )
        decisions_after_first = len(runtime.ctx.db.get_session_decisions(session_id))
        characters_after_first = len(runtime.ctx.db.get_session_characters(session_id))

        replay = gas.act(
            capability.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr13-fixture-idempotent-retry",
            session_id=session_id,
        )

        assert normalize(first.model_dump(mode="json")) == normalize(replay.model_dump(mode="json"))
        assert len(runtime.ctx.db.get_session_decisions(session_id)) == decisions_after_first, (
            "replay must not record a second decision"
        )
        assert len(runtime.ctx.db.get_session_characters(session_id)) == characters_after_first, (
            "replay must not perform a second mutation"
        )
        _assert_matches_fixture("gas_act_idempotent_retry", replay.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_idempotency_identity_prefers_capability_id_over_resolved_action_name():
    """Regression test for the bug fixed above, isolated from the GAS
    response wrapper: two `execute()` calls through the same capability_id
    and the same (now-stale) expected_revision must both succeed, the
    second by replay rather than by re-executing."""
    runtime = GameRuntime()
    try:
        session_id = runtime.create_session().data["id"]
        session = runtime.ctx.get_session(session_id)
        capability = project_capability_set(
            runtime.ctx, session, runtime.request_context
        ).commands[0]
        assert capability.command == "select_character"

        first_data, first_events = execute(
            runtime.ctx,
            session_id,
            "",
            {"template_id": "iryna"},
            0,
            request_context=runtime.request_context,
            capability_id=capability.id,
            idempotency_key="identity-regression",
        )
        replay_data, replay_events = execute(
            runtime.ctx,
            session_id,
            "",
            {"template_id": "iryna"},
            0,
            request_context=runtime.request_context,
            capability_id=capability.id,
            idempotency_key="identity-regression",
        )

        assert replay_data == first_data
        assert [e.model_dump(mode="json") for e in replay_events] == [
            e.model_dump(mode="json") for e in first_events
        ]
        assert len(runtime.ctx.db.get_session_characters(session_id)) == 1
    finally:
        runtime.ctx.db.close()
