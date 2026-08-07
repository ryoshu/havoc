"""PR9 decision-provenance contract and persistence guarantees."""

from __future__ import annotations

from havoc_domain.graph import GameGraph
from gia_core.provenance import REDACTED, capability_set_digest, redact_sensitive
from gia.server import GameRuntime, build_gas_service


def _select_capability(response, template_id: str):
    return next(
        command
        for command in response.commands
        if command.command == "select_character"
        and command.input_schema["properties"]["template_id"]["const"] == template_id
    )


def test_committed_mutation_has_reconstructable_provenance():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        before = gas.get(f"gia://session/{session_id}")
        capability = _select_capability(before, "iryna")

        gas.act(
            capability.id,
            before.state_revision,
            {"template_id": "iryna"},
            "provenance-select",
            session_id=session_id,
            request_id="req-provenance-select",
            client_metadata={"client": "test", "authorization": "do-not-store"},
            model_metadata={"model": "fixture", "api_token": "do-not-store"},
            untrusted_rationale="supplied by the caller, not a causal proof",
        )

        record = runtime.ctx.db.get_provenance("req-provenance-select")
        assert record is not None
        assert record.version == "2.0"
        assert record.capability_id == capability.id
        assert record.capability_set_hash == capability_set_digest(record.capability_snapshot)
        assert record.capability_snapshot_ref == f"decision:{record.id}:capabilities"
        assert record.state_revision_before == 0
        assert record.state_revision_after == 1
        assert record.outcome == "committed"
        assert record.input == {"template_id": "iryna"}
        assert record.client_metadata["authorization"] == REDACTED
        assert record.model_metadata["api_token"] == REDACTED
        assert record.untrusted_rationale
        raw = runtime.ctx.db.conn.execute(
            "SELECT * FROM decision_records WHERE request_id = ?",
            ("req-provenance-select",),
        ).fetchone()
        assert "do-not-store" not in repr(tuple(raw))
        assert len(runtime.ctx.db.get_session_provenance(session_id)) == 1
    finally:
        runtime.ctx.db.close()


def test_idempotent_retry_writes_provenance_exactly_once():
    runtime = GameRuntime()
    try:
        session_id = runtime.create_session().data["id"]
        runtime.act(
            "select_character",
            {"template_id": "iryna"},
            session_id=session_id,
            expected_revision=0,
            idempotency_key="provenance-retry",
            request_id="req-first-attempt",
        )
        runtime.act(
            "select_character",
            {"template_id": "iryna"},
            session_id=session_id,
            expected_revision=0,
            idempotency_key="provenance-retry",
            request_id="req-retry-attempt",
        )
        records = runtime.ctx.db.get_session_provenance(session_id)
        assert len(records) == 1
        assert records[0].request_id == "req-first-attempt"
    finally:
        runtime.ctx.db.close()


def test_redaction_is_recursive_and_graph_projection_has_no_reasoning_fields():
    payload = {
        "token": "secret",
        "nested": [{"password": "secret", "visible": "ok"}],
        "configured": "sensitive",
    }
    redacted = redact_sensitive(payload, sensitive_fields=("configured",))
    assert redacted == {
        "token": REDACTED,
        "nested": [{"password": REDACTED, "visible": "ok"}],
        "configured": REDACTED,
    }

    runtime = GameRuntime()
    try:
        session_id = runtime.create_session().data["id"]
        runtime.act(
            "select_character",
            {"template_id": "iryna"},
            session_id=session_id,
            expected_revision=0,
        )
        record = runtime.ctx.db.get_session_provenance(session_id)[0]
        graph = GameGraph()
        graph.load_provenance([record])
        assert graph.query(
            "SELECT ?id WHERE { ?id etr:rdf_type etr:DecisionProvenance . }"
        )
        assert not graph.query(
            "SELECT ?id WHERE { ?id etr:llmNarration ?value . }"
        )
    finally:
        runtime.ctx.db.close()
