"""60 tools — extends 30 with per-field updates, audit, granular search, workflow, bulk ops."""

from __future__ import annotations

from .tools_30 import TOOLS_30

TOOLS_60_EXTRA = [
    # Per-field issue updates
    {"name": "set_issue_title", "description": "Set the title of an issue.", "parameters": {"issue_id": {"type": "string"}, "title": {"type": "string"}}, "required": ["issue_id", "title"]},
    {"name": "set_issue_description", "description": "Set the description of an issue.", "parameters": {"issue_id": {"type": "string"}, "description": {"type": "string"}}, "required": ["issue_id", "description"]},
    {"name": "set_issue_priority", "description": "Set the priority of an issue.", "parameters": {"issue_id": {"type": "string"}, "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"]}}, "required": ["issue_id", "priority"]},
    {"name": "set_issue_assignee", "description": "Set the assignee of an issue.", "parameters": {"issue_id": {"type": "string"}, "assignee_id": {"type": "string"}}, "required": ["issue_id", "assignee_id"]},
    {"name": "set_issue_status", "description": "Set the status of an issue. Must follow valid transitions.", "parameters": {"issue_id": {"type": "string"}, "status": {"type": "string", "enum": ["open", "in_progress", "in_review", "resolved", "closed"]}}, "required": ["issue_id", "status"]},
    # Audit tools
    {"name": "get_issue_history", "description": "Get the decision/change history for an issue.", "parameters": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
    {"name": "get_sprint_burndown", "description": "Get sprint burndown data: total issues, resolved, open by priority.", "parameters": {"sprint_id": {"type": "string"}}, "required": ["sprint_id"]},
    # Granular search
    {"name": "search_issues_by_assignee", "description": "Find all issues assigned to a specific user.", "parameters": {"assignee_id": {"type": "string"}}, "required": ["assignee_id"]},
    {"name": "search_issues_by_label", "description": "Find all issues with a specific label.", "parameters": {"label_id": {"type": "string"}}, "required": ["label_id"]},
    {"name": "search_issues_by_sprint", "description": "Find all issues in a specific sprint.", "parameters": {"sprint_id": {"type": "string"}}, "required": ["sprint_id"]},
    {"name": "search_issues_by_status", "description": "Find all issues with a specific status.", "parameters": {"status": {"type": "string", "enum": ["open", "in_progress", "in_review", "resolved", "closed"]}}, "required": ["status"]},
    {"name": "search_issues_by_priority", "description": "Find all issues with a specific priority.", "parameters": {"priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"]}}, "required": ["priority"]},
    # Workflow-specific
    {"name": "start_review", "description": "Transition an in_progress issue to in_review.", "parameters": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
    {"name": "complete_review", "description": "Transition an in_review issue to resolved (without PR approval flow).", "parameters": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
    {"name": "request_changes", "description": "Send an in_review issue back to in_progress.", "parameters": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
    # Bulk operations
    {"name": "bulk_assign", "description": "Assign multiple issues to a single user.", "parameters": {"issue_ids": {"type": "array", "items": {"type": "string"}}, "assignee_id": {"type": "string"}}, "required": ["issue_ids", "assignee_id"]},
    {"name": "bulk_label", "description": "Add a label to multiple issues.", "parameters": {"issue_ids": {"type": "array", "items": {"type": "string"}}, "label_id": {"type": "string"}}, "required": ["issue_ids", "label_id"]},
    {"name": "bulk_close", "description": "Close multiple issues at once.", "parameters": {"issue_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["issue_ids"]},
    # Cross-resource
    {"name": "get_user_workload", "description": "Get count of open/in-progress issues assigned to a user.", "parameters": {"user_id": {"type": "string"}}, "required": ["user_id"]},
    {"name": "get_project_stats", "description": "Get project statistics: issue counts by status, sprint counts, member count.", "parameters": {"project_id": {"type": "string"}}, "required": ["project_id"]},
    # Additional CRUD
    {"name": "remove_label", "description": "Remove a label from an issue.", "parameters": {"issue_id": {"type": "string"}, "label_id": {"type": "string"}}, "required": ["issue_id", "label_id"]},
    {"name": "lock_issue", "description": "Lock an issue to prevent modifications. Only admins and managers.", "parameters": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
    {"name": "unlock_issue", "description": "Unlock a locked issue. Only admins and managers.", "parameters": {"issue_id": {"type": "string"}}, "required": ["issue_id"]},
    {"name": "activate_sprint", "description": "Activate a sprint that is in planning status. Only admins and managers.", "parameters": {"sprint_id": {"type": "string"}}, "required": ["sprint_id"]},
    {"name": "activate_project", "description": "Activate a project that is in setup status. Only admins and managers.", "parameters": {"project_id": {"type": "string"}}, "required": ["project_id"]},
    {"name": "list_projects", "description": "List all projects in the current session.", "parameters": {}, "required": []},
    {"name": "list_sprints", "description": "List all sprints, optionally filtered by project.", "parameters": {"project_id": {"type": "string"}}, "required": []},
    {"name": "list_users", "description": "List all users, optionally filtered by role.", "parameters": {"role": {"type": "string", "enum": ["admin", "manager", "developer", "viewer"]}}, "required": []},
    {"name": "list_labels", "description": "List all available labels.", "parameters": {}, "required": []},
    {"name": "get_comment", "description": "Get a specific comment by ID.", "parameters": {"comment_id": {"type": "string"}}, "required": ["comment_id"]},
]

TOOLS_60 = TOOLS_30 + TOOLS_60_EXTRA
