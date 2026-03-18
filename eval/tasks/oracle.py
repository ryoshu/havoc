"""Oracle — deterministic success checker for eval tasks."""

from __future__ import annotations

from eval.backend.context import EvalContext
from eval.backend.models import IssueStatus, SprintStatus, ProjectStatus, Priority


def check_oracle(
    ctx: EvalContext,
    session_id: str,
    checks: list[dict],
    id_map: dict[str, str] | None = None,
) -> tuple[bool, list[dict]]:
    """Run oracle checks against current state. Returns (all_passed, details)."""
    id_map = id_map or {}

    def resolve_id(value: str) -> str:
        if not value:
            return value
        return id_map.get(value, value)

    details = []
    all_passed = True

    for check in checks:
        check_type = check["type"]
        passed = False
        message = ""

        if check_type == "issue_status":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                expected = IssueStatus(check["expected"])
                passed = issue.status == expected
                message = f"Issue '{issue.title}' status: {issue.status.value} (expected {expected.value})"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "issue_assignee":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                passed = issue.assignee_id == check["expected"]
                message = f"Issue '{issue.title}' assignee: {issue.assignee_id} (expected {check['expected']})"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "issue_priority":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                expected = Priority(check["expected"])
                passed = issue.priority == expected
                message = f"Issue '{issue.title}' priority: {issue.priority.value} (expected {expected.value})"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "issue_has_label":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                passed = check["label_id"] in issue.labels
                message = f"Issue '{issue.title}' has label '{check['label_id']}': {passed}"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "issue_in_sprint":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                expected_sprint = resolve_id(check["expected"])
                passed = issue.sprint_id == expected_sprint
                message = f"Issue '{issue.title}' sprint: {issue.sprint_id} (expected {expected_sprint})"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "comment_exists":
            issue_id = resolve_id(check.get("issue_id", ""))
            if issue_id:
                comments = ctx.db.get_issue_comments(issue_id)
            else:
                comments = ctx.db.search_comments(session_id, {})
            if "body_contains" in check:
                passed = any(check["body_contains"].lower() in c.body.lower() for c in comments)
                scope = issue_id or "session"
                message = f"Comment containing '{check['body_contains']}' in {scope}: {passed}"
            elif "author_id" in check:
                passed = any(c.author_id == check["author_id"] for c in comments)
                scope = issue_id or "session"
                message = f"Comment by '{check['author_id']}' in {scope}: {passed}"
            else:
                passed = len(comments) > 0
                scope = issue_id or "session"
                message = f"Any comment exists in {scope}: {passed}"

        elif check_type == "sprint_status":
            sprint_id = resolve_id(check["sprint_id"])
            sprint = ctx.db.get_sprint(sprint_id)
            if sprint:
                expected = SprintStatus(check["expected"])
                passed = sprint.status == expected
                message = f"Sprint '{sprint.name}' status: {sprint.status.value} (expected {expected.value})"
            else:
                message = f"Sprint '{sprint_id}' not found"

        elif check_type == "sprint_exists":
            sprints = ctx.db.get_session_sprints(session_id)
            if "name_contains" in check:
                needle = check["name_contains"].lower()
                sprints = [s for s in sprints if needle in s.name.lower()]
            if "project_id" in check:
                project_id = resolve_id(check["project_id"])
                sprints = [s for s in sprints if s.project_id == project_id]
            if "expected_status" in check:
                expected_status = SprintStatus(check["expected_status"])
                sprints = [s for s in sprints if s.status == expected_status]
            passed = len(sprints) > 0
            message = f"Sprint exists matching filters: {passed} (matches={len(sprints)})"

        elif check_type == "project_status":
            project_id = resolve_id(check["project_id"])
            proj = ctx.db.get_project(project_id)
            if proj:
                expected = ProjectStatus(check["expected"])
                passed = proj.status == expected
                message = f"Project '{proj.name}' status: {proj.status.value} (expected {expected.value})"
            else:
                message = f"Project '{project_id}' not found"

        elif check_type == "issue_count":
            issues = ctx.db.get_session_issues(session_id)
            filters = check.get("filters", {})
            if "status" in filters:
                issues = [i for i in issues if i.status.value == filters["status"]]
            if "project_id" in filters:
                project_id = resolve_id(filters["project_id"])
                issues = [i for i in issues if i.project_id == project_id]
            if "priority" in filters:
                issues = [i for i in issues if i.priority.value == filters["priority"]]
            if "sprint_id" in filters:
                sprint_id = resolve_id(filters["sprint_id"])
                issues = [i for i in issues if i.sprint_id == sprint_id]
            op = check.get("op", "eq")
            expected = check["expected"]
            if op == "eq":
                passed = len(issues) == expected
            elif op == "gte":
                passed = len(issues) >= expected
            elif op == "lte":
                passed = len(issues) <= expected
            message = f"Issue count ({op}): {len(issues)} vs {expected}"

        elif check_type == "no_backend_errors":
            decisions = ctx.db.get_session_decisions(session_id)
            invalid = [d for d in decisions if not d.was_valid]
            passed = len(invalid) == 0
            message = f"Backend errors: {len(invalid)}"

        elif check_type == "issue_exists":
            issues = ctx.db.get_session_issues(session_id)
            if "title_contains" in check:
                passed = any(check["title_contains"].lower() in i.title.lower() for i in issues)
                message = f"Issue with title containing '{check['title_contains']}': {passed}"
            else:
                passed = len(issues) > 0
                message = f"Any issue exists: {passed}"

        elif check_type == "issue_not_locked":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                passed = not issue.is_locked
                message = f"Issue '{issue.title}' locked: {issue.is_locked}"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "issue_in_named_sprint":
            issue_id = resolve_id(check["issue_id"])
            issue = ctx.db.get_issue(issue_id)
            if issue:
                if not issue.sprint_id:
                    passed = False
                    message = f"Issue '{issue.title}' is not in a sprint"
                else:
                    sprint = ctx.db.get_sprint(issue.sprint_id)
                    expected_name = check["sprint_name"]
                    passed = bool(sprint and sprint.name == expected_name)
                    actual = sprint.name if sprint else "<missing sprint>"
                    message = f"Issue '{issue.title}' sprint name: {actual} (expected {expected_name})"
            else:
                message = f"Issue '{issue_id}' not found"

        elif check_type == "issues_linked":
            issue_id_a = resolve_id(check["issue_id_a"])
            issue_id_b = resolve_id(check["issue_id_b"])
            issue_a = ctx.db.get_issue(issue_id_a)
            issue_b = ctx.db.get_issue(issue_id_b)
            if issue_a and issue_b:
                passed = issue_id_b in issue_a.linked_issue_ids
                message = f"Issues linked: {passed}"
            else:
                message = "One or both issues not found"

        elif check_type == "project_has_member":
            project_id = resolve_id(check["project_id"])
            proj = ctx.db.get_project(project_id)
            if proj:
                passed = check["member_id"] in proj.member_ids
                message = f"Project '{proj.name}' has member '{check['member_id']}': {passed}"
            else:
                message = f"Project '{project_id}' not found"

        else:
            message = f"Unknown check type: {check_type}"

        if not passed:
            all_passed = False
        details.append({"type": check_type, "passed": passed, "message": message})

    return all_passed, details
