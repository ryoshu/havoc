"""PR 13 golden fixtures (docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md).

Freezes representative GIA `CapabilitySet` and GAS `get`/`search`/`act`/
`why_not` payloads, plus the stale-revision, stale-cursor, unavailable/
unknown-capability, scope, policy-version, and idempotent-retry cases named
in that plan's PR 13 work items — so PR 15 (gas-protocol extraction) and
PR 16 (the GIA-GAS adapter) have a frozen baseline to diff their new output
against for parity, per those PRs' own exit criteria.

IDs are opaque and regenerated every run (session/character ids are
``uuid4().hex``-based, capability ids hash the session's scope — see
``src/havoc_domain/db.py:_uid`` and ``src/gia/capabilities/ids.py``), so this file
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

from havoc_domain.execution import execute
from havoc_domain.kernel import project_capability_set
from gas_protocol.errors import (
    InvalidInputError as GasInvalidInputError,
    StaleStateError as GasStaleStateError,
    StaleViewError as GasStaleViewError,
)
from gia_core.errors import PolicyChangedError, ScopeMismatchError
from gia.server import GameRuntime, build_gas_service

from .helpers import (
    FIXTURES_DIR,
    _assert_matches_fixture,
    _command,
    _error_payload,
    normalize,
    tenant_runtime,
)


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
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.get(f"gia://session/{session_id}")
        _assert_matches_fixture("gas_get_session", response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_gas_search_locations_golden_fixture():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        response = gas.search("locations", {"sector": 3}, session_id=session_id)
        _assert_matches_fixture("gas_search_locations", response.model_dump(mode="json"))
    finally:
        runtime.ctx.db.close()


def test_gas_act_golden_fixture():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
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
    gas = build_gas_service(runtime)
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
    gas = build_gas_service(runtime)
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
        except GasStaleStateError as error:
            _assert_matches_fixture("error_stale_revision", _error_payload(error))
    finally:
        runtime.ctx.db.close()


def test_stale_cursor_golden_fixture():
    runtime = GameRuntime()
    gas = build_gas_service(runtime, max_page_size=1)
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
        except GasStaleViewError as error:
            _assert_matches_fixture("error_stale_cursor", _error_payload(error))
    finally:
        runtime.ctx.db.close()


# ---------------------------------------------------------------------------
# Unavailable and unknown capability — ADR-0002: both are indistinguishable
# by design, so both scenarios freeze to the same error shape.
# ---------------------------------------------------------------------------


def test_unknown_capability_golden_fixture():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
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
        except GasInvalidInputError as error:
            _assert_matches_fixture("error_unknown_capability", _error_payload(error))
    finally:
        runtime.ctx.db.close()


def test_unavailable_capability_golden_fixture():
    """A capability that *was* valid, replayed after the state that
    projected it has moved on — resolves to the same error shape as an
    unknown id (see module note above)."""
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
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
        except GasInvalidInputError as error:
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


def test_scope_mismatch_golden_fixture(tmp_path):
    runtime_a, context_a = tenant_runtime(tmp_path, "actor-a", "tenant-a")
    runtime_b, context_b = tenant_runtime(tmp_path, "actor-b", "tenant-b")
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
    `src/havoc_domain/execution.py::_execute_locked`)."""
    runtime, context = tenant_runtime(tmp_path, "actor", "tenant-a")
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
    """Exercises the public `GasService.act(capability_id=...)` path — the
    one an actual GAS client uses. This used to raise
    `IdempotencyConflictError` on replay instead of returning the cached
    result: the cache comparison ran against the caller's un-resolved
    action ("" for a capability-id request) while the cache was written
    with the post-resolution action name. Fixed in
    `src/havoc_domain/execution.py` by comparing/storing on
    `capability_id or action` (a stable identity available before
    resolution) instead of the resolved action name. Also asserts the
    replay records no second decision and performs no second mutation —
    the property the bug would otherwise have silently violated.
    """
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
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
