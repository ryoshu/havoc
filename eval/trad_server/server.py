"""Traditional MCP server — N individual tools, no affordances in responses."""

from __future__ import annotations

import json

from eval.backend.context import EvalContext
from eval.backend.domain import DomainError, ProjectEngine
from eval.backend.models import (
    DecisionRecord,
    IssueStatus,
    Priority,
    ProjectState,
    ProjectStatus,
    SprintStatus,
)

from .tools_15 import TOOLS_15
from .tools_30 import TOOLS_30
from .tools_60 import TOOLS_60
from .tools_60_poly import POLY_TO_CANONICAL, TOOLS_60_POLY
from .tools_distractor import TOOLS_120D, TOOLS_240D, TOOLS_480D
from eval.gas_server.affordances import compute_affordances

TOOL_LEVELS: dict[int | str, list[dict]] = {
    15: TOOLS_15, 30: TOOLS_30, 60: TOOLS_60, "60-poly": TOOLS_60_POLY,
    "120d": TOOLS_120D, "240d": TOOLS_240D, "480d": TOOLS_480D,
}


class TradRuntime:
    """Traditional runtime — one tool per operation, no affordances."""

    def __init__(
        self,
        db_path: str = ":memory:",
        tool_level: int | str = 15,
        *,
        state_filtered: bool = False,
    ):
        self.ctx = EvalContext(db_path=db_path)
        self.engine = ProjectEngine()
        self.tool_level = tool_level
        self.state_filtered = state_filtered
        self.tools = TOOL_LEVELS[tool_level]
        self.name_map: dict[str, str] | None = (
            POLY_TO_CANONICAL if tool_level == "60-poly" else None
        )
        self.default_session_id: str = ""

    def create_session(self, acting_user_id: str) -> str:
        session = self.ctx.db.create_session(acting_user_id=acting_user_id)
        if not self.default_session_id:
            self.default_session_id = session.id
        return session.id

    def _sid(self, session_id: str) -> str:
        return session_id or self.default_session_id

    _READ_TOOL_PREFIXES = ("get_", "search_", "list_")
    _AFFORDANCE_ALIASES: dict[str, set[str]] = {
        # Coarse native tool names represent several command-kernel actions.
        "update_issue": {"transition_issue", "change_priority", "assign_issue", "add_label", "remove_label"},
        "close_issue": {"transition_issue"},
        "reopen_issue": {"transition_issue"},
        "approve_pr": {"approve_issue"},
        "complete_review": {"approve_issue"},
        "start_review": {"submit_for_review"},
        "request_changes": {"request_changes"},
        "set_issue_title": {"update_issue"},
        "set_issue_description": {"update_issue"},
        "set_issue_priority": {"change_priority"},
        "set_issue_assignee": {"assign_issue"},
        "set_issue_status": {"transition_issue"},
    }

    def _filtered_tool_names(self, session_id: str) -> set[str]:
        """Return native tools applicable to the current state.

        Reads stay visible because they are how a native-MCP agent discovers
        state. Mutation tools are filtered from the same server-authoritative
        affordance computation used by GAS; this is an interface projection,
        not a second authorization path.
        """
        sid = self._sid(session_id)
        affordances = list(compute_affordances(self.ctx, sid))
        afforded = {a.action for a in affordances}
        names: set[str] = set()
        for tool in self.tools:
            name = tool["name"]
            if name.startswith(self._READ_TOOL_PREFIXES):
                names.add(name)
                continue
            # Close/reopen are native aliases for a transition, but only the
            # exact target status should be projected as available.
            if name == "close_issue":
                if any(
                    a.action == "transition_issue"
                    and isinstance(a.schema_.get("new_status"), dict)
                    and "closed" in a.schema_["new_status"].get("enum", [])
                    for a in affordances
                ):
                    names.add(name)
                continue
            if name == "reopen_issue":
                if any(
                    a.action == "transition_issue"
                    and isinstance(a.schema_.get("new_status"), dict)
                    and "open" in a.schema_["new_status"].get("enum", [])
                    for a in affordances
                ):
                    names.add(name)
                continue
            aliases = self._AFFORDANCE_ALIASES.get(name, {name})
            if aliases & afforded:
                names.add(name)
        return names

    def get_tool_definitions(self, session_id: str = "") -> list[dict]:
        """Return OpenAI-format tool definitions for the current tool level."""
        allowed = self._filtered_tool_names(session_id) if self.state_filtered and session_id else None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            k: v for k, v in t["parameters"].items()
                        },
                        "required": t["required"],
                    },
                },
            }
            for t in self.tools
            if allowed is None or t["name"] in allowed
        ]

    def call_tool(self, tool_name: str, params: dict, session_id: str = "") -> str:
        """Execute a tool call. Returns JSON result (no affordances)."""
        sid = self._sid(session_id)
        session = self.ctx.get_session(sid)
        if not session:
            return json.dumps({"error": f"Session '{sid}' not found"})

        user = self.ctx.get_user(session.acting_user_id)
        if not user:
            return json.dumps({"error": f"Acting user '{session.acting_user_id}' not found"})

        # Validate tool exists at current level
        valid_names = {t["name"] for t in self.tools}
        if tool_name not in valid_names:
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=False,
                error_message=f"Unknown tool: {tool_name}",
            )
            self.ctx.db.record_decision(decision)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        # Resolve poly name → canonical for dispatch, keep original for records
        dispatch_name = self.name_map[tool_name] if self.name_map and tool_name in self.name_map else tool_name

        try:
            result, events = self._dispatch(sid, dispatch_name, params, user)
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=True,
                result_summary=str(result.get("message", ""))[:200] if isinstance(result, dict) else "",
                events=[e.model_dump() for e in events],
            )
            self.ctx.db.record_decision(decision)
            response = {"data": result}
            if events:
                response["events"] = [e.model_dump() for e in events]
            return json.dumps(response, indent=2)

        except DomainError as e:
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=False,
                error_message=str(e),
            )
            self.ctx.db.record_decision(decision)
            return json.dumps({"error": str(e)})
        except Exception as e:
            decision = DecisionRecord(
                session_id=sid, actor_id=user.id, actor_name=user.name,
                action=tool_name, params=params, was_valid=False,
                error_message=f"Runtime error: {e}",
            )
            self.ctx.db.record_decision(decision)
            return json.dumps({"error": f"Runtime error: {e}"})

    def _dispatch(self, session_id, tool_name, params, user):
        ctx = self.ctx
        engine = self.engine
        events = []

        # --- Read tools ---
        if tool_name == "get_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            comments = ctx.db.get_issue_comments(issue.id)
            return {**issue.model_dump(), "comments": [c.model_dump() for c in comments]}, []

        elif tool_name == "get_project":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            return proj.model_dump(), []

        elif tool_name == "get_sprint":
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            sprint_issues = ctx.db.get_sprint_issues(sprint.id)
            return {
                **sprint.model_dump(),
                "issues": [{"id": i.id, "title": i.title, "status": i.status.value} for i in sprint_issues],
            }, []

        elif tool_name == "get_user":
            u = ctx.get_user(params["user_id"])
            if not u:
                raise DomainError(f"User '{params['user_id']}' not found.")
            return u.model_dump(), []

        elif tool_name == "get_comment":
            c = ctx.db.get_comment(params["comment_id"])
            if not c:
                raise DomainError(f"Comment '{params['comment_id']}' not found.")
            return c.model_dump(), []

        elif tool_name == "search_issues":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_issues(session_id, filters)
            return {"issues": [
                {"id": i.id, "title": i.title, "status": i.status.value,
                 "priority": i.priority.value, "assignee_id": i.assignee_id}
                for i in results
            ]}, []

        elif tool_name == "search_comments":
            filters = {k: v for k, v in params.items() if v}
            results = ctx.db.search_comments(session_id, filters)
            return {"comments": [
                {"id": c.id, "issue_id": c.issue_id, "author_id": c.author_id, "body": c.body[:100]}
                for c in results
            ]}, []

        elif tool_name == "list_sprint_issues":
            results = ctx.db.get_sprint_issues(params["sprint_id"])
            return {"issues": [
                {"id": i.id, "title": i.title, "status": i.status.value, "priority": i.priority.value}
                for i in results
            ]}, []

        elif tool_name == "list_projects":
            projects = ctx.db.get_session_projects(session_id)
            return {"projects": [{"id": p.id, "name": p.name, "status": p.status.value} for p in projects]}, []

        elif tool_name == "list_sprints":
            sprints = ctx.db.get_session_sprints(session_id)
            if "project_id" in params and params["project_id"]:
                sprints = [s for s in sprints if s.project_id == params["project_id"]]
            return {"sprints": [{"id": s.id, "name": s.name, "status": s.status.value} for s in sprints]}, []

        elif tool_name == "list_users":
            users = ctx.get_all_users()
            if "role" in params and params["role"]:
                users = [u for u in users if u.role.value == params["role"]]
            return {"users": [{"id": u.id, "name": u.name, "role": u.role.value} for u in users]}, []

        elif tool_name == "list_labels":
            labels = ctx.get_all_labels()
            return {"labels": [lb.model_dump() for lb in labels]}, []

        # --- Granular search (60-level) ---
        elif tool_name == "search_issues_by_assignee":
            results = ctx.db.search_issues(session_id, {"assignee_id": params["assignee_id"]})
            return {"issues": [{"id": i.id, "title": i.title, "status": i.status.value} for i in results]}, []

        elif tool_name == "search_issues_by_label":
            all_issues = ctx.db.get_session_issues(session_id)
            filtered = [i for i in all_issues if params["label_id"] in i.labels]
            return {"issues": [{"id": i.id, "title": i.title} for i in filtered]}, []

        elif tool_name == "search_issues_by_sprint":
            results = ctx.db.get_sprint_issues(params["sprint_id"])
            return {"issues": [{"id": i.id, "title": i.title, "status": i.status.value} for i in results]}, []

        elif tool_name == "search_issues_by_status":
            results = ctx.db.search_issues(session_id, {"status": params["status"]})
            return {"issues": [{"id": i.id, "title": i.title} for i in results]}, []

        elif tool_name == "search_issues_by_priority":
            results = ctx.db.search_issues(session_id, {"priority": params["priority"]})
            return {"issues": [{"id": i.id, "title": i.title} for i in results]}, []

        # --- Audit tools (60-level) ---
        elif tool_name == "get_issue_history":
            decisions = ctx.db.get_session_decisions(session_id)
            issue_decisions = [
                d for d in decisions
                if d.params.get("issue_id") == params["issue_id"]
                or d.result_summary and params["issue_id"] in str(d.params)
            ]
            return {"history": [
                {"action": d.action, "by": d.actor_name, "at": d.timestamp,
                 "valid": d.was_valid, "summary": d.result_summary}
                for d in issue_decisions
            ]}, []

        elif tool_name == "get_sprint_burndown":
            sprint_issues = ctx.db.get_sprint_issues(params["sprint_id"])
            by_status = {}
            for i in sprint_issues:
                by_status.setdefault(i.status.value, 0)
                by_status[i.status.value] += 1
            return {"total": len(sprint_issues), "by_status": by_status}, []

        # --- Cross-resource (60-level) ---
        elif tool_name == "get_user_workload":
            issues = ctx.db.search_issues(session_id, {"assignee_id": params["user_id"]})
            open_issues = [i for i in issues if i.status in (IssueStatus.open, IssueStatus.in_progress)]
            return {"user_id": params["user_id"], "open_count": len(open_issues), "total_assigned": len(issues)}, []

        elif tool_name == "get_project_stats":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            issues = ctx.db.get_project_issues(proj.id)
            sprints = ctx.db.get_project_sprints(proj.id)
            by_status = {}
            for i in issues:
                by_status.setdefault(i.status.value, 0)
                by_status[i.status.value] += 1
            return {
                "project": proj.name, "total_issues": len(issues),
                "by_status": by_status, "sprint_count": len(sprints),
                "member_count": len(proj.member_ids),
            }, []

        # --- Write tools ---
        elif tool_name == "create_issue":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            priority = Priority(params.get("priority", "p3"))
            issue, event = engine.create_issue(
                user, proj, params["title"], params.get("description", ""), priority,
            )
            issue = ctx.db.create_issue(issue)
            return {"message": f"Created issue '{issue.title}'", "issue_id": issue.id}, [event]

        elif tool_name == "update_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            evts = []
            if "status" in params:
                new_status = IssueStatus(params["status"])
                evt = engine.transition_issue(user, issue, new_status)
                evts.append(evt)
            if "priority" in params and "status" not in params:
                evt = engine.change_priority(user, issue, Priority(params["priority"]))
                evts.append(evt)
            if "assignee_id" in params:
                assignee = ctx.get_user(params["assignee_id"])
                if not assignee:
                    raise DomainError(f"User '{params['assignee_id']}' not found.")
                evt = engine.assign_issue(user, issue, assignee, ctx._user_templates)
                evts.append(evt)
            if "title" in params:
                engine.check_not_viewer(user)
                if issue.is_locked:
                    raise DomainError(f"Issue '{issue.title}' is locked.")
                issue.title = params["title"]
            if "description" in params:
                engine.check_not_viewer(user)
                if issue.is_locked:
                    raise DomainError(f"Issue '{issue.title}' is locked.")
                issue.description = params["description"]
            if "sprint_id" in params:
                sprint = ctx.db.get_sprint(params["sprint_id"])
                if not sprint:
                    raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
                evt = engine.move_to_sprint(user, issue, sprint)
                evts.append(evt)
            ctx.db.update_issue(issue)
            return {"message": f"Updated issue '{issue.title}'"}, evts

        elif tool_name == "close_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.transition_issue(user, issue, IssueStatus.closed)
            ctx.db.update_issue(issue)
            return {"message": f"Closed issue '{issue.title}'"}, [event]

        elif tool_name == "assign_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            assignee = ctx.get_user(params["assignee_id"])
            if not assignee:
                raise DomainError(f"User '{params['assignee_id']}' not found.")
            event = engine.assign_issue(user, issue, assignee, ctx._user_templates)
            ctx.db.update_issue(issue)
            return {"message": f"Assigned '{issue.title}' to {assignee.name}"}, [event]

        elif tool_name == "add_comment":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            from eval.backend.models import CommentState
            comment, event = engine.add_comment(user, issue, params["body"])
            comment = ctx.db.create_comment(comment)
            return {"message": f"Added comment to '{issue.title}'", "comment_id": comment.id}, [event]

        elif tool_name in ("create_project",):
            engine.check_can_manage(user)
            proj = ProjectState(
                session_id=session_id, name=params["name"],
                description=params.get("description", ""),
                status=ProjectStatus.setup, owner_id=user.id,
                member_ids=[user.id],
            )
            proj = ctx.db.create_project(proj)
            from eval.backend.models import DomainEvent
            return {"message": f"Created project '{proj.name}'", "project_id": proj.id}, [
                DomainEvent(type="ProjectCreated", data={"project": proj.name})
            ]

        elif tool_name == "close_project":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            proj_sprints = ctx.db.get_project_sprints(proj.id)
            event = engine.close_project(user, proj, proj_sprints)
            ctx.db.update_project(proj)
            return {"message": f"Closed project '{proj.name}'"}, [event]

        elif tool_name == "create_sprint":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            sprint, event = engine.create_sprint(user, proj, params["name"])
            sprint = ctx.db.create_sprint(sprint)
            return {"message": f"Created sprint '{sprint.name}'", "sprint_id": sprint.id}, [event]

        elif tool_name == "close_sprint":
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            sprint_issues = ctx.db.get_sprint_issues(sprint.id)
            event = engine.close_sprint(user, sprint, sprint_issues)
            ctx.db.update_sprint(sprint)
            return {"message": f"Closed sprint '{sprint.name}'"}, [event]

        elif tool_name == "add_label":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.add_label(user, issue, params["label_id"])
            ctx.db.update_issue(issue)
            return {"message": f"Added label to '{issue.title}'"}, [event]

        elif tool_name == "approve_pr":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.approve_pr(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Approved PR for '{issue.title}'"}, [event]

        # --- 30-level tools ---
        elif tool_name == "reopen_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.transition_issue(user, issue, IssueStatus.open)
            ctx.db.update_issue(issue)
            return {"message": f"Reopened issue '{issue.title}'"}, [event]

        elif tool_name == "change_priority":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.change_priority(user, issue, Priority(params["new_priority"]))
            ctx.db.update_issue(issue)
            return {"message": f"Changed priority of '{issue.title}'"}, [event]

        elif tool_name == "link_issues":
            issue_a = ctx.db.get_issue(params["issue_id_a"])
            issue_b = ctx.db.get_issue(params["issue_id_b"])
            if not issue_a or not issue_b:
                raise DomainError("One or both issues not found.")
            event = engine.link_issues(user, issue_a, issue_b)
            ctx.db.update_issue(issue_a)
            ctx.db.update_issue(issue_b)
            return {"message": f"Linked issues"}, [event]

        elif tool_name == "unlink_issues":
            issue_a = ctx.db.get_issue(params["issue_id_a"])
            issue_b = ctx.db.get_issue(params["issue_id_b"])
            if not issue_a or not issue_b:
                raise DomainError("One or both issues not found.")
            event = engine.unlink_issues(user, issue_a, issue_b)
            ctx.db.update_issue(issue_a)
            ctx.db.update_issue(issue_b)
            return {"message": f"Unlinked issues"}, [event]

        elif tool_name == "bulk_update_issues":
            evts = []
            for iid in params["issue_ids"]:
                issue = ctx.db.get_issue(iid)
                if not issue:
                    continue
                if "priority" in params:
                    evt = engine.change_priority(user, issue, Priority(params["priority"]))
                    evts.append(evt)
                if "assignee_id" in params:
                    assignee = ctx.get_user(params["assignee_id"])
                    if assignee:
                        evt = engine.assign_issue(user, issue, assignee, ctx._user_templates)
                        evts.append(evt)
                if "status" in params:
                    evt = engine.transition_issue(user, issue, IssueStatus(params["status"]))
                    evts.append(evt)
                ctx.db.update_issue(issue)
            return {"message": f"Bulk updated {len(params['issue_ids'])} issues"}, evts

        elif tool_name == "move_issue_to_sprint":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            event = engine.move_to_sprint(user, issue, sprint)
            ctx.db.update_issue(issue)
            return {"message": f"Moved issue to sprint '{sprint.name}'"}, [event]

        elif tool_name == "remove_from_sprint":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.remove_from_sprint(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Removed issue from sprint"}, [event]

        elif tool_name == "update_sprint":
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            engine.check_can_manage(user)
            sprint.name = params["name"]
            ctx.db.update_sprint(sprint)
            from eval.backend.models import DomainEvent
            return {"message": f"Updated sprint"}, [DomainEvent(type="SprintUpdated", data={"sprint": sprint.name})]

        elif tool_name == "add_project_member":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            member = ctx.get_user(params["member_id"])
            if not member:
                raise DomainError(f"User '{params['member_id']}' not found.")
            event = engine.add_project_member(user, proj, member)
            ctx.db.update_project(proj)
            return {"message": f"Added {member.name} to '{proj.name}'"}, [event]

        elif tool_name == "remove_project_member":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            event = engine.remove_project_member(user, proj, params["member_id"])
            ctx.db.update_project(proj)
            return {"message": f"Removed member from '{proj.name}'"}, [event]

        elif tool_name == "delete_comment":
            comment = ctx.db.get_comment(params["comment_id"])
            if not comment:
                raise DomainError(f"Comment '{params['comment_id']}' not found.")
            event = engine.delete_comment(user, comment)
            ctx.db.delete_comment(comment.id)
            return {"message": f"Deleted comment"}, [event]

        elif tool_name == "update_comment":
            comment = ctx.db.get_comment(params["comment_id"])
            if not comment:
                raise DomainError(f"Comment '{params['comment_id']}' not found.")
            event = engine.update_comment(user, comment, params["body"])
            # Re-create since we don't have update_comment in DB
            ctx.db.delete_comment(comment.id)
            ctx.db.create_comment(comment)
            return {"message": f"Updated comment"}, [event]

        # --- 60-level per-field tools ---
        elif tool_name == "set_issue_title":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            engine.check_not_viewer(user)
            if issue.is_locked:
                raise DomainError("Issue is locked.")
            issue.title = params["title"]
            ctx.db.update_issue(issue)
            from eval.backend.models import DomainEvent
            return {"message": f"Updated title"}, [DomainEvent(type="IssueTitleChanged", data={"issue_id": issue.id})]

        elif tool_name == "set_issue_description":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            engine.check_not_viewer(user)
            if issue.is_locked:
                raise DomainError("Issue is locked.")
            issue.description = params["description"]
            ctx.db.update_issue(issue)
            from eval.backend.models import DomainEvent
            return {"message": f"Updated description"}, [DomainEvent(type="IssueDescriptionChanged", data={"issue_id": issue.id})]

        elif tool_name == "set_issue_priority":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.change_priority(user, issue, Priority(params["priority"]))
            ctx.db.update_issue(issue)
            return {"message": f"Set priority"}, [event]

        elif tool_name == "set_issue_assignee":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            assignee = ctx.get_user(params["assignee_id"])
            if not assignee:
                raise DomainError(f"User not found.")
            event = engine.assign_issue(user, issue, assignee, ctx._user_templates)
            ctx.db.update_issue(issue)
            return {"message": f"Set assignee"}, [event]

        elif tool_name == "set_issue_status":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.transition_issue(user, issue, IssueStatus(params["status"]))
            ctx.db.update_issue(issue)
            return {"message": f"Set status"}, [event]

        # Workflow shortcuts
        elif tool_name == "start_review":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.transition_issue(user, issue, IssueStatus.in_review)
            ctx.db.update_issue(issue)
            return {"message": f"Started review for '{issue.title}'"}, [event]

        elif tool_name == "complete_review":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.transition_issue(user, issue, IssueStatus.resolved)
            ctx.db.update_issue(issue)
            return {"message": f"Completed review for '{issue.title}'"}, [event]

        elif tool_name == "request_changes":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.transition_issue(user, issue, IssueStatus.in_progress)
            ctx.db.update_issue(issue)
            return {"message": f"Requested changes for '{issue.title}'"}, [event]

        # Bulk ops
        elif tool_name == "bulk_assign":
            evts = []
            assignee = ctx.get_user(params["assignee_id"])
            if not assignee:
                raise DomainError(f"User not found.")
            for iid in params["issue_ids"]:
                issue = ctx.db.get_issue(iid)
                if issue:
                    evt = engine.assign_issue(user, issue, assignee, ctx._user_templates)
                    ctx.db.update_issue(issue)
                    evts.append(evt)
            return {"message": f"Bulk assigned {len(params['issue_ids'])} issues"}, evts

        elif tool_name == "bulk_label":
            evts = []
            for iid in params["issue_ids"]:
                issue = ctx.db.get_issue(iid)
                if issue:
                    evt = engine.add_label(user, issue, params["label_id"])
                    ctx.db.update_issue(issue)
                    evts.append(evt)
            return {"message": f"Bulk labeled {len(params['issue_ids'])} issues"}, evts

        elif tool_name == "bulk_close":
            evts = []
            for iid in params["issue_ids"]:
                issue = ctx.db.get_issue(iid)
                if issue:
                    evt = engine.transition_issue(user, issue, IssueStatus.closed)
                    ctx.db.update_issue(issue)
                    evts.append(evt)
            return {"message": f"Bulk closed {len(params['issue_ids'])} issues"}, evts

        # Lock/unlock/activate (60-level)
        elif tool_name == "remove_label":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.remove_label(user, issue, params["label_id"])
            ctx.db.update_issue(issue)
            return {"message": f"Removed label"}, [event]

        elif tool_name == "lock_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.lock_issue(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Locked issue"}, [event]

        elif tool_name == "unlock_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue not found.")
            event = engine.unlock_issue(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Unlocked issue"}, [event]

        elif tool_name == "activate_sprint":
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint not found.")
            event = engine.activate_sprint(user, sprint)
            ctx.db.update_sprint(sprint)
            return {"message": f"Activated sprint '{sprint.name}'"}, [event]

        elif tool_name == "activate_project":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project not found.")
            event = engine.activate_project(user, proj)
            ctx.db.update_project(proj)
            return {"message": f"Activated project '{proj.name}'"}, [event]

        else:
            raise DomainError(f"Tool '{tool_name}' not implemented.")
