"""Test-only ``GasBackend`` adapters over eval's three GAS-enforced runtimes.

PR 19 (execution plan) asks that "GAS conformance tests are reusable
across the game, project-management, cruise, automotive, and fake
backends." Per an explicit PR 19 Part B scoping decision, this is done
*without* changing eval's own runtime code, response shapes, DB schema, or
evaluation-mode behavior — ``eval/gas_server``, ``eval/cruise_gas_server``,
and ``eval/auto_gas_server`` remain exactly as the harness and historical
result data expect.

These adapters exist purely so ``tests/test_gas_conformance.py`` can drive
``EvalRuntime``/``CruiseGasRuntime``/``AutoGasRuntime`` (in gas-enforced
mode, via their shared ``eval.gas_server.contracts.EnforcedGasMixin``)
through the exact same ``gas_protocol.service.GasService`` used for the
fake backend and the Havoc/GIA backend — proving the protocol-level
invariants hold generically, not just for the two backends that were
already written against ``gas_protocol`` directly. Nothing in ``eval/``
imports this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from gas_protocol.backend import BackendMutation, BackendView
from gas_protocol.contracts import Command, EffectMetadata, Event
from gas_protocol.errors import (
    GasError,
    InvalidInputError,
    ResourceNotFoundError,
    StaleStateError,
)

from eval.gas_server.contracts import GasErrorResponse

# eval's own contract error vocabulary (eval/gas_server/contracts.py's
# GasContractError.code strings) translated onto gas_protocol's stable
# vocabulary, the same style of explicit boundary translation
# gia_gas_adapter.adapter.GiaGasAdapter._ERROR_MAP applies for GIA.
# "action_unavailable"/"invalid_parameters"/"domain_error" all collapse to
# InvalidInputError for the same reason UnavailableActionError does there:
# none of them describe a revision that merely needs a refresh-and-retry.
_ERROR_MAP: dict[str, type[GasError]] = {
    "invalid_input": InvalidInputError,
    "resource_not_found": ResourceNotFoundError,
    "stale_state": StaleStateError,
    "action_unavailable": InvalidInputError,
    "invalid_parameters": InvalidInputError,
    "domain_error": InvalidInputError,
}


def _raise_for_error(response: GasErrorResponse) -> None:
    error_cls = _ERROR_MAP.get(response.error.code, GasError)
    raise error_cls(response.error.message, details=response.error.details)


class _EvalEnforcedGasBackend:
    """Generic ``GasBackend`` translation over an ``EnforcedGasMixin`` runtime.

    Deliberately known-incomplete: eval's ``act_enforced`` has no
    ``idempotency_key`` parameter at all, so retrying the same mutation
    with the same key re-executes it rather than replaying the cached
    result — a real, pre-existing gap relative to the full ``GasBackend``
    contract, not something this test-only shim can paper over without
    changing eval's enforcement behavior (out of scope for this PR; see
    ``tests/test_gas_conformance.py``'s ``supports_idempotent_retry`` flag).
    """

    policy_version = "eval-conformance-v1"

    def __init__(
        self,
        runtime: Any,
        *,
        default_user: str,
        seed: Callable[[Any, str], None] | None = None,
    ):
        self.runtime = runtime
        self._default_user = default_user
        self._seed = seed

    # -- GasBackend ----------------------------------------------------

    def create_session(self) -> BackendView:
        session_id = self.runtime.create_session(acting_user_id=self._default_user)
        if self._seed is not None:
            self._seed(self.runtime.ctx, session_id)
        return self.read("session", session_id, session_id)

    def read(self, resource_type: str, resource_id: str, session_id: str) -> BackendView:
        response = self.runtime.get_enforced(resource_type, resource_id, session_id=session_id)
        return self._to_view(response, session_id)

    def search(self, resource_type: str, query: Mapping[str, Any], session_id: str) -> BackendView:
        response = self.runtime.search_enforced(resource_type, dict(query), session_id=session_id)
        return self._to_view(response, session_id)

    def act(
        self,
        capability_id: str,
        expected_revision: int,
        input: Mapping[str, Any],
        idempotency_key: str,
        *,
        session_id: str,
        scope: str | None,
        request_id: str | None,
        client_metadata: Mapping[str, Any] | None,
        model_metadata: Mapping[str, Any] | None,
        untrusted_rationale: str | None,
        sensitive_fields: tuple[str, ...],
    ) -> BackendMutation:
        action = capability_id.split("::", 1)[0]
        response = self.runtime.act_enforced(
            action,
            dict(input),
            session_id=session_id,
            expected_revision=expected_revision,
        )
        return self._to_mutation(response, session_id)

    def why_not(
        self,
        resource_type: str,
        resource_id: str,
        session_id: str,
        command: str,
        input: Mapping[str, Any] | None,
    ) -> BackendView:
        affordances = self.runtime._contract_affordances(session_id)
        available = any(affordance.action == command for affordance in affordances)
        revision = self.runtime._contract_revision(session_id)
        return BackendView(
            data={"command": command, "available": available},
            commands=[],
            links=[],
            subject="eval",
            scope=f"session:{session_id}",
            state_revision=revision,
            policy_version=self.policy_version,
        )

    # -- internals -------------------------------------------------------

    def _to_view(self, response, session_id: str) -> BackendView:
        if isinstance(response, GasErrorResponse):
            _raise_for_error(response)
        return BackendView(
            data=response.data,
            commands=self._translate_commands(response),
            links=[],
            subject="eval",
            scope=f"session:{session_id}",
            state_revision=response.state_revision,
            policy_version=self.policy_version,
        )

    def _to_mutation(self, response, session_id: str) -> BackendMutation:
        if isinstance(response, GasErrorResponse):
            _raise_for_error(response)
        events = [
            Event(type=str(raw.get("event_type") or raw.get("type") or "event"), data=raw)
            for raw in response.events
        ]
        return BackendMutation(
            data=response.data,
            commands=self._translate_commands(response),
            links=[],
            subject="eval",
            scope=f"session:{session_id}",
            state_revision=response.state_revision,
            policy_version=self.policy_version,
            events=events,
        )

    def _translate_commands(self, response) -> list[Command]:
        # response.affordances is already a list[GasContractAffordance],
        # normalized by eval.gas_server.contracts.contract_affordances() —
        # its .schema_ is already a full JSON Schema object
        # (properties/required/additionalProperties), matching what
        # GiaGasAdapter/gia_core emit, not eval's internal flat
        # {name: spec} shorthand.
        return [
            Command(
                # Prefix the action name onto eval's own opaque contract-hash
                # id so act() below can recover which action to dispatch
                # without a second lookup table — the same
                # "::"-delimited-token trick fake_backend.py uses, since
                # eval's id (a content hash) doesn't embed it on its own.
                id=f"{affordance.action}::{affordance.id}",
                command=affordance.action,
                target=None,
                title=affordance.description,
                input_schema=affordance.schema_,
                effects=EffectMetadata(mutating=True, idempotent=False, destructive=False),
                valid_at_revision=response.state_revision,
                policy_version=self.policy_version,
                constraints=affordance.constraints,
            )
            for affordance in response.affordances
        ]


def _seed_one_pm_project(ctx: Any, session_id: str) -> None:
    ctx.create_project_from_template(session_id, "proj-alpha")


def _seed_one_cruise(ctx: Any, session_id: str) -> None:
    ctx.create_cruise_from_template(session_id, "cruise-med")


def make_eval_pm_backend() -> _EvalEnforcedGasBackend:
    from eval.gas_server.server import EvalRuntime

    return _EvalEnforcedGasBackend(
        EvalRuntime(mode="gas-enforced"),
        default_user="user-mgr-1",
        seed=_seed_one_pm_project,
    )


def make_eval_cruise_backend() -> _EvalEnforcedGasBackend:
    from eval.cruise_gas_server.server import CruiseGasRuntime

    return _EvalEnforcedGasBackend(
        CruiseGasRuntime(mode="gas-enforced"),
        default_user="user-agent-1",
        seed=_seed_one_cruise,
    )


def make_eval_auto_backend() -> _EvalEnforcedGasBackend:
    from eval.auto_gas_server.server import AutoGasRuntime

    return _EvalEnforcedGasBackend(
        AutoGasRuntime(mode="gas-enforced"),
        default_user="user-sales-1",
        seed=None,
    )
