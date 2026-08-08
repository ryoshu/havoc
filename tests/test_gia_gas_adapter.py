"""PR 16: the explicit GIA-GAS adapter (`GiaGasAdapter`).

`GiaGasAdapter` is a fresh `gas_protocol.backend.GasBackend` implementation
over `gia_core.ports.{ResourceProvider,CapabilityAuthority}`, meant to be
driven by `gas_protocol.service.GasService`. These tests prove it reaches
the same reference monitor a native GIA caller would (cross-renderer) and
that a rejected action leaves state untouched (negative coverage) — two of
the three test categories PR 16's own Work list names. The third (golden
parity against the deprecated `src.gia.gas.GasRuntime`) doesn't apply
anymore: PR 19 removed `GasRuntime` once every first-party caller had
migrated to this adapter, and the parity it proved is now frozen instead
in `tests/test_pr13_golden_fixtures.py`'s committed fixtures.
"""

from __future__ import annotations

import pytest

from gas_protocol.backend import GasBackend
from gas_protocol.errors import (
    GasError,
    InvalidInputError as GasInvalidInputError,
    StaleStateError as GasStaleStateError,
)
from gia_core.capabilities import CapabilitySet
from gia_core.policy import PolicyProvider, RequestContext, Scope
from gia_core.requests import (
    DiagnoseRequest,
    DiagnoseResult,
    ExecuteRequest,
    ExecuteResult,
    GetRequest,
    GetResult,
    ProjectRequest,
    SearchRequest,
    SearchResult,
)

from havoc_server.runtime import GameRuntime, build_gas_service
from gia_gas_adapter import GiaGasAdapter

from .helpers import _command, normalize


@pytest.fixture
def adapted():
    runtime = GameRuntime()
    service = build_gas_service(runtime)
    try:
        yield runtime, service
    finally:
        runtime.ctx.db.close()


def test_protocol_conformance(adapted):
    runtime, service = adapted
    assert isinstance(service.backend, GasBackend)


# ---------------------------------------------------------------------------
# Cross-renderer: GAS-surfaced commands are the same tokens the reference
# monitor (CapabilityAuthority.execute) accepts natively.
# ---------------------------------------------------------------------------


def test_gas_rendered_command_id_executes_through_the_native_reference_monitor(adapted):
    runtime, service = adapted
    session_id = service.create_session().data["id"]
    state = service.get(f"gia://session/{session_id}")
    command = _command(state, "select_character", template_id="iryna")

    # Bypass the adapter entirely: call the same CapabilityAuthority the
    # adapter itself calls, directly, exactly as the native MCP renderer
    # would. If GAS's rendered command.id were not a real, currently-valid
    # capability reference, this would raise.
    result = runtime._application.execute(
        ExecuteRequest(
            session_id=session_id,
            action="",
            params={"template_id": "iryna"},
            expected_revision=state.state_revision,
            idempotency_key="pr16-cross-renderer",
            request_context=runtime.request_context,
            capability_id=command.id,
        )
    )
    assert result.data["character_id"].startswith("ch-")
    assert result.state_revision == 1


# ---------------------------------------------------------------------------
# Negative: the adapter cannot add, authorize, or execute an unprojected
# command; a rejected action leaves state/revision/events unchanged.
# ---------------------------------------------------------------------------


def test_forged_capability_id_is_rejected_and_state_is_unchanged(adapted):
    runtime, service = adapted
    session_id = service.create_session().data["id"]
    session_before = runtime.ctx.get_session(session_id)
    decisions_before = len(runtime.ctx.db.get_session_decisions(session_id))

    with pytest.raises(GasError):
        service.act(
            "cap-0000000000000000deadbeef",
            0,
            {},
            "pr16-forged-capability",
            session_id=session_id,
        )

    session_after = runtime.ctx.get_session(session_id)
    assert session_after.state_revision == session_before.state_revision
    assert len(runtime.ctx.db.get_session_decisions(session_id)) == decisions_before


def test_stale_expected_revision_is_rejected_as_stale_state_and_state_is_unchanged(adapted):
    runtime, service = adapted
    session_id = service.create_session().data["id"]
    state = service.get(f"gia://session/{session_id}")
    command = _command(state, "select_character", template_id="iryna")
    session_before = runtime.ctx.get_session(session_id)

    with pytest.raises(GasStaleStateError):
        service.act(
            command.id,
            state.state_revision + 1,
            {"template_id": "iryna"},
            "pr16-stale-revision",
            session_id=session_id,
        )

    session_after = runtime.ctx.get_session(session_id)
    assert session_after.state_revision == session_before.state_revision


def test_replayed_capability_after_state_advances_is_rejected(adapted):
    """A capability that *was* valid, replayed after the state it was
    projected against has moved on, must be rejected — the adapter cannot
    let a stale reference authorize a second mutation."""
    runtime, service = adapted
    session_id = service.create_session().data["id"]
    state = service.get(f"gia://session/{session_id}")
    command = _command(state, "select_character", template_id="iryna")

    service.act(
        command.id, state.state_revision, {"template_id": "iryna"}, "pr16-advance-state", session_id=session_id,
    )
    session_before = runtime.ctx.get_session(session_id)

    with pytest.raises(GasInvalidInputError):
        service.act(
            command.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr16-replay-after-advance",
            session_id=session_id,
        )

    session_after = runtime.ctx.get_session(session_id)
    assert session_after.state_revision == session_before.state_revision


def test_scope_outside_authenticated_tenant_is_rejected(adapted):
    runtime, service = adapted
    session_id = service.create_session().data["id"]
    state = service.get(f"gia://session/{session_id}")
    command = _command(state, "select_character", template_id="iryna")

    with pytest.raises(GasInvalidInputError):
        service.act(
            command.id,
            state.state_revision,
            {"template_id": "iryna"},
            "pr16-foreign-scope",
            session_id=session_id,
            scope="tenant:someone-else/session:not-this-session",
        )


# ---------------------------------------------------------------------------
# Regression: request-context forwarding, scope-correct projection, and
# mixed-session rejection — verified against fake ports that record exactly
# what the adapter sent them, since HavocGiaApplication's own leniency
# (filter keys it doesn't recognize are simply ignored; a missing
# request_context silently falls back to a default actor) would otherwise
# mask these bugs.
# ---------------------------------------------------------------------------


class _FakePolicyProvider:
    @property
    def version(self) -> str:
        return "v1"

    def allows(self, **kwargs) -> bool:
        return True


class _RecordingPorts:
    """Minimal ResourceProvider + CapabilityAuthority + SessionFactory fake."""

    def __init__(self) -> None:
        self.get_requests: list[GetRequest] = []
        self.search_requests: list[SearchRequest] = []
        self.project_requests: list[ProjectRequest] = []

    def get(self, request: GetRequest) -> GetResult:
        self.get_requests.append(request)
        return GetResult(data={"id": request.id}, state_revision=1)

    def search(self, request: SearchRequest) -> SearchResult:
        self.search_requests.append(request)
        return SearchResult(data=[], state_revision=1)

    def project(self, request: ProjectRequest) -> CapabilitySet:
        self.project_requests.append(request)
        scope = request.scope or Scope.session("default", request.session_id)
        return CapabilitySet(subject="system", scope=scope.key, state_revision=1, policy_version="v1")

    def execute(self, request: ExecuteRequest) -> ExecuteResult:  # pragma: no cover - unused here
        raise NotImplementedError

    def diagnose(self, request: DiagnoseRequest) -> DiagnoseResult:
        return DiagnoseResult(available=False, reasons=[], details=[])

    def create_session(self) -> GetResult:
        return GetResult(data={"id": "sess-1"}, state_revision=0)


def _fake_adapter(ports: _RecordingPorts) -> GiaGasAdapter:
    return GiaGasAdapter(
        ports, ports, ports,
        policy_provider=_FakePolicyProvider(),
        request_context=RequestContext.system(),
    )


def test_read_forwards_the_authenticated_context():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    adapter.read("character", "ch-1", "sess-1")

    assert ports.get_requests[-1].request_context is adapter.request_context


def test_search_forwards_the_authenticated_context():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    adapter.search("locations", {}, "sess-1")

    assert ports.search_requests[-1].request_context is adapter.request_context


def test_search_strips_reserved_session_id_from_filters_even_with_a_positional_session_id():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    adapter.search("locations", {"session_id": "bogus", "sector": 3}, "sess-1")

    sent = ports.search_requests[-1]
    assert sent.session_id == "sess-1"
    assert sent.filters == {"sector": 3}


def test_read_projects_capabilities_at_the_resource_scope():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    adapter.read("character", "ch-1", "sess-1")

    resource_scope = Scope.resource("default", "character", "ch-1")
    assert ports.project_requests[-1].scope == resource_scope


def test_search_projects_capabilities_at_the_collection_scope():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    adapter.search("locations", {}, "sess-1")

    assert ports.project_requests[-1].scope == Scope.collection("default", "locations")


def test_read_rejects_a_session_id_that_disagrees_with_the_session_resource_uri():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    with pytest.raises(GasInvalidInputError):
        adapter.read("session", "sess-A", "sess-B")


def test_read_canonicalizes_an_omitted_session_id_to_the_session_resource_uri():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    adapter.read("session", "sess-A", "")

    assert ports.project_requests[-1].session_id == "sess-A"


def test_why_not_rejects_a_session_id_that_disagrees_with_the_session_resource_uri():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    with pytest.raises(GasInvalidInputError):
        adapter.why_not("session", "sess-A", "sess-B", "start_mission", None)


def test_read_rejects_a_session_uri_with_no_path_id_even_with_a_query_session_id():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    with pytest.raises(GasInvalidInputError):
        adapter.read("session", "", "sess-B")


def test_why_not_rejects_a_session_uri_with_no_path_id_even_with_a_query_session_id():
    ports = _RecordingPorts()
    adapter = _fake_adapter(ports)

    with pytest.raises(GasInvalidInputError):
        adapter.why_not("session", "", "sess-B", "start_mission", None)
