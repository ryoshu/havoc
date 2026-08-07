"""PR 16: the explicit GIA-GAS adapter (`GiaGasAdapter`).

`GiaGasAdapter` is a fresh `gas_protocol.backend.GasBackend` implementation
over `gia_core.ports.{ResourceProvider,CapabilityAuthority}`, meant to be
driven by `gas_protocol.service.GasService` — not a relocation of the
deprecated, Havoc-`GameRuntime`-coupled `src.gia.gas.GasRuntime`. These
tests hold the new path to the same behavior as the old one (golden
parity), prove the two reach the same reference monitor (cross-renderer),
and prove a rejected action leaves state untouched (negative coverage) —
the three test categories PR 16's own Work list names.
"""

from __future__ import annotations

import pytest

from gas_protocol.backend import GasBackend
from gas_protocol.errors import (
    GasError,
    InvalidInputError as GasInvalidInputError,
    StaleStateError as GasStaleStateError,
)
from gas_protocol.service import GasService
from gia.capabilities import CapabilitySet
from gia.policy import PolicyProvider, RequestContext, Scope
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

from src.gia.gas import GasRuntime
from src.gia.server import GameRuntime
from src.gia_gas_adapter import GiaGasAdapter

from .helpers import _command, normalize


def _new_adapter_service(runtime: GameRuntime) -> GasService:
    adapter = GiaGasAdapter(
        runtime._application,
        runtime._application,
        runtime._application,
        policy_provider=runtime.ctx.policy_provider,
        request_context=runtime.request_context,
    )
    return GasService(adapter, scheme="gia")


@pytest.fixture
def legacy():
    runtime = GameRuntime()
    gas = GasRuntime(runtime)
    try:
        yield runtime, gas
    finally:
        runtime.ctx.db.close()


@pytest.fixture
def adapted():
    runtime = GameRuntime()
    service = _new_adapter_service(runtime)
    try:
        yield runtime, service
    finally:
        runtime.ctx.db.close()


def test_protocol_conformance(adapted):
    runtime, service = adapted
    assert isinstance(service.backend, GasBackend)


# ---------------------------------------------------------------------------
# Golden parity: legacy GasRuntime vs GiaGasAdapter+GasService
# ---------------------------------------------------------------------------


def test_create_session_parity_with_legacy_gas_runtime(legacy, adapted):
    _, legacy_gas = legacy
    _, new_service = adapted

    legacy_response = legacy_gas.create_session()
    new_response = new_service.create_session()

    assert normalize(legacy_response.model_dump(mode="json")) == normalize(
        new_response.model_dump(mode="json")
    )


def test_get_session_parity_with_legacy_gas_runtime(legacy, adapted):
    _, legacy_gas = legacy
    _, new_service = adapted

    legacy_session_id = legacy_gas.create_session().data["id"]
    new_session_id = new_service.create_session().data["id"]

    legacy_response = legacy_gas.get(f"gia://session/{legacy_session_id}")
    new_response = new_service.get(f"gia://session/{new_session_id}")

    assert normalize(legacy_response.model_dump(mode="json")) == normalize(
        new_response.model_dump(mode="json")
    )


def test_search_locations_parity_with_legacy_gas_runtime(legacy, adapted):
    _, legacy_gas = legacy
    _, new_service = adapted

    legacy_session_id = legacy_gas.create_session().data["id"]
    new_session_id = new_service.create_session().data["id"]

    legacy_response = legacy_gas.search("locations", {"sector": 3}, session_id=legacy_session_id)
    new_response = new_service.search("locations", {"sector": 3}, session_id=new_session_id)

    assert normalize(legacy_response.model_dump(mode="json")) == normalize(
        new_response.model_dump(mode="json")
    )


def test_get_character_local_view_parity_with_legacy_gas_runtime(legacy, adapted):
    """Exercises `_localize`'s `force_incomplete` behavior: a resource-local
    view (character/scene) is marked `complete=False` even when its (small)
    command set fits in one page — both paths must agree on that flag, not
    just on the command list."""
    _, legacy_gas = legacy
    _, new_service = adapted

    legacy_session_id = legacy_gas.create_session().data["id"]
    new_session_id = new_service.create_session().data["id"]
    legacy_state = legacy_gas.get(f"gia://session/{legacy_session_id}")
    new_state = new_service.get(f"gia://session/{new_session_id}")
    legacy_capability = _command(legacy_state, "select_character", template_id="iryna")
    new_capability = _command(new_state, "select_character", template_id="iryna")

    legacy_acted = legacy_gas.act(
        legacy_capability.id, legacy_state.state_revision, {"template_id": "iryna"},
        "pr16-local-view", session_id=legacy_session_id,
    )
    new_acted = new_service.act(
        new_capability.id, new_state.state_revision, {"template_id": "iryna"},
        "pr16-local-view", session_id=new_session_id,
    )
    legacy_char_id = legacy_acted.data["character_id"]
    new_char_id = new_acted.data["character_id"]

    legacy_view = legacy_gas.get(f"gia://character/{legacy_char_id}?session_id={legacy_session_id}")
    new_view = new_service.get(f"gia://character/{new_char_id}?session_id={new_session_id}")

    assert legacy_view.complete is False
    assert normalize(legacy_view.model_dump(mode="json")) == normalize(new_view.model_dump(mode="json"))


def test_act_select_character_parity_with_legacy_gas_runtime(legacy, adapted):
    _, legacy_gas = legacy
    _, new_service = adapted

    legacy_session_id = legacy_gas.create_session().data["id"]
    new_session_id = new_service.create_session().data["id"]

    legacy_state = legacy_gas.get(f"gia://session/{legacy_session_id}")
    new_state = new_service.get(f"gia://session/{new_session_id}")
    legacy_capability = _command(legacy_state, "select_character", template_id="iryna")
    new_capability = _command(new_state, "select_character", template_id="iryna")

    legacy_response = legacy_gas.act(
        legacy_capability.id,
        legacy_state.state_revision,
        {"template_id": "iryna"},
        "pr16-parity-select-character",
        session_id=legacy_session_id,
    )
    new_response = new_service.act(
        new_capability.id,
        new_state.state_revision,
        {"template_id": "iryna"},
        "pr16-parity-select-character",
        session_id=new_session_id,
    )

    assert normalize(legacy_response.model_dump(mode="json")) == normalize(
        new_response.model_dump(mode="json")
    )


def test_why_not_parity_with_legacy_gas_runtime(legacy, adapted):
    _, legacy_gas = legacy
    _, new_service = adapted

    legacy_session_id = legacy_gas.create_session().data["id"]
    new_session_id = new_service.create_session().data["id"]

    legacy_response = legacy_gas.why_not(f"gia://session/{legacy_session_id}", "start_mission")
    new_response = new_service.why_not(f"gia://session/{new_session_id}", "start_mission")

    assert normalize(legacy_response.model_dump(mode="json")) == normalize(
        new_response.model_dump(mode="json")
    )


def test_idempotent_retry_parity_with_legacy_gas_runtime(legacy, adapted):
    """Preserve idempotency: the replay response, not just the first, must
    match between paths — and both paths' replay must equal their own
    first response (the actual idempotency guarantee)."""
    legacy_runtime, legacy_gas = legacy
    new_runtime, new_service = adapted

    legacy_session_id = legacy_gas.create_session().data["id"]
    new_session_id = new_service.create_session().data["id"]
    legacy_state = legacy_gas.get(f"gia://session/{legacy_session_id}")
    new_state = new_service.get(f"gia://session/{new_session_id}")
    legacy_capability = _command(legacy_state, "select_character", template_id="iryna")
    new_capability = _command(new_state, "select_character", template_id="iryna")

    legacy_first = legacy_gas.act(
        legacy_capability.id, legacy_state.state_revision, {"template_id": "iryna"},
        "pr16-idempotent-retry", session_id=legacy_session_id,
    )
    new_first = new_service.act(
        new_capability.id, new_state.state_revision, {"template_id": "iryna"},
        "pr16-idempotent-retry", session_id=new_session_id,
    )
    legacy_replay = legacy_gas.act(
        legacy_capability.id, legacy_state.state_revision, {"template_id": "iryna"},
        "pr16-idempotent-retry", session_id=legacy_session_id,
    )
    new_replay = new_service.act(
        new_capability.id, new_state.state_revision, {"template_id": "iryna"},
        "pr16-idempotent-retry", session_id=new_session_id,
    )

    assert normalize(legacy_first.model_dump(mode="json")) == normalize(legacy_replay.model_dump(mode="json"))
    assert normalize(new_first.model_dump(mode="json")) == normalize(new_replay.model_dump(mode="json"))
    assert normalize(legacy_replay.model_dump(mode="json")) == normalize(new_replay.model_dump(mode="json"))
    assert (
        len(new_runtime.ctx.db.get_session_decisions(new_session_id))
        == len(legacy_runtime.ctx.db.get_session_decisions(legacy_session_id))
    )


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
