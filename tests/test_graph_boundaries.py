"""PR11 graph/read-model and authoritative-store boundary tests."""

from __future__ import annotations

import pytest
import pyoxigraph as ox

from havoc_domain.graph import ETR, GameGraph
from havoc_server.runtime import GameRuntime


def test_graph_layers_and_structural_profile_are_explicit():
    runtime = GameRuntime()
    try:
        assert runtime.ctx.graph.loaded_layers == frozenset({"vocabulary", "knowledge"})
        assert runtime.ctx.graph.schema_version == "2.0"
        assert runtime.ctx.graph.validate_shacl().conforms

        session_id = runtime.create_session().data["id"]
        runtime.act(
            "select_character",
            {"template_id": "iryna"},
            session_id=session_id,
            expected_revision=0,
        )
        runtime.ctx.project_pending_graph()
        assert runtime.ctx.graph.loaded_layers == frozenset(
            {"vocabulary", "knowledge", "derived"}
        )
        assert runtime.ctx.graph.validate_shacl().conforms
    finally:
        runtime.ctx.db.close()


def test_rebuild_from_authoritative_sqlite_records_preserves_queries():
    runtime = GameRuntime()
    try:
        session_id = runtime.create_session().data["id"]
        runtime.act(
            "select_character",
            {"template_id": "iryna"},
            session_id=session_id,
            expected_revision=0,
        )
        assert len(runtime.ctx.db.get_pending_projection_events()) == 1
        runtime.ctx.project_pending_graph()

        query = """
            SELECT ?action ?before ?after WHERE {
                ?id etr:rdf_type etr:DecisionProvenance .
                ?id etr:actionTaken ?action .
                ?id etr:stateRevisionBefore ?before .
                ?id etr:stateRevisionAfter ?after .
            }
        """
        projected = runtime.ctx.graph.query(query)
        runtime.ctx.graph.clear_derived()
        assert runtime.ctx.graph.query(query) == []

        rebuilt = runtime.ctx.rebuild_graph()
        assert rebuilt.query(query) == projected
        assert rebuilt.validate_shacl().conforms
    finally:
        runtime.ctx.db.close()


def test_graph_failure_does_not_partially_commit_authoritative_mutation():
    runtime = GameRuntime()
    try:
        session_id = runtime.create_session().data["id"]

        def unavailable(_decisions):
            raise RuntimeError("graph unavailable")

        runtime.ctx.graph.load_decisions = unavailable
        result = runtime.act(
            "select_character",
            {"template_id": "iryna"},
            session_id=session_id,
            expected_revision=0,
        )

        assert result.data["message"] == "Iryna joins the mission!"
        assert runtime.ctx.get_session(session_id).state_revision == 1
        pending = runtime.ctx.db.get_pending_projection_events()
        assert len(pending) == 1
        assert pending[0]["event_type"] == "decision.provenance.recorded"
    finally:
        runtime.ctx.db.close()


def test_shacl_profile_reports_malformed_projection_without_authorizing_anything():
    graph = GameGraph()
    subject = ox.NamedNode(f"{ETR}decision_malformed")
    graph.store.add(
        ox.Quad(
            subject,
            ox.NamedNode(f"{ETR}rdf_type"),
            ox.NamedNode(f"{ETR}DecisionProvenance"),
        )
    )

    report = graph.validate_shacl()
    assert report.conforms is False
    assert any("sessionId" in violation for violation in report.violations)
    with pytest.raises(ValueError, match="Graph shape validation failed"):
        report.raise_if_invalid()
