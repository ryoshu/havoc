"""RS-10: a GAS conformance suite reusable across backends.

The execution plan's PR 19 exit criteria (docs/GIA-GAS-SEPARATION-EXECUTION-
PLAN.md) names this explicitly: "GAS conformance tests are reusable across
the game, project-management, cruise, automotive, and fake backends." Every
test below runs against a plain ``gas_protocol.service.GasService`` wrapping
one of five ``GasBackend`` implementations:

- ``InMemoryGasBackend`` — the domain-independent fake backend (PR 15).
- Havoc/``GiaGasAdapter`` — the real game backend (PR 16), built the same
  way ``havoc_server.runtime.build_gas_service`` does.
- Eval's PM, cruise, and automotive runtimes, in gas-enforced mode, through
  the test-only translation shims in ``tests/gas_conformance/eval_adapters.py``
  (per an explicit PR 19 Part B scoping decision, eval's own runtime code,
  response shapes, and DB schema are untouched by this suite).

Per-backend specifics (which action to exercise, what its non-const inputs
look like, which collection to search) are unavoidably domain knowledge —
there is no way to pick "a mutating command" or "a searchable collection"
without knowing the domain — so each backend contributes one
``ConformanceCase`` naming them explicitly; the generic case model and
service-driving helpers are published by ``gas_protocol.conformance`` so a
downstream repository can run the same checks without importing this test
tree. Everything else the tests do is generic across all five.
"""

from __future__ import annotations

import pytest

from gas_protocol import GasService
from gas_protocol.backend import GasBackend
from gas_protocol.conformance import ConformanceCase, GasConformanceHarness
from gas_protocol.errors import InvalidInputError, ResourceNotFoundError, StaleStateError
from gas_protocol.fake_backend import InMemoryGasBackend

from .gas_conformance.eval_adapters import (
    make_eval_auto_backend,
    make_eval_cruise_backend,
    make_eval_pm_backend,
)


def _make_havoc_backend() -> GasBackend:
    from havoc_server.runtime import GameRuntime
    from gia_gas_adapter import GiaGasAdapter

    runtime = GameRuntime()
    return GiaGasAdapter(
        runtime._application,
        runtime._application,
        runtime._application,
        policy_provider=runtime.ctx.policy_provider,
        request_context=runtime.request_context,
    )


CASES: list[ConformanceCase] = [
    ConformanceCase(
        label="fake",
        make_backend=InMemoryGasBackend,
        mutating_action="create_note",
        extra_input={"title": "conformance", "body": "b"},
        search_resource_type="notes",
        supports_idempotent_retry=True,
    ),
    ConformanceCase(
        label="havoc",
        make_backend=_make_havoc_backend,
        mutating_action="select_character",
        extra_input={},
        search_resource_type="locations",
        supports_idempotent_retry=True,
    ),
    ConformanceCase(
        label="eval-pm",
        make_backend=make_eval_pm_backend,
        mutating_action="create_issue",
        extra_input={"title": "conformance issue", "description": "seeded by the conformance suite", "priority": "p3"},
        search_resource_type="issues",
        supports_idempotent_retry=False,
    ),
    ConformanceCase(
        label="eval-cruise",
        make_backend=make_eval_cruise_backend,
        mutating_action="create_booking",
        extra_input={"description": "seeded by the conformance suite"},
        search_resource_type="bookings",
        supports_idempotent_retry=False,
    ),
    ConformanceCase(
        label="eval-auto",
        make_backend=make_eval_auto_backend,
        mutating_action="create_customer",
        extra_input={
            "name": "Conformance Customer",
            "email": "conformance@example.com",
            "phone": "555-0100",
            "drivers_license": "D1234567",
        },
        search_resource_type="customers",
        supports_idempotent_retry=False,
    ),
]

CASE_IDS = [case.label for case in CASES]


@pytest.fixture(params=CASES, ids=CASE_IDS)
def case(request) -> ConformanceCase:
    return request.param


@pytest.fixture
def harness(case: ConformanceCase) -> GasConformanceHarness:
    return GasConformanceHarness(case)


@pytest.fixture
def service(harness: GasConformanceHarness) -> GasService:
    return harness.make_service()


def test_backend_conforms_to_the_gas_backend_protocol(harness: GasConformanceHarness):
    assert isinstance(harness.make_backend(), GasBackend)


def test_create_session_returns_a_well_formed_view(service: GasService):
    created = service.create_session()
    assert isinstance(created.data, dict)
    assert created.data["id"]
    assert created.state_revision == 0
    assert created.subject
    assert created.scope
    assert created.policy_version
    assert created.complete is True


def test_read_of_an_unknown_session_is_rejected(service: GasService):
    with pytest.raises(ResourceNotFoundError):
        service.get("gas://session/does-not-exist")


def test_search_returns_a_view_without_erroring(case: ConformanceCase, service: GasService):
    if case.search_resource_type is None:
        pytest.skip(f"{case.label} has no declared searchable resource type")
    created = service.create_session()
    session_id = created.data["id"]
    result = service.search(case.search_resource_type, {}, session_id=session_id)
    assert isinstance(result.data, list)


def test_act_happy_path_commits_and_advances_revision(
    harness: GasConformanceHarness, service: GasService
):
    created = service.create_session()
    session_id = created.data["id"]
    command = harness.find_command(created.commands)

    result = harness.act(
        service, session_id, created.state_revision, command, "conformance-act"
    )

    assert result.state_revision == created.state_revision + 1


def test_act_rejects_a_stale_expected_revision(
    harness: GasConformanceHarness, service: GasService
):
    created = service.create_session()
    session_id = created.data["id"]
    command = harness.find_command(created.commands)

    with pytest.raises(StaleStateError):
        harness.act(
            service,
            session_id,
            created.state_revision + 1,
            command,
            "conformance-stale",
        )


def test_act_on_an_unknown_session_is_rejected_as_resource_not_found(case: ConformanceCase, service: GasService):
    """Regression test: a first version of the eval GasBackend adapters
    checked capability_id offer-status before session existence, so acting
    on a nonexistent session reported invalid_input ("capability_id is not
    currently offered") instead of resource_not_found — because computing
    the currently-offered set for an unknown session quietly returns an
    empty set rather than raising anything itself. The fake and Havoc
    backends both already get this right; every backend must."""
    with pytest.raises(ResourceNotFoundError):
        service.act(
            "not-a-real-capability-id",
            0,
            {},
            "conformance-unknown-session",
            session_id="does-not-exist",
        )


def test_act_rejects_a_capability_id_that_is_not_currently_offered(case: ConformanceCase, service: GasService):
    created = service.create_session()
    session_id = created.data["id"]

    with pytest.raises(InvalidInputError):
        service.act(
            "not-a-real-capability-id",
            created.state_revision,
            {},
            "conformance-forged",
            session_id=session_id,
        )


def test_act_rejects_a_forged_suffix_on_an_otherwise_valid_action_name(
    harness: GasConformanceHarness, service: GasService
):
    """A capability_id must be validated in full, not just its action-name
    prefix. Regression test: the eval GasBackend adapters mint ids as
    "<action>::<opaque-token>" so act() can recover which action to
    dispatch — but a first version of that adapter recovered the action by
    splitting on "::" and never checked the token against anything, so
    "<valid-action>::forged" executed successfully. Every backend must
    reject this, not just a fully-bogus id with no valid prefix at all
    (covered above)."""
    created = service.create_session()
    session_id = created.data["id"]
    command = harness.find_command(created.commands)
    forged_id = f"{command.command}::forged-suffix-not-a-real-target"

    with pytest.raises(InvalidInputError):
        service.act(
            forged_id,
            created.state_revision,
            harness.mutation_input(command),
            "conformance-forged-suffix",
            session_id=session_id,
        )


def test_why_not_reports_an_unavailable_command(service: GasService):
    created = service.create_session()
    session_id = created.data["id"]
    response = service.why_not(
        f"gas://session/{session_id}", "definitely_not_a_real_command"
    )
    assert response.data["available"] is False
    assert response.commands == []


def test_act_is_idempotent_on_retry(
    harness: GasConformanceHarness, service: GasService
):
    if not harness.case.supports_idempotent_retry:
        pytest.skip(
            f"{harness.case.label}'s enforced-mode contract has no idempotency_key "
            "support (eval.gas_server.contracts.EnforcedGasMixin.act_enforced "
            "does not accept one) — a real, pre-existing gap relative to the "
            "full GasBackend contract, out of scope for PR 19 Part B's "
            "conformance-suite-only pass."
        )
    created = service.create_session()
    session_id = created.data["id"]
    command = harness.find_command(created.commands)

    first = harness.act(
        service, session_id, created.state_revision, command, "conformance-idem"
    )
    second = harness.act(
        service, session_id, created.state_revision, command, "conformance-idem"
    )

    assert first.state_revision == second.state_revision
    assert first.data == second.data
