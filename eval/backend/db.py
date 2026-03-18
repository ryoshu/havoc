"""SQLite layer — mutable eval state persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .models import (
    CommentState,
    DecisionRecord,
    EvalSession,
    IssueState,
    IssueStatus,
    Priority,
    ProjectState,
    ProjectStatus,
    SprintState,
    SprintStatus,
)

SCHEMA = """\
CREATE TABLE IF NOT EXISTS eval_sessions (
    id TEXT PRIMARY KEY,
    acting_user_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES eval_sessions(id),
    template_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'setup',
    owner_id TEXT NOT NULL DEFAULT '',
    member_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sprints (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES eval_sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planning',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES eval_sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'p3',
    assignee_id TEXT NOT NULL DEFAULT '',
    reporter_id TEXT NOT NULL DEFAULT '',
    sprint_id TEXT NOT NULL DEFAULT '',
    labels_json TEXT NOT NULL DEFAULT '[]',
    linked_issue_ids_json TEXT NOT NULL DEFAULT '[]',
    is_locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES eval_sessions(id),
    issue_id TEXT NOT NULL REFERENCES issues(id),
    author_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES eval_sessions(id),
    actor_id TEXT NOT NULL DEFAULT '',
    actor_name TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    affordances_snapshot_json TEXT NOT NULL DEFAULT '[]',
    affordances_not_taken_json TEXT NOT NULL DEFAULT '[]',
    result_summary TEXT NOT NULL DEFAULT '',
    events_json TEXT NOT NULL DEFAULT '[]',
    was_valid INTEGER NOT NULL DEFAULT 1,
    error_message TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
"""


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


class EvalDB:
    """SQLite persistence for mutable eval state."""

    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # --- Sessions ---

    def create_session(self, acting_user_id: str = "") -> EvalSession:
        sid = _uid("es-")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO eval_sessions (id, acting_user_id, created_at) VALUES (?, ?, ?)",
            (sid, acting_user_id, now),
        )
        self.conn.commit()
        return EvalSession(id=sid, acting_user_id=acting_user_id, created_at=now)

    def get_session(self, session_id: str) -> EvalSession | None:
        row = self.conn.execute(
            "SELECT * FROM eval_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return EvalSession(
            id=row["id"],
            acting_user_id=row["acting_user_id"],
            created_at=row["created_at"],
        )

    def update_session(self, session: EvalSession) -> None:
        self.conn.execute(
            "UPDATE eval_sessions SET acting_user_id=? WHERE id=?",
            (session.acting_user_id, session.id),
        )
        self.conn.commit()

    # --- Projects ---

    def create_project(self, project: ProjectState) -> ProjectState:
        if not project.id:
            project.id = _uid("proj-")
        if not project.created_at:
            project.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO projects
               (id, session_id, template_id, name, description, status, owner_id,
                member_ids_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project.id, project.session_id, project.template_id,
                project.name, project.description, project.status.value,
                project.owner_id, json.dumps(project.member_ids),
                project.created_at,
            ),
        )
        self.conn.commit()
        return project

    def get_project(self, project_id: str) -> ProjectState | None:
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_project(row)

    def get_session_projects(self, session_id: str) -> list[ProjectState]:
        rows = self.conn.execute(
            "SELECT * FROM projects WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def update_project(self, project: ProjectState) -> None:
        self.conn.execute(
            """UPDATE projects
               SET name=?, description=?, status=?, owner_id=?,
                   member_ids_json=?
               WHERE id=?""",
            (
                project.name, project.description, project.status.value,
                project.owner_id, json.dumps(project.member_ids),
                project.id,
            ),
        )
        self.conn.commit()

    def _row_to_project(self, row: sqlite3.Row) -> ProjectState:
        return ProjectState(
            id=row["id"],
            session_id=row["session_id"],
            template_id=row["template_id"],
            name=row["name"],
            description=row["description"],
            status=ProjectStatus(row["status"]),
            owner_id=row["owner_id"],
            member_ids=json.loads(row["member_ids_json"]),
            created_at=row["created_at"],
        )

    # --- Sprints ---

    def create_sprint(self, sprint: SprintState) -> SprintState:
        if not sprint.id:
            sprint.id = _uid("sp-")
        if not sprint.created_at:
            sprint.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO sprints (id, session_id, project_id, name, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                sprint.id, sprint.session_id, sprint.project_id,
                sprint.name, sprint.status.value, sprint.created_at,
            ),
        )
        self.conn.commit()
        return sprint

    def get_sprint(self, sprint_id: str) -> SprintState | None:
        row = self.conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_sprint(row)

    def get_project_sprints(self, project_id: str) -> list[SprintState]:
        rows = self.conn.execute(
            "SELECT * FROM sprints WHERE project_id = ?", (project_id,)
        ).fetchall()
        return [self._row_to_sprint(r) for r in rows]

    def get_session_sprints(self, session_id: str) -> list[SprintState]:
        rows = self.conn.execute(
            "SELECT * FROM sprints WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_sprint(r) for r in rows]

    def update_sprint(self, sprint: SprintState) -> None:
        self.conn.execute(
            "UPDATE sprints SET name=?, status=? WHERE id=?",
            (sprint.name, sprint.status.value, sprint.id),
        )
        self.conn.commit()

    def _row_to_sprint(self, row: sqlite3.Row) -> SprintState:
        return SprintState(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            name=row["name"],
            status=SprintStatus(row["status"]),
            created_at=row["created_at"],
        )

    # --- Issues ---

    def create_issue(self, issue: IssueState) -> IssueState:
        if not issue.id:
            issue.id = _uid("iss-")
        now = datetime.now(timezone.utc).isoformat()
        if not issue.created_at:
            issue.created_at = now
        if not issue.updated_at:
            issue.updated_at = now
        self.conn.execute(
            """INSERT INTO issues
               (id, session_id, project_id, title, description, status, priority,
                assignee_id, reporter_id, sprint_id, labels_json,
                linked_issue_ids_json, is_locked, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue.id, issue.session_id, issue.project_id, issue.title,
                issue.description, issue.status.value, issue.priority.value,
                issue.assignee_id, issue.reporter_id, issue.sprint_id,
                json.dumps(issue.labels), json.dumps(issue.linked_issue_ids),
                int(issue.is_locked), issue.created_at, issue.updated_at,
            ),
        )
        self.conn.commit()
        return issue

    def get_issue(self, issue_id: str) -> IssueState | None:
        row = self.conn.execute(
            "SELECT * FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_issue(row)

    def get_project_issues(self, project_id: str) -> list[IssueState]:
        rows = self.conn.execute(
            "SELECT * FROM issues WHERE project_id = ?", (project_id,)
        ).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def get_session_issues(self, session_id: str) -> list[IssueState]:
        rows = self.conn.execute(
            "SELECT * FROM issues WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def get_sprint_issues(self, sprint_id: str) -> list[IssueState]:
        rows = self.conn.execute(
            "SELECT * FROM issues WHERE sprint_id = ?", (sprint_id,)
        ).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def search_issues(self, session_id: str, filters: dict) -> list[IssueState]:
        query = "SELECT * FROM issues WHERE session_id = ?"
        params: list = [session_id]
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        if "priority" in filters:
            query += " AND priority = ?"
            params.append(filters["priority"])
        if "assignee_id" in filters:
            query += " AND assignee_id = ?"
            params.append(filters["assignee_id"])
        if "project_id" in filters:
            query += " AND project_id = ?"
            params.append(filters["project_id"])
        if "sprint_id" in filters:
            query += " AND sprint_id = ?"
            params.append(filters["sprint_id"])
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_issue(r) for r in rows]

    def update_issue(self, issue: IssueState) -> None:
        issue.updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE issues
               SET title=?, description=?, status=?, priority=?,
                   assignee_id=?, reporter_id=?, sprint_id=?, labels_json=?,
                   linked_issue_ids_json=?, is_locked=?, updated_at=?
               WHERE id=?""",
            (
                issue.title, issue.description, issue.status.value,
                issue.priority.value, issue.assignee_id, issue.reporter_id,
                issue.sprint_id, json.dumps(issue.labels),
                json.dumps(issue.linked_issue_ids), int(issue.is_locked),
                issue.updated_at, issue.id,
            ),
        )
        self.conn.commit()

    def _row_to_issue(self, row: sqlite3.Row) -> IssueState:
        return IssueState(
            id=row["id"],
            session_id=row["session_id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            status=IssueStatus(row["status"]),
            priority=Priority(row["priority"]),
            assignee_id=row["assignee_id"],
            reporter_id=row["reporter_id"],
            sprint_id=row["sprint_id"],
            labels=json.loads(row["labels_json"]),
            linked_issue_ids=json.loads(row["linked_issue_ids_json"]),
            is_locked=bool(row["is_locked"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Comments ---

    def create_comment(self, comment: CommentState) -> CommentState:
        if not comment.id:
            comment.id = _uid("cmt-")
        if not comment.created_at:
            comment.created_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO comments (id, session_id, issue_id, author_id, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                comment.id, comment.session_id, comment.issue_id,
                comment.author_id, comment.body, comment.created_at,
            ),
        )
        self.conn.commit()
        return comment

    def get_issue_comments(self, issue_id: str) -> list[CommentState]:
        rows = self.conn.execute(
            "SELECT * FROM comments WHERE issue_id = ? ORDER BY created_at",
            (issue_id,),
        ).fetchall()
        return [self._row_to_comment(r) for r in rows]

    def search_comments(self, session_id: str, filters: dict) -> list[CommentState]:
        query = "SELECT * FROM comments WHERE session_id = ?"
        params: list = [session_id]
        if "issue_id" in filters:
            query += " AND issue_id = ?"
            params.append(filters["issue_id"])
        if "author_id" in filters:
            query += " AND author_id = ?"
            params.append(filters["author_id"])
        query += " ORDER BY created_at"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_comment(r) for r in rows]

    def get_comment(self, comment_id: str) -> CommentState | None:
        row = self.conn.execute(
            "SELECT * FROM comments WHERE id = ?", (comment_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_comment(row)

    def delete_comment(self, comment_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def _row_to_comment(self, row: sqlite3.Row) -> CommentState:
        return CommentState(
            id=row["id"],
            session_id=row["session_id"],
            issue_id=row["issue_id"],
            author_id=row["author_id"],
            body=row["body"],
            created_at=row["created_at"],
        )

    # --- Decision Records ---

    def record_decision(self, decision: DecisionRecord) -> DecisionRecord:
        if not decision.id:
            decision.id = _uid("dec-")
        if not decision.timestamp:
            decision.timestamp = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO decision_records
               (id, session_id, actor_id, actor_name, action, params_json,
                affordances_snapshot_json, affordances_not_taken_json,
                result_summary, events_json, was_valid, error_message, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.id, decision.session_id, decision.actor_id,
                decision.actor_name, decision.action,
                json.dumps(decision.params),
                json.dumps(decision.affordances_snapshot),
                json.dumps(decision.affordances_not_taken),
                decision.result_summary,
                json.dumps(decision.events),
                int(decision.was_valid), decision.error_message,
                decision.timestamp,
            ),
        )
        self.conn.commit()
        return decision

    def get_session_decisions(self, session_id: str) -> list[DecisionRecord]:
        rows = self.conn.execute(
            "SELECT * FROM decision_records WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def _row_to_decision(self, row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            id=row["id"],
            session_id=row["session_id"],
            actor_id=row["actor_id"],
            actor_name=row["actor_name"],
            action=row["action"],
            params=json.loads(row["params_json"]),
            affordances_snapshot=json.loads(row["affordances_snapshot_json"]),
            affordances_not_taken=json.loads(row["affordances_not_taken_json"]),
            result_summary=row["result_summary"],
            events=json.loads(row["events_json"]),
            was_valid=bool(row["was_valid"]),
            error_message=row["error_message"],
            timestamp=row["timestamp"],
        )
