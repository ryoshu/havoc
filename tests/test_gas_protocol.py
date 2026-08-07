"""PR 15: the domain-independent `gas_protocol` package.

Exercises `InMemoryGasBackend` (a deterministic, non-Havoc "notes" domain)
through `GasService`, proving the `GasBackend` seam works end-to-end
without GIA, and proves the package itself never imports GIA/MCP — the
literal claim behind PR 15's exit criteria ("GAS can be
installed/imported and tested without GIA").
"""

from __future__ import annotations

import base64
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gas_protocol import GasBackend, GasService, InMemoryGasBackend
from gas_protocol.errors import ConflictError, InvalidInputError, StaleStateError, StaleViewError

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_gas_protocol_imports_nothing_forbidden():
    """Importing gas_protocol must never pull in gia, gia_core, or mcp."""
    probe = (
        "import sys\n"
        "import gas_protocol\n"
        "forbidden_prefixes = ('gia', 'gia_core', 'src.gia', 'src.gia_core', 'mcp')\n"
        "hits = sorted(\n"
        "    name for name in sys.modules\n"
        "    if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden_prefixes)\n"
        ")\n"
        "print(','.join(hits))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    hits = [name for name in result.stdout.strip().split(",") if name]
    assert hits == [], f"gas_protocol pulled in forbidden modules: {hits}"


def test_protocol_conformance():
    assert isinstance(InMemoryGasBackend(), GasBackend)


@pytest.fixture
def service():
    return GasService(InMemoryGasBackend())


@pytest.fixture
def session(service):
    created = service.create_session()
    return service, created.data["id"], created.state_revision


def _create_note_id(response):
    return next(command.id for command in response.commands if command.command == "create_note")


def test_create_session_returns_create_note_command(service):
    created = service.create_session()
    assert created.data["id"]
    assert [command.command for command in created.commands] == ["create_note"]
    assert created.subject == "system"
    assert created.scope.endswith(f"session:{created.data['id']}")
    assert created.state_revision == 0
    assert created.complete is True


def test_act_create_note_then_get_note(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    result = service.act(
        _create_note_id(created),
        revision,
        {"title": "hello", "body": "world"},
        "idem-1",
        session_id=session_id,
    )
    assert len(result.events) == 1
    assert result.events[0].type == "note_created"
    note_id = result.events[0].data["id"]

    fetched = service.get(f"gas://note/{note_id}?session_id={session_id}")
    assert fetched.data == {"id": note_id, "title": "hello", "body": "world"}
    assert [command.command for command in fetched.commands] == ["update_note"]


def test_act_is_idempotent_on_retry(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    capability_id = _create_note_id(created)
    first = service.act(
        capability_id, revision, {"title": "hello", "body": "world"}, "idem-1", session_id=session_id
    )
    second = service.act(
        capability_id, revision, {"title": "hello", "body": "world"}, "idem-1", session_id=session_id
    )
    assert first.state_revision == second.state_revision == 1
    assert first.data == second.data


def test_act_rejects_stale_revision(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    with pytest.raises(StaleStateError):
        service.act(
            _create_note_id(created),
            revision + 1,
            {"title": "hello", "body": "world"},
            "idem-1",
            session_id=session_id,
        )


def test_search_notes_paginates_with_cursor_continuation(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    capability_id = _create_note_id(created)
    for index in range(3):
        acted = service.act(
            capability_id, revision, {"title": f"note-{index}", "body": "b"}, f"idem-{index}", session_id=session_id
        )
        revision = acted.state_revision
        capability_id = _create_note_id(acted)

    first_page = service.search("notes", {}, limit=2, session_id=session_id)
    assert len(first_page.data) == 2
    assert first_page.complete is False
    assert first_page.next_cursor is not None

    second_page = service.search("notes", {}, cursor=first_page.next_cursor, limit=2, session_id=session_id)
    assert len(second_page.data) == 1
    assert second_page.complete is True
    assert second_page.next_cursor is None

    seen_ids = {item["id"] for item in first_page.data} | {item["id"] for item in second_page.data}
    assert len(seen_ids) == 3


def test_get_command_page_emits_binding_templates_only_when_truncated(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    capability_id = _create_note_id(created)
    for index in range(2):
        acted = service.act(
            capability_id, revision, {"title": f"note-{index}", "body": "b"}, f"idem-{index}", session_id=session_id
        )
        revision = acted.state_revision
        capability_id = _create_note_id(acted)

    small_page_service = GasService(service.backend, max_commands=1)
    truncated = small_page_service.get(f"gas://session/{session_id}")
    assert truncated.next_cursor is not None
    assert truncated.binding_templates, "a truncated page should emit binding templates for repeated commands"

    full_page = service.get(f"gas://session/{session_id}")
    assert full_page.next_cursor is None
    assert full_page.binding_templates == []


def test_cursor_rejects_mismatched_view(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    other_session = service.create_session().data["id"]
    with pytest.raises(InvalidInputError):
        service.get(f"gas://session/{other_session}", cursor=created.next_cursor or "not-a-real-cursor")


def test_cursor_rejects_stale_state(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    # Two notes so a session read has 3 commands (create_note + 2 update_note)
    # — enough for a max_commands=1 page to have a next_cursor to go stale.
    capability_id = _create_note_id(created)
    for index in range(2):
        acted = service.act(
            capability_id, revision, {"title": f"note-{index}", "body": "b"}, f"idem-{index}", session_id=session_id
        )
        revision = acted.state_revision
        capability_id = _create_note_id(acted)

    small_page_service = GasService(service.backend, max_commands=1)
    first_page = small_page_service.get(f"gas://session/{session_id}")
    assert first_page.next_cursor is not None

    service.act(capability_id, revision, {"title": "x", "body": "y"}, "idem-2", session_id=session_id)

    with pytest.raises(StaleViewError):
        small_page_service.get(f"gas://session/{session_id}", cursor=first_page.next_cursor)


def test_search_cursor_offset_out_of_range_is_rejected(session):
    service, session_id, revision = session
    bogus_cursor_payload = {
        "version": 1,
        "kind": "search",
        "resource_type": "notes",
        "resource_id": "",
        "session_id": session_id,
        "scope": f"session:{session_id}",
        "state_revision": revision,
        "policy_version": "policy-v1",
        "query": "{}",
        "data_offset": 999,
        "command_offset": 0,
    }
    raw = json.dumps(bogus_cursor_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bogus_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(InvalidInputError):
        service.search("notes", {}, cursor=bogus_cursor, session_id=session_id)


def test_why_not_reports_unavailable_command(session):
    service, session_id, revision = session
    response = service.why_not(f"gas://session/{session_id}", "delete_everything")
    assert response.data["available"] is False
    assert response.commands == []


def test_act_rejects_idempotency_key_reused_for_a_different_request(session):
    service, session_id, revision = session
    created = service.get(f"gas://session/{session_id}")
    capability_id = _create_note_id(created)
    service.act(capability_id, revision, {"title": "first", "body": "b"}, "idem-1", session_id=session_id)
    with pytest.raises(ConflictError):
        service.act(capability_id, revision, {"title": "different", "body": "b"}, "idem-1", session_id=session_id)


def test_act_rejects_a_capability_id_not_currently_offered(session):
    service, session_id, revision = session
    with pytest.raises(InvalidInputError):
        service.act(
            "cmd::create_note::none::" + session_id + "::999",
            revision,
            {"title": "x", "body": "y"},
            "idem-1",
            session_id=session_id,
        )


def test_get_rejects_negative_cursor_offset(session):
    service, session_id, revision = session
    bogus_payload = {
        "version": 1,
        "kind": "capabilities",
        "resource_type": "session",
        "resource_id": session_id,
        "session_id": session_id,
        "scope": f"session:{session_id}",
        "state_revision": revision,
        "policy_version": "policy-v1",
        "query": "{}",
        "data_offset": 0,
        "command_offset": -1,
    }
    raw = json.dumps(bogus_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bogus_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(InvalidInputError):
        service.get(f"gas://session/{session_id}", cursor=bogus_cursor)


def test_cursor_rejects_non_integer_offset(session):
    service, session_id, revision = session
    bogus_payload = {
        "version": 1,
        "kind": "capabilities",
        "resource_type": "session",
        "resource_id": session_id,
        "session_id": session_id,
        "scope": f"session:{session_id}",
        "state_revision": revision,
        "policy_version": "policy-v1",
        "query": "{}",
        "data_offset": "0",
        "command_offset": 0,
    }
    raw = json.dumps(bogus_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bogus_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(InvalidInputError):
        service.get(f"gas://session/{session_id}", cursor=bogus_cursor)


class _TwoCommandCreateSessionBackend(InMemoryGasBackend):
    """A stub whose freshly created session already offers 2+ commands.

    `InMemoryGasBackend.create_session` always starts a session with just
    `create_note`, so it can never itself exercise a truncated first page —
    this subclass adds a second command up front, purely to reproduce and
    guard the `_overflow_cursor` continuation-identity bug (a truncated
    `create_session` page must still resolve on the next `get`).
    """

    def create_session(self):
        view = super().create_session()
        session_id = view.data["id"]
        return dataclasses.replace(
            view, commands=[*view.commands, self._create_note_command(session_id)]
        )


def test_create_session_overflow_cursor_continues_on_the_right_session():
    """Regression test: a truncated create_session page's cursor used to
    encode a blank resource_id/session_id, so continuing via
    `get(gas://session/{id}, cursor=...)` always failed view-matching with
    InvalidInputError ("Cursor does not match the requested view.") — the
    remaining commands could never actually be recovered."""
    service = GasService(_TwoCommandCreateSessionBackend(), max_commands=1)
    created = service.create_session()
    session_id = created.data["id"]
    assert created.next_cursor is not None

    # Must not raise — a mismatched cursor would raise InvalidInputError here.
    service.get(f"gas://session/{session_id}", cursor=created.next_cursor)
