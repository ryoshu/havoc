"""60 polymorphic tools — same handlers as trad-60, ambiguous synonym-heavy names.

Disentangles tool-count scaling from name specificity. If models recover at
trad-60-poly the same way they do at trad-60, the recovery is scale tolerance;
if they collapse, name specificity was the driver.
"""

from __future__ import annotations

from .tools_60 import TOOLS_60

# ── Poly-name → canonical-name mapping ──────────────────────────────────────

POLY_TO_CANONICAL: dict[str, str] = {
    "open_ticket": "create_issue",
    "fetch_ticket": "get_issue",
    "patch_record": "update_issue",
    "resolve_item": "close_issue",
    "delegate_task": "assign_issue",
    "post_note": "add_comment",
    "init_workspace": "create_project",
    "fetch_workspace": "get_project",
    "archive_workspace": "close_project",
    "plan_iteration": "create_sprint",
    "finalize_iteration": "close_sprint",
    "tag_item": "add_label",
    "query_records": "search_issues",
    "fetch_member": "get_user",
    "sign_off_review": "approve_pr",
    "restore_ticket": "reopen_issue",
    "adjust_urgency": "change_priority",
    "connect_items": "link_issues",
    "disconnect_items": "unlink_issues",
    "batch_modify": "bulk_update_issues",
    "attach_to_iteration": "move_issue_to_sprint",
    "detach_from_iteration": "remove_from_sprint",
    "fetch_iteration": "get_sprint",
    "enumerate_iteration_items": "list_sprint_issues",
    "rename_iteration": "update_sprint",
    "enroll_contributor": "add_project_member",
    "drop_contributor": "remove_project_member",
    "find_notes": "search_comments",
    "remove_note": "delete_comment",
    "edit_note": "update_comment",
    "rename_item": "set_issue_title",
    "revise_summary": "set_issue_description",
    "set_urgency_level": "set_issue_priority",
    "reassign_ticket": "set_issue_assignee",
    "update_state": "set_issue_status",
    "audit_trail": "get_issue_history",
    "progress_snapshot": "get_sprint_burndown",
    "lookup_by_owner": "search_issues_by_assignee",
    "filter_tagged_items": "search_issues_by_label",
    "filter_by_iteration": "search_issues_by_sprint",
    "filter_by_state": "search_issues_by_status",
    "filter_by_urgency": "search_issues_by_priority",
    "submit_for_evaluation": "start_review",
    "finalize_evaluation": "complete_review",
    "return_for_rework": "request_changes",
    "batch_delegate": "bulk_assign",
    "batch_tag": "bulk_label",
    "batch_resolve": "bulk_close",
    "check_capacity": "get_user_workload",
    "workspace_metrics": "get_project_stats",
    "untag_item": "remove_label",
    "freeze_record": "lock_issue",
    "unfreeze_record": "unlock_issue",
    "launch_iteration": "activate_sprint",
    "launch_workspace": "activate_project",
    "enumerate_workspaces": "list_projects",
    "enumerate_iterations": "list_sprints",
    "enumerate_members": "list_users",
    "enumerate_tags": "list_labels",
    "fetch_note": "get_comment",
}

# Reverse lookup: canonical → poly
_CANONICAL_TO_POLY = {v: k for k, v in POLY_TO_CANONICAL.items()}

# ── Synonym-styled descriptions ─────────────────────────────────────────────

_POLY_DESCRIPTIONS: dict[str, str] = {
    "open_ticket": "Open a new ticket in a workspace. Requires: project_id, title. Optional: description, priority (p1-p4, default p3). Viewers cannot open tickets. Cannot open in archived workspaces.",
    "fetch_ticket": "Fetch ticket details by ID. Returns ticket data including state, urgency, delegate, tags, and notes.",
    "patch_record": "Patch record fields. Can change title, description, status, priority, assignee_id, sprint_id, labels. State transitions must follow valid flows. Cannot modify frozen records. Viewers cannot patch.",
    "resolve_item": "Resolve an item by setting its state to closed. Item must be in 'resolved' or 'open' state. Cannot resolve frozen items. Viewers cannot resolve.",
    "delegate_task": "Delegate a task to a team member. Cannot delegate to viewers or nonexistent members. Cannot modify frozen records.",
    "post_note": "Post a note on a ticket. Viewers cannot post notes.",
    "init_workspace": "Initialize a new workspace. Only admins and managers can initialize workspaces.",
    "fetch_workspace": "Fetch workspace details by ID, including state, owner, and contributors.",
    "archive_workspace": "Archive a workspace. Cannot archive if there are active iterations. Only admins and managers.",
    "plan_iteration": "Plan a new iteration in a workspace. Only admins and managers. Workspace must be in setup or active state.",
    "finalize_iteration": "Finalize an active iteration. Cannot finalize if there are unresolved P1 items. Only admins and managers.",
    "tag_item": "Tag an item with a label. Cannot modify frozen items. Viewers cannot tag.",
    "query_records": "Query records with filters. Available filters: status, priority, assignee_id, project_id, sprint_id.",
    "fetch_member": "Fetch member details by ID, including name, email, and role.",
    "sign_off_review": "Sign off on a review for a ticket. Ticket must be in 'in_review' state. Cannot self-approve. Viewers cannot sign off.",
    "restore_ticket": "Restore a closed ticket. Transitions from 'closed' back to 'open'.",
    "adjust_urgency": "Adjust the urgency level of a ticket. Cannot modify frozen records.",
    "connect_items": "Create a bidirectional connection between two items.",
    "disconnect_items": "Remove the connection between two items.",
    "batch_modify": "Modify multiple records at once with the same field values. Provide a list of record IDs and the fields to modify.",
    "attach_to_iteration": "Attach an item to a specific iteration. Cannot attach to finalized iterations.",
    "detach_from_iteration": "Detach an item from its current iteration.",
    "fetch_iteration": "Fetch iteration details including name, state, and list of items.",
    "enumerate_iteration_items": "Enumerate all items attached to a specific iteration.",
    "rename_iteration": "Rename an iteration. Only admins and managers.",
    "enroll_contributor": "Enroll a member as a contributor to a workspace. Only admins and managers.",
    "drop_contributor": "Drop a contributor from a workspace. Cannot drop the owner. Only admins and managers.",
    "find_notes": "Find notes by ticket or author.",
    "remove_note": "Remove a note. Only the note author or an admin can remove.",
    "edit_note": "Edit a note's body text. Only the author or an admin can edit.",
    "rename_item": "Rename an item by setting its title.",
    "revise_summary": "Revise the summary text of an item.",
    "set_urgency_level": "Set the urgency level of a ticket.",
    "reassign_ticket": "Reassign a ticket to a different team member.",
    "update_state": "Update the state of a ticket. Must follow valid transitions.",
    "audit_trail": "Retrieve the audit trail of decisions and changes for a ticket.",
    "progress_snapshot": "Get a progress snapshot: total items, resolved, open by urgency.",
    "lookup_by_owner": "Look up all items owned by a specific member.",
    "filter_tagged_items": "Filter items that have a specific tag applied.",
    "filter_by_iteration": "Filter all items within a specific iteration.",
    "filter_by_state": "Filter all items with a specific state.",
    "filter_by_urgency": "Filter all items with a specific urgency level.",
    "submit_for_evaluation": "Submit an in-progress item for evaluation.",
    "finalize_evaluation": "Finalize an evaluation, transitioning the item to resolved.",
    "return_for_rework": "Return an item under evaluation back to in-progress.",
    "batch_delegate": "Delegate multiple items to a single member.",
    "batch_tag": "Apply a tag to multiple items.",
    "batch_resolve": "Resolve multiple items at once.",
    "check_capacity": "Check a member's capacity: count of open/in-progress items assigned.",
    "workspace_metrics": "Get workspace metrics: item counts by state, iteration counts, contributor count.",
    "untag_item": "Remove a tag from an item.",
    "freeze_record": "Freeze a record to prevent modifications. Only admins and managers.",
    "unfreeze_record": "Unfreeze a frozen record. Only admins and managers.",
    "launch_iteration": "Launch an iteration that is in planning state. Only admins and managers.",
    "launch_workspace": "Launch a workspace that is in setup state. Only admins and managers.",
    "enumerate_workspaces": "Enumerate all workspaces in the current session.",
    "enumerate_iterations": "Enumerate all iterations, optionally filtered by workspace.",
    "enumerate_members": "Enumerate all members, optionally filtered by role.",
    "enumerate_tags": "Enumerate all available tags.",
    "fetch_note": "Fetch a specific note by ID.",
}

# ── Build TOOLS_60_POLY from TOOLS_60 ───────────────────────────────────────


def _build_poly_tools() -> list[dict]:
    """Clone TOOLS_60, replacing names and descriptions with poly variants."""
    poly_tools = []
    for tool in TOOLS_60:
        canonical = tool["name"]
        poly_name = _CANONICAL_TO_POLY.get(canonical)
        if poly_name is None:
            raise ValueError(f"No poly mapping for canonical tool: {canonical}")
        poly_tool = {
            "name": poly_name,
            "description": _POLY_DESCRIPTIONS[poly_name],
            "parameters": tool["parameters"],
            "required": tool["required"],
        }
        poly_tools.append(poly_tool)
    return poly_tools


TOOLS_60_POLY = _build_poly_tools()
