"""15 baseline tools for the traditional MCP server."""

from __future__ import annotations

TOOLS_15 = [
    {
        "name": "create_issue",
        "description": "Create a new issue in a project. Requires: project_id, title. Optional: description, priority (p1-p4, default p3). Viewers cannot create issues. Cannot create in closed projects.",
        "parameters": {
            "project_id": {"type": "string", "description": "Project ID"},
            "title": {"type": "string", "description": "Issue title"},
            "description": {"type": "string", "description": "Issue description"},
            "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"], "description": "Priority level"},
        },
        "required": ["project_id", "title"],
    },
    {
        "name": "get_issue",
        "description": "Get issue details by ID. Returns issue data including status, priority, assignee, labels, and comments.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID"},
        },
        "required": ["issue_id"],
    },
    {
        "name": "update_issue",
        "description": "Update issue fields. Can change title, description, status, priority, assignee_id, sprint_id, labels. Status transitions must follow: open→in_progress→in_review→resolved→closed (reopen: closed→open, in_progress→open, in_review→in_progress). Cannot modify locked issues. Viewers cannot update.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID"},
            "title": {"type": "string", "description": "New title"},
            "description": {"type": "string", "description": "New description"},
            "status": {"type": "string", "enum": ["open", "in_progress", "in_review", "resolved", "closed"], "description": "New status"},
            "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"]},
            "assignee_id": {"type": "string", "description": "User ID to assign to. Cannot assign to viewers."},
            "sprint_id": {"type": "string", "description": "Sprint ID to move to. Cannot add to closed sprints."},
        },
        "required": ["issue_id"],
    },
    {
        "name": "close_issue",
        "description": "Close an issue. Transitions status to 'closed'. Issue must be in 'resolved' or 'open' state. Cannot close locked issues. Viewers cannot close.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID to close"},
        },
        "required": ["issue_id"],
    },
    {
        "name": "assign_issue",
        "description": "Assign an issue to a user. Cannot assign to viewers or nonexistent users. Cannot modify locked issues.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID"},
            "assignee_id": {"type": "string", "description": "User ID to assign to"},
        },
        "required": ["issue_id", "assignee_id"],
    },
    {
        "name": "add_comment",
        "description": "Add a comment to an issue. Viewers cannot comment.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID"},
            "body": {"type": "string", "description": "Comment text"},
        },
        "required": ["issue_id", "body"],
    },
    {
        "name": "create_project",
        "description": "Create a new project. Only admins and managers can create projects.",
        "parameters": {
            "name": {"type": "string", "description": "Project name"},
            "description": {"type": "string", "description": "Project description"},
        },
        "required": ["name"],
    },
    {
        "name": "get_project",
        "description": "Get project details by ID, including status, owner, and members.",
        "parameters": {
            "project_id": {"type": "string", "description": "Project ID"},
        },
        "required": ["project_id"],
    },
    {
        "name": "close_project",
        "description": "Close a project. Cannot close if there are active sprints. Only admins and managers.",
        "parameters": {
            "project_id": {"type": "string", "description": "Project ID to close"},
        },
        "required": ["project_id"],
    },
    {
        "name": "create_sprint",
        "description": "Create a new sprint in a project. Only admins and managers. Project must be in setup or active state.",
        "parameters": {
            "project_id": {"type": "string", "description": "Project ID"},
            "name": {"type": "string", "description": "Sprint name"},
        },
        "required": ["project_id", "name"],
    },
    {
        "name": "close_sprint",
        "description": "Close an active sprint. Cannot close if there are unresolved P1 issues. Only admins and managers.",
        "parameters": {
            "sprint_id": {"type": "string", "description": "Sprint ID to close"},
        },
        "required": ["sprint_id"],
    },
    {
        "name": "add_label",
        "description": "Add a label to an issue. Cannot modify locked issues. Viewers cannot add labels.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID"},
            "label_id": {"type": "string", "description": "Label ID to add"},
        },
        "required": ["issue_id", "label_id"],
    },
    {
        "name": "search_issues",
        "description": "Search issues with filters. Available filters: status, priority, assignee_id, project_id, sprint_id.",
        "parameters": {
            "status": {"type": "string", "enum": ["open", "in_progress", "in_review", "resolved", "closed"]},
            "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"]},
            "assignee_id": {"type": "string"},
            "project_id": {"type": "string"},
            "sprint_id": {"type": "string"},
        },
        "required": [],
    },
    {
        "name": "get_user",
        "description": "Get user details by ID, including name, email, and role.",
        "parameters": {
            "user_id": {"type": "string", "description": "User ID"},
        },
        "required": ["user_id"],
    },
    {
        "name": "approve_pr",
        "description": "Approve a PR/code review for an issue. Issue must be in 'in_review' status. Cannot self-approve (assignee cannot approve their own PR). Viewers cannot approve.",
        "parameters": {
            "issue_id": {"type": "string", "description": "Issue ID to approve"},
        },
        "required": ["issue_id"],
    },
]
