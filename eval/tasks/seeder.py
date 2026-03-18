"""Seeder — populates EvalContext from a task's setup dict."""

from __future__ import annotations

from eval.backend.context import EvalContext
from eval.backend.models import (
    CommentState,
    IssueState,
    IssueStatus,
    Priority,
    ProjectState,
    ProjectStatus,
    SprintState,
    SprintStatus,
)


def seed_task(ctx: EvalContext, session_id: str, setup: dict) -> dict:
    """Seed the eval context from a task setup dict. Returns a map of alias→real ID."""
    id_map: dict[str, str] = {}

    # Seed projects
    for proj_def in setup.get("projects", []):
        if "template_id" in proj_def:
            proj = ctx.create_project_from_template(
                session_id,
                proj_def["template_id"],
                project_id=proj_def.get("id", ""),
            )
        else:
            proj = ProjectState(
                session_id=session_id,
                name=proj_def["name"],
                description=proj_def.get("description", ""),
                status=ProjectStatus(proj_def.get("status", "active")),
                owner_id=proj_def.get("owner_id", ""),
                member_ids=proj_def.get("member_ids", []),
            )
            if proj_def.get("id"):
                proj.id = proj_def["id"]
            proj = ctx.db.create_project(proj)
        id_map[proj_def.get("alias", proj.id)] = proj.id
        if proj_def.get("template_id"):
            id_map[proj_def["template_id"]] = proj.id
        if proj_def.get("id"):
            id_map[proj_def["id"]] = proj.id

    # Seed sprints
    for sp_def in setup.get("sprints", []):
        project_id = id_map.get(sp_def.get("project_alias", ""), sp_def.get("project_id", ""))
        sprint = SprintState(
            session_id=session_id,
            project_id=project_id,
            name=sp_def["name"],
            status=SprintStatus(sp_def.get("status", "planning")),
        )
        if sp_def.get("id"):
            sprint.id = sp_def["id"]
        sprint = ctx.db.create_sprint(sprint)
        id_map[sp_def.get("alias", sprint.id)] = sprint.id
        if sp_def.get("id"):
            id_map[sp_def["id"]] = sprint.id

    # Seed issues
    for iss_def in setup.get("issues", []):
        project_id = id_map.get(iss_def.get("project_alias", ""), iss_def.get("project_id", ""))
        sprint_id = id_map.get(iss_def.get("sprint_alias", ""), iss_def.get("sprint_id", ""))
        issue = IssueState(
            session_id=session_id,
            project_id=project_id,
            title=iss_def["title"],
            description=iss_def.get("description", ""),
            status=IssueStatus(iss_def.get("status", "open")),
            priority=Priority(iss_def.get("priority", "p3")),
            assignee_id=iss_def.get("assignee_id", ""),
            reporter_id=iss_def.get("reporter_id", ""),
            sprint_id=sprint_id,
            labels=iss_def.get("labels", []),
            linked_issue_ids=iss_def.get("linked_issue_ids", []),
            is_locked=iss_def.get("is_locked", False),
        )
        if iss_def.get("id"):
            issue.id = iss_def["id"]
        issue = ctx.db.create_issue(issue)
        id_map[iss_def.get("alias", issue.id)] = issue.id
        if iss_def.get("id"):
            id_map[iss_def["id"]] = issue.id

    # Seed comments
    for cmt_def in setup.get("comments", []):
        issue_id = id_map.get(cmt_def.get("issue_alias", ""), cmt_def.get("issue_id", ""))
        comment = CommentState(
            session_id=session_id,
            issue_id=issue_id,
            author_id=cmt_def.get("author_id", ""),
            body=cmt_def.get("body", ""),
        )
        comment = ctx.db.create_comment(comment)
        id_map[cmt_def.get("alias", comment.id)] = comment.id

    return id_map
