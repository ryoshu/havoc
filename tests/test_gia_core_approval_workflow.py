"""Tests for the approval-workflow second domain (PR 18 of the GIA/GAS 2.0
plan).

`ApprovalWorkflowApplication` (`gia_core.approval_workflow`) is a small,
deterministic, Havoc-free domain implementing `gia_core.ports
.ResourceProvider`/`CapabilityAuthority` directly. Its own job is proving
PR 18's exit criterion "a non-game domain uses GIA without importing
Havoc" — so, mirroring `test_application_boundary.py`'s own import
discipline, this file imports nothing from `src.gia`/`gia`/`havoc_domain`/
`mcp` at all, only `gia_core.*`.
"""

from __future__ import annotations

import pytest

from gia_core.approval_workflow import ApprovalWorkflowApplication
from gia_core.errors import (
    InvalidParameterError,
    ResourceNotFoundError,
    StaleStateError,
    UnavailableActionError,
    UnsupportedOperationError,
)
from gia_core.ports import CapabilityAuthority, ResourceProvider
from gia_core.requests import (
    DiagnoseRequest,
    ExecuteRequest,
    GetRequest,
    ProjectRequest,
    SearchRequest,
)


@pytest.fixture
def app():
    return ApprovalWorkflowApplication()


def test_implements_both_gia_ports(app):
    assert isinstance(app, ResourceProvider)
    assert isinstance(app, CapabilityAuthority)


def test_new_session_only_offers_submit(app):
    result = app.create_session()
    assert [a.action for a in result.affordances] == ["submit_request"]
    assert result.state_revision == 0


def test_submit_project_approve_cycle(app):
    sid = app.create_session().data["id"]

    submitted = app.execute(
        ExecuteRequest(
            session_id=sid, action="submit_request",
            params={"title": "Buy a printer"}, expected_revision=0,
        )
    )
    assert submitted.state_revision == 1
    assert [e.type for e in submitted.events] == ["RequestSubmitted"]
    request_id = submitted.events[0].data["id"]
    assert {a.action for a in submitted.affordances} == {
        "submit_request", "approve_request", "reject_request",
    }

    capability_set = app.project(ProjectRequest(session_id=sid))
    assert capability_set.state_revision == 1
    assert {c.command for c in capability_set.commands} == {
        "submit_request", "approve_request", "reject_request",
    }
    # Capability IDs are content-addressed and opaque, not sequential.
    assert all(c.id.startswith("cap-") for c in capability_set.commands)

    approved = app.execute(
        ExecuteRequest(
            session_id=sid, action="approve_request",
            params={"request_id": request_id}, expected_revision=1,
        )
    )
    assert approved.state_revision == 2
    assert approved.events[0].type == "RequestApproved"
    assert [a.action for a in approved.affordances] == ["submit_request"]

    fetched = app.get(GetRequest(resource_type="request", id=request_id, session_id=sid))
    assert fetched.data == {"id": request_id, "title": "Buy a printer", "status": "approved", "reason": None}

    searched = app.search(SearchRequest(resource_type="requests", session_id=sid))
    assert searched.data == [fetched.data]


def test_reject_records_reason(app):
    sid = app.create_session().data["id"]
    submitted = app.execute(
        ExecuteRequest(session_id=sid, action="submit_request", params={"title": "x"}, expected_revision=0)
    )
    request_id = submitted.events[0].data["id"]

    rejected = app.execute(
        ExecuteRequest(
            session_id=sid, action="reject_request",
            params={"request_id": request_id, "reason": "too expensive"}, expected_revision=1,
        )
    )
    assert rejected.events[0].data == {"id": request_id, "reason": "too expensive"}

    filtered = app.search(
        SearchRequest(resource_type="requests", session_id=sid, filters={"status": "rejected"})
    )
    assert len(filtered.data) == 1
    assert filtered.data[0]["reason"] == "too expensive"


def test_search_filters_by_status(app):
    sid = app.create_session().data["id"]
    app.execute(ExecuteRequest(session_id=sid, action="submit_request", params={"title": "a"}, expected_revision=0))
    app.execute(ExecuteRequest(session_id=sid, action="submit_request", params={"title": "b"}, expected_revision=1))

    pending = app.search(SearchRequest(resource_type="requests", session_id=sid, filters={"status": "pending"}))
    assert len(pending.data) == 2


def test_approving_an_already_decided_request_is_rejected(app):
    sid = app.create_session().data["id"]
    submitted = app.execute(
        ExecuteRequest(session_id=sid, action="submit_request", params={"title": "x"}, expected_revision=0)
    )
    request_id = submitted.events[0].data["id"]
    app.execute(
        ExecuteRequest(session_id=sid, action="approve_request", params={"request_id": request_id}, expected_revision=1)
    )
    with pytest.raises(UnavailableActionError):
        app.execute(
            ExecuteRequest(
                session_id=sid, action="approve_request",
                params={"request_id": request_id}, expected_revision=2,
            )
        )


def test_stale_revision_is_rejected_without_mutating_state(app):
    sid = app.create_session().data["id"]
    app.execute(ExecuteRequest(session_id=sid, action="submit_request", params={"title": "a"}, expected_revision=0))

    with pytest.raises(StaleStateError):
        app.execute(
            ExecuteRequest(session_id=sid, action="submit_request", params={"title": "b"}, expected_revision=0)
        )

    # The rejected attempt must not have partially applied.
    assert len(app.search(SearchRequest(resource_type="requests", session_id=sid)).data) == 1


def test_missing_required_parameter_is_rejected(app):
    sid = app.create_session().data["id"]
    with pytest.raises(InvalidParameterError):
        app.execute(ExecuteRequest(session_id=sid, action="submit_request", params={}, expected_revision=0))


def test_unknown_resource_type_is_rejected(app):
    sid = app.create_session().data["id"]
    with pytest.raises(UnsupportedOperationError):
        app.get(GetRequest(resource_type="nope", session_id=sid))
    with pytest.raises(UnsupportedOperationError):
        app.search(SearchRequest(resource_type="nope", session_id=sid))


def test_unknown_session_is_not_found(app):
    with pytest.raises(ResourceNotFoundError):
        app.get(GetRequest(resource_type="session", id="does-not-exist"))


def test_diagnose_reports_unavailable_and_available_commands(app):
    sid = app.create_session().data["id"]

    unavailable = app.diagnose(DiagnoseRequest(session_id=sid, command="approve_request"))
    assert unavailable.available is False
    assert unavailable.reasons[0]["code"] == "prerequisite_unsatisfied"

    available = app.diagnose(DiagnoseRequest(session_id=sid, command="submit_request"))
    assert available.available is True
    assert available.reasons == []
