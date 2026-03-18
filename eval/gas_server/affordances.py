"""Affordance layer — computes valid actions from user role and resource states."""

from __future__ import annotations

from eval.backend.context import EvalContext
from eval.backend.models import (
    Affordance,
    IssueStatus,
    Priority,
    ProjectStatus,
    SprintStatus,
    UserRole,
)


def compute_affordances(
    ctx: EvalContext,
    session_id: str,
) -> list[Affordance]:
    """Compute available actions based on acting user's role and resource states."""
    session = ctx.get_session(session_id)
    if not session:
        return []

    user = ctx.get_user(session.acting_user_id)
    if not user:
        return []

    affordances: list[Affordance] = []
    is_viewer = user.role == UserRole.viewer
    can_manage = user.role in (UserRole.admin, UserRole.manager)

    projects = ctx.db.get_session_projects(session_id)
    issues = ctx.db.get_session_issues(session_id)
    sprints = ctx.db.get_session_sprints(session_id)

    all_user_ids = [u.id for u in ctx.get_all_users()]
    assignable_users = [u for u in ctx.get_all_users() if u.role != UserRole.viewer]
    label_ids = [lb.id for lb in ctx.get_all_labels()]

    # --- Read actions (always available) ---

    for proj in projects:
        affordances.append(Affordance(
            action="get_project",
            description=f"View project '{proj.name}' details",
            schema={"project_id": {"type": "string", "const": proj.id}},
        ))

    for issue in issues:
        affordances.append(Affordance(
            action="get_issue",
            description=f"View issue '{issue.title}' ({issue.status.value})",
            schema={"issue_id": {"type": "string", "const": issue.id}},
        ))

    affordances.append(Affordance(
        action="search_issues",
        description="Search issues by status, priority, assignee, project, or sprint",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": [s.value for s in IssueStatus]},
                    "priority": {"type": "string", "enum": [p.value for p in Priority]},
                    "assignee_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "sprint_id": {"type": "string"},
                },
            },
        },
    ))

    affordances.append(Affordance(
        action="search_comments",
        description="Search comments by issue or author",
        schema={
            "filters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string"},
                    "author_id": {"type": "string"},
                },
            },
        },
    ))

    for sprint in sprints:
        affordances.append(Affordance(
            action="get_sprint",
            description=f"View sprint '{sprint.name}' ({sprint.status.value})",
            schema={"sprint_id": {"type": "string", "const": sprint.id}},
        ))

    affordances.append(Affordance(
        action="get_user",
        description="View user details",
        schema={"user_id": {"type": "string", "enum": all_user_ids}},
    ))

    if is_viewer:
        return affordances

    # --- Write actions (non-viewers only) ---

    # Issue creation
    for proj in projects:
        if proj.status != ProjectStatus.closed:
            affordances.append(Affordance(
                action="create_issue",
                description=f"Create a new issue in '{proj.name}'",
                schema={
                    "project_id": {"type": "string", "const": proj.id},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string", "enum": [p.value for p in Priority]},
                },
            ))

    # Per-issue write actions
    for issue in issues:
        if issue.is_locked:
            if can_manage:
                affordances.append(Affordance(
                    action="unlock_issue",
                    description=f"Unlock issue '{issue.title}'",
                    schema={"issue_id": {"type": "string", "const": issue.id}},
                ))
            continue

        # Status transitions
        from eval.backend.domain import ISSUE_TRANSITIONS
        valid_transitions = ISSUE_TRANSITIONS.get(issue.status, [])
        for target in valid_transitions:
            affordances.append(Affordance(
                action="transition_issue",
                description=f"Move '{issue.title}' from {issue.status.value} → {target.value}",
                schema={
                    "issue_id": {"type": "string", "const": issue.id},
                    "new_status": {"type": "string", "const": target.value},
                },
            ))

        # Assignment
        affordances.append(Affordance(
            action="assign_issue",
            description=f"Assign '{issue.title}' to a user",
            schema={
                "issue_id": {"type": "string", "const": issue.id},
                "assignee_id": {"type": "string", "enum": [u.id for u in assignable_users]},
            },
        ))

        # Priority change
        other_priorities = [p for p in Priority if p != issue.priority]
        if other_priorities:
            affordances.append(Affordance(
                action="change_priority",
                description=f"Change priority of '{issue.title}' (currently {issue.priority.value})",
                schema={
                    "issue_id": {"type": "string", "const": issue.id},
                    "new_priority": {"type": "string", "enum": [p.value for p in other_priorities]},
                },
            ))

        # Labels
        available_labels = [lid for lid in label_ids if lid not in issue.labels]
        if available_labels:
            affordances.append(Affordance(
                action="add_label",
                description=f"Add label to '{issue.title}'",
                schema={
                    "issue_id": {"type": "string", "const": issue.id},
                    "label_id": {"type": "string", "enum": available_labels},
                },
            ))
        removable_labels = issue.labels
        if removable_labels:
            affordances.append(Affordance(
                action="remove_label",
                description=f"Remove label from '{issue.title}'",
                schema={
                    "issue_id": {"type": "string", "const": issue.id},
                    "label_id": {"type": "string", "enum": removable_labels},
                },
            ))

        # Comment
        affordances.append(Affordance(
            action="add_comment",
            description=f"Add comment to '{issue.title}'",
            schema={
                "issue_id": {"type": "string", "const": issue.id},
                "body": {"type": "string"},
            },
        ))

        # Sprint assignment
        active_sprints = [s for s in sprints if s.status != SprintStatus.closed
                          and s.project_id == issue.project_id]
        if active_sprints and not issue.sprint_id:
            affordances.append(Affordance(
                action="move_to_sprint",
                description=f"Add '{issue.title}' to a sprint",
                schema={
                    "issue_id": {"type": "string", "const": issue.id},
                    "sprint_id": {"type": "string", "enum": [s.id for s in active_sprints]},
                },
            ))
        if issue.sprint_id:
            affordances.append(Affordance(
                action="remove_from_sprint",
                description=f"Remove '{issue.title}' from its sprint",
                schema={"issue_id": {"type": "string", "const": issue.id}},
            ))

        # PR approval (only for in_review issues, not by assignee)
        if issue.status == IssueStatus.in_review and issue.assignee_id != user.id:
            affordances.append(Affordance(
                action="approve_pr",
                description=f"Approve PR for '{issue.title}'",
                schema={"issue_id": {"type": "string", "const": issue.id}},
            ))

        # Linking
        other_issues = [i for i in issues if i.id != issue.id
                        and i.id not in issue.linked_issue_ids]
        if other_issues:
            affordances.append(Affordance(
                action="link_issues",
                description=f"Link '{issue.title}' to another issue",
                schema={
                    "issue_id_a": {"type": "string", "const": issue.id},
                    "issue_id_b": {"type": "string", "enum": [i.id for i in other_issues]},
                },
            ))

        # Lock (managers/admins only)
        if can_manage:
            affordances.append(Affordance(
                action="lock_issue",
                description=f"Lock issue '{issue.title}'",
                schema={"issue_id": {"type": "string", "const": issue.id}},
            ))

    # --- Sprint actions (managers/admins) ---
    if can_manage:
        for proj in projects:
            if proj.status in (ProjectStatus.setup, ProjectStatus.active):
                affordances.append(Affordance(
                    action="create_sprint",
                    description=f"Create new sprint in '{proj.name}'",
                    schema={
                        "project_id": {"type": "string", "const": proj.id},
                        "name": {"type": "string"},
                    },
                ))

        for sprint in sprints:
            if sprint.status == SprintStatus.planning:
                affordances.append(Affordance(
                    action="activate_sprint",
                    description=f"Activate sprint '{sprint.name}'",
                    schema={"sprint_id": {"type": "string", "const": sprint.id}},
                ))
            elif sprint.status == SprintStatus.active:
                # Check if closeable (no open P1s)
                sprint_issues = ctx.db.get_sprint_issues(sprint.id)
                open_p1 = [
                    i for i in sprint_issues
                    if i.priority == Priority.p1
                    and i.status not in (IssueStatus.resolved, IssueStatus.closed)
                ]
                if not open_p1:
                    affordances.append(Affordance(
                        action="close_sprint",
                        description=f"Close sprint '{sprint.name}'",
                        schema={"sprint_id": {"type": "string", "const": sprint.id}},
                    ))
                else:
                    affordances.append(Affordance(
                        action="close_sprint",
                        description=f"Close sprint '{sprint.name}' (BLOCKED: open P1 issues)",
                        schema={"sprint_id": {"type": "string", "const": sprint.id}},
                        constraints=[f"Must resolve P1 issues first: {[i.title for i in open_p1]}"],
                    ))

    # --- Project actions (managers/admins) ---
    if can_manage:
        for proj in projects:
            if proj.status == ProjectStatus.setup:
                affordances.append(Affordance(
                    action="activate_project",
                    description=f"Activate project '{proj.name}'",
                    schema={"project_id": {"type": "string", "const": proj.id}},
                ))

            if proj.status in (ProjectStatus.active, ProjectStatus.review):
                proj_sprints = [s for s in sprints if s.project_id == proj.id]
                active_sprints = [s for s in proj_sprints if s.status == SprintStatus.active]
                if not active_sprints:
                    affordances.append(Affordance(
                        action="close_project",
                        description=f"Close project '{proj.name}'",
                        schema={"project_id": {"type": "string", "const": proj.id}},
                    ))

            # Member management
            non_members = [u for u in ctx.get_all_users() if u.id not in proj.member_ids]
            if non_members:
                affordances.append(Affordance(
                    action="add_project_member",
                    description=f"Add member to '{proj.name}'",
                    schema={
                        "project_id": {"type": "string", "const": proj.id},
                        "member_id": {"type": "string", "enum": [u.id for u in non_members]},
                    },
                ))
            removable = [mid for mid in proj.member_ids if mid != proj.owner_id]
            if removable:
                affordances.append(Affordance(
                    action="remove_project_member",
                    description=f"Remove member from '{proj.name}'",
                    schema={
                        "project_id": {"type": "string", "const": proj.id},
                        "member_id": {"type": "string", "enum": removable},
                    },
                ))

    return affordances
