"""30 tools — extends the 15 baseline with 15 more specific operations."""

from __future__ import annotations

from .tools_15 import TOOLS_15

TOOLS_30_EXTRA = [
    {
        "name": "reopen_issue",
        "description": "Reopen a closed issue. Transitions from 'closed' back to 'open'.",
        "parameters": {"issue_id": {"type": "string"}},
        "required": ["issue_id"],
    },
    {
        "name": "change_priority",
        "description": "Change the priority of an issue. Cannot modify locked issues.",
        "parameters": {
            "issue_id": {"type": "string"},
            "new_priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"]},
        },
        "required": ["issue_id", "new_priority"],
    },
    {
        "name": "link_issues",
        "description": "Create a bidirectional link between two issues.",
        "parameters": {
            "issue_id_a": {"type": "string"},
            "issue_id_b": {"type": "string"},
        },
        "required": ["issue_id_a", "issue_id_b"],
    },
    {
        "name": "unlink_issues",
        "description": "Remove the link between two issues.",
        "parameters": {
            "issue_id_a": {"type": "string"},
            "issue_id_b": {"type": "string"},
        },
        "required": ["issue_id_a", "issue_id_b"],
    },
    {
        "name": "bulk_update_issues",
        "description": "Update multiple issues at once with the same field values. Provide a list of issue IDs and the fields to update.",
        "parameters": {
            "issue_ids": {"type": "array", "items": {"type": "string"}},
            "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4"]},
            "assignee_id": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["issue_ids"],
    },
    {
        "name": "move_issue_to_sprint",
        "description": "Move an issue to a specific sprint. Cannot add to closed sprints.",
        "parameters": {
            "issue_id": {"type": "string"},
            "sprint_id": {"type": "string"},
        },
        "required": ["issue_id", "sprint_id"],
    },
    {
        "name": "remove_from_sprint",
        "description": "Remove an issue from its current sprint.",
        "parameters": {"issue_id": {"type": "string"}},
        "required": ["issue_id"],
    },
    {
        "name": "get_sprint",
        "description": "Get sprint details including name, status, and list of issues.",
        "parameters": {"sprint_id": {"type": "string"}},
        "required": ["sprint_id"],
    },
    {
        "name": "list_sprint_issues",
        "description": "List all issues assigned to a specific sprint.",
        "parameters": {"sprint_id": {"type": "string"}},
        "required": ["sprint_id"],
    },
    {
        "name": "update_sprint",
        "description": "Update sprint name. Only admins and managers.",
        "parameters": {
            "sprint_id": {"type": "string"},
            "name": {"type": "string"},
        },
        "required": ["sprint_id", "name"],
    },
    {
        "name": "add_project_member",
        "description": "Add a user as a member to a project. Only admins and managers.",
        "parameters": {
            "project_id": {"type": "string"},
            "member_id": {"type": "string"},
        },
        "required": ["project_id", "member_id"],
    },
    {
        "name": "remove_project_member",
        "description": "Remove a member from a project. Cannot remove the owner. Only admins and managers.",
        "parameters": {
            "project_id": {"type": "string"},
            "member_id": {"type": "string"},
        },
        "required": ["project_id", "member_id"],
    },
    {
        "name": "search_comments",
        "description": "Search comments by issue or author.",
        "parameters": {
            "issue_id": {"type": "string"},
            "author_id": {"type": "string"},
        },
        "required": [],
    },
    {
        "name": "delete_comment",
        "description": "Delete a comment. Only the comment author or an admin can delete.",
        "parameters": {"comment_id": {"type": "string"}},
        "required": ["comment_id"],
    },
    {
        "name": "update_comment",
        "description": "Update a comment's body text. Only the author or an admin can edit.",
        "parameters": {
            "comment_id": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["comment_id", "body"],
    },
]

TOOLS_30 = TOOLS_15 + TOOLS_30_EXTRA
