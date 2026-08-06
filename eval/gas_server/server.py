"""GAS server — 3 generic tools (get, search, act) for the project management eval."""

from __future__ import annotations

import json

from eval.backend.context import EvalContext
from eval.backend.domain import DomainError, ProjectEngine
from eval.backend.models import (
    Affordance,
    DecisionRecord,
    IssueStatus,
    Priority,
    SprintStatus,
)

from .affordances import compute_affordances
from .contracts import EnforcedGasMixin


def _compact_affordances(affordances: list[Affordance]) -> list[dict]:
    """Compact affordances by grouping per action type.

    Instead of N per-entity entries with repeated schemas, produces one entry
    per action type with a ``targets`` list of applicable entity IDs and a
    shared ``params`` dict for non-const parameters.

    Singleton affordances (only one instance of an action) are emitted inline
    without a ``targets`` wrapper.
    """
    from collections import OrderedDict

    groups: OrderedDict[str, list[Affordance]] = OrderedDict()
    for a in affordances:
        groups.setdefault(a.action, []).append(a)

    result: list[dict] = []
    for action, items in groups.items():
        if len(items) == 1:
            # Singleton — emit inline (no batching overhead)
            a = items[0]
            entry: dict = {"action": a.action, "description": a.description}
            if a.schema_:
                entry["params"] = _simplify_schema(a.schema_)
            if a.constraints:
                entry["constraints"] = a.constraints
            result.append(entry)
            continue

        # Multiple instances — batch by action type.
        # Separate const params (vary per entity) from shared params (same across all).
        const_keys: list[str] = []
        shared_params: dict = {}
        sample = items[0].schema_

        for key, spec in sample.items():
            if isinstance(spec, dict) and "const" in spec:
                const_keys.append(key)
            else:
                shared_params[key] = _simplify_param(spec)

        entry = {"action": action}

        # Build compact targets list
        targets: list[dict] = []
        for a in items:
            target: dict = {}
            for ck in const_keys:
                target[ck] = a.schema_[ck]["const"]
            # Include per-entity description as label
            target["_desc"] = a.description
            # Per-entity enum overrides (e.g., transition_issue where valid
            # new_status differs per issue)
            for key, spec in a.schema_.items():
                if key in const_keys:
                    continue
                if isinstance(spec, dict) and "enum" in spec:
                    shared_val = sample.get(key, {})
                    if isinstance(shared_val, dict) and spec.get("enum") != shared_val.get("enum"):
                        target[key] = spec["enum"]
            if a.constraints:
                target["constraints"] = a.constraints
            targets.append(target)

        # Merge targets sharing the same primary entity key.
        # e.g., two transition_issue entries for the same issue_id with
        # different new_status values collapse into one target with a list.
        if len(const_keys) > 1:
            primary = const_keys[0]  # e.g., issue_id
            merged: OrderedDict[str, dict] = OrderedDict()
            for t in targets:
                pk = t[primary]
                if pk not in merged:
                    merged[pk] = dict(t)
                else:
                    # Merge the non-primary const values into lists
                    existing = merged[pk]
                    for ck in const_keys[1:]:
                        old_val = existing.get(ck)
                        new_val = t.get(ck)
                        if old_val is None:
                            existing[ck] = new_val
                        elif isinstance(old_val, list):
                            existing[ck].append(new_val)
                        else:
                            existing[ck] = [old_val, new_val]
                    # Merge descriptions
                    if "_desc" in t:
                        old_desc = existing.get("_desc", "")
                        if isinstance(old_desc, list):
                            old_desc.append(t["_desc"])
                        else:
                            existing["_desc"] = [old_desc, t["_desc"]]
            targets = list(merged.values())

        entry["targets"] = targets
        if shared_params:
            entry["params"] = shared_params
        result.append(entry)

    return result


def _simplify_schema(schema: dict) -> dict:
    """Simplify a parameter schema by stripping redundant JSON Schema wrappers."""
    out = {}
    for key, spec in schema.items():
        out[key] = _simplify_param(spec)
    return out


def _simplify_param(spec) -> str | list | dict:
    """Collapse ``{"type": "string", "const": "x"}`` → ``"x"`` etc."""
    if not isinstance(spec, dict):
        return spec
    if "const" in spec:
        return spec["const"]
    if "enum" in spec:
        return spec["enum"]
    if spec.get("type") == "object" and "properties" in spec:
        return {k: _simplify_param(v) for k, v in spec["properties"].items()}
    if spec.get("type") == "string":
        return "string"
    return spec


class EvalRuntime(EnforcedGasMixin):
    """Encapsulates eval state for a single runtime instance."""

    def __init__(
        self,
        db_path: str = ":memory:",
        mode: str = "gas-advisory",
        *,
        advertise_capabilities: bool | None = None,
    ):
        self.ctx = EvalContext(db_path=db_path)
        self.engine = ProjectEngine()
        self.mode = mode
        # The generic PR12 condition intentionally keeps the same runtime and
        # command registry while withholding the affordance projection.
        self.advertise_capabilities = (
            mode != "gas-generic" if advertise_capabilities is None else advertise_capabilities
        )
        self._contract_revisions: dict[str, int] = {}
        self.default_session_id: str = ""

    def _contract_affordances(self, session_id: str):
        return compute_affordances(self.ctx, session_id)

    def create_session(self, acting_user_id: str) -> str:
        session = self.ctx.db.create_session(acting_user_id=acting_user_id)
        if not self.default_session_id:
            self.default_session_id = session.id
        return session.id

    def _sid(self, session_id: str) -> str:
        return session_id or self.default_session_id

    def _format(self, data, affordances) -> dict:
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        response = {"data": data}
        if self.advertise_capabilities:
            response["affordances"] = _compact_affordances(affordances)
        return response

    # --- get ---

    def get(self, resource_type: str, id: str = "", session_id: str = "") -> str:
        sid = self._sid(session_id)
        try:
            if resource_type == "issue":
                issue = self.ctx.db.get_issue(id)
                if not issue:
                    return json.dumps({"error": f"Issue '{id}' not found"})
                comments = self.ctx.db.get_issue_comments(id)
                data = {**issue.model_dump(), "comments": [c.model_dump() for c in comments]}
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "project":
                proj = self.ctx.db.get_project(id)
                if not proj:
                    return json.dumps({"error": f"Project '{id}' not found"})
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(proj, affs), indent=2)

            elif resource_type == "sprint":
                sprint = self.ctx.db.get_sprint(id)
                if not sprint:
                    return json.dumps({"error": f"Sprint '{id}' not found"})
                sprint_issues = self.ctx.db.get_sprint_issues(sprint.id)
                data = {
                    **sprint.model_dump(),
                    "issues": [{"id": i.id, "title": i.title, "status": i.status.value}
                               for i in sprint_issues],
                }
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "user":
                user = self.ctx.get_user(id)
                if not user:
                    return json.dumps({"error": f"User '{id}' not found"})
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(user, affs), indent=2)

            elif resource_type == "comment":
                comment = self.ctx.db.get_comment(id)
                if not comment:
                    return json.dumps({"error": f"Comment '{id}' not found"})
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(comment, affs), indent=2)

            elif resource_type == "session":
                session = self.ctx.get_session(id or sid)
                if not session:
                    return json.dumps({"error": f"Session '{id or sid}' not found"})
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(session, affs), indent=2)

            else:
                return json.dumps({"error": f"Unknown resource type: {resource_type}"})

        except Exception as e:
            return json.dumps({"error": str(e)})

    # --- search ---

    def search(self, resource_type: str, filters: str = "{}", session_id: str = "") -> str:
        sid = self._sid(session_id)
        try:
            parsed = json.loads(filters) if isinstance(filters, str) else filters
        except json.JSONDecodeError:
            parsed = {}

        try:
            if resource_type == "issues":
                results = self.ctx.db.search_issues(sid, parsed)
                data = [
                    {"id": i.id, "title": i.title, "status": i.status.value,
                     "priority": i.priority.value, "assignee_id": i.assignee_id}
                    for i in results
                ]
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "projects":
                results = self.ctx.db.get_session_projects(sid)
                data = [
                    {"id": p.id, "name": p.name, "status": p.status.value}
                    for p in results
                ]
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "sprints":
                results = self.ctx.db.get_session_sprints(sid)
                if "project_id" in parsed:
                    results = [s for s in results if s.project_id == parsed["project_id"]]
                data = [
                    {"id": s.id, "name": s.name, "status": s.status.value,
                     "project_id": s.project_id}
                    for s in results
                ]
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "users":
                results = self.ctx.get_all_users()
                if "role" in parsed:
                    results = [u for u in results if u.role.value == parsed["role"]]
                data = [
                    {"id": u.id, "name": u.name, "role": u.role.value}
                    for u in results
                ]
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            elif resource_type == "comments":
                results = self.ctx.db.search_comments(sid, parsed)
                data = [
                    {"id": c.id, "issue_id": c.issue_id, "author_id": c.author_id,
                     "body": c.body[:100]}
                    for c in results
                ]
                affs = compute_affordances(self.ctx, sid)
                return json.dumps(self._format(data, affs), indent=2)

            else:
                return json.dumps({"error": f"Unknown search type: {resource_type}"})

        except Exception as e:
            return json.dumps({"error": str(e)})

    # --- act ---

    def act(self, action: str, params: str = "{}", session_id: str = "") -> str:
        sid = self._sid(session_id)
        try:
            parsed = json.loads(params) if isinstance(params, str) else params
        except json.JSONDecodeError:
            parsed = {}

        session = self.ctx.get_session(sid)
        if not session:
            return json.dumps({"error": f"Session '{sid}' not found"})

        user = self.ctx.get_user(session.acting_user_id)
        if not user:
            return json.dumps({"error": f"Acting user '{session.acting_user_id}' not found"})

        # Snapshot affordances before action
        pre_affordances = compute_affordances(self.ctx, sid)
        affordances_snapshot = [
            {"action": a.action, "description": a.description}
            for a in pre_affordances
        ]
        affordances_not_taken = [
            a.action for a in pre_affordances if a.action != action
        ]

        try:
            result, events = self._dispatch(sid, action, parsed, user)

            decision = DecisionRecord(
                session_id=sid,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                result_summary=str(result.get("message", ""))[:200] if isinstance(result, dict) else "",
                events=[e.model_dump() for e in events],
                was_valid=True,
            )
            self.ctx.db.record_decision(decision)

            affs = compute_affordances(self.ctx, sid)
            response = self._format(result, affs)
            if events:
                response["events"] = [e.model_dump() for e in events]
            return json.dumps(response, indent=2)

        except DomainError as e:
            decision = DecisionRecord(
                session_id=sid,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                was_valid=False,
                error_message=str(e),
            )
            self.ctx.db.record_decision(decision)

            affs = compute_affordances(self.ctx, sid)
            response = {"error": str(e)}
            if self.advertise_capabilities:
                response["affordances"] = _compact_affordances(affs)
            return json.dumps(response, indent=2)
        except Exception as e:
            decision = DecisionRecord(
                session_id=sid,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                params=parsed,
                affordances_snapshot=affordances_snapshot,
                affordances_not_taken=list(set(affordances_not_taken)),
                was_valid=False,
                error_message=f"Runtime error: {e}",
            )
            self.ctx.db.record_decision(decision)

            affs = compute_affordances(self.ctx, sid)
            response = {"error": f"Runtime error: {e}"}
            if self.advertise_capabilities:
                response["affordances"] = _compact_affordances(affs)
            return json.dumps(response, indent=2)

    def _dispatch(self, session_id, action, params, user):
        ctx = self.ctx
        engine = self.engine
        events = []

        # --- Issue actions ---
        if action == "create_issue":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            priority = Priority(params.get("priority", "p3"))
            issue, event = engine.create_issue(
                user, proj, params["title"],
                params.get("description", ""), priority,
            )
            issue = ctx.db.create_issue(issue)
            return {"message": f"Created issue '{issue.title}'", "issue_id": issue.id}, [event]

        elif action == "transition_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            new_status = IssueStatus(params["new_status"])
            event = engine.transition_issue(user, issue, new_status)
            ctx.db.update_issue(issue)
            return {"message": f"Issue '{issue.title}' → {new_status.value}"}, [event]

        elif action == "assign_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            assignee = ctx.get_user(params["assignee_id"])
            if not assignee:
                raise DomainError(f"User '{params['assignee_id']}' not found.")
            event = engine.assign_issue(user, issue, assignee, ctx._user_templates)
            ctx.db.update_issue(issue)
            return {"message": f"Assigned '{issue.title}' to {assignee.name}"}, [event]

        elif action == "change_priority":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            new_priority = Priority(params["new_priority"])
            event = engine.change_priority(user, issue, new_priority)
            ctx.db.update_issue(issue)
            return {"message": f"Changed '{issue.title}' priority to {new_priority.value}"}, [event]

        elif action == "add_label":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.add_label(user, issue, params["label_id"])
            ctx.db.update_issue(issue)
            return {"message": f"Added label '{params['label_id']}' to '{issue.title}'"}, [event]

        elif action == "remove_label":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.remove_label(user, issue, params["label_id"])
            ctx.db.update_issue(issue)
            return {"message": f"Removed label from '{issue.title}'"}, [event]

        elif action == "add_comment":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            comment, event = engine.add_comment(user, issue, params["body"])
            comment = ctx.db.create_comment(comment)
            return {"message": f"Added comment to '{issue.title}'", "comment_id": comment.id}, [event]

        elif action == "move_to_sprint":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            event = engine.move_to_sprint(user, issue, sprint)
            ctx.db.update_issue(issue)
            return {"message": f"Moved '{issue.title}' to sprint '{sprint.name}'"}, [event]

        elif action == "remove_from_sprint":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.remove_from_sprint(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Removed '{issue.title}' from sprint"}, [event]

        elif action == "link_issues":
            issue_a = ctx.db.get_issue(params["issue_id_a"])
            issue_b = ctx.db.get_issue(params["issue_id_b"])
            if not issue_a or not issue_b:
                raise DomainError("One or both issues not found.")
            event = engine.link_issues(user, issue_a, issue_b)
            ctx.db.update_issue(issue_a)
            ctx.db.update_issue(issue_b)
            return {"message": f"Linked '{issue_a.title}' ↔ '{issue_b.title}'"}, [event]

        elif action == "lock_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.lock_issue(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Locked issue '{issue.title}'"}, [event]

        elif action == "unlock_issue":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.unlock_issue(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Unlocked issue '{issue.title}'"}, [event]

        elif action == "approve_pr":
            issue = ctx.db.get_issue(params["issue_id"])
            if not issue:
                raise DomainError(f"Issue '{params['issue_id']}' not found.")
            event = engine.approve_pr(user, issue)
            ctx.db.update_issue(issue)
            return {"message": f"Approved PR for '{issue.title}'"}, [event]

        # --- Sprint actions ---
        elif action == "create_sprint":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            sprint, event = engine.create_sprint(user, proj, params["name"])
            sprint = ctx.db.create_sprint(sprint)
            return {"message": f"Created sprint '{sprint.name}'", "sprint_id": sprint.id}, [event]

        elif action == "activate_sprint":
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            event = engine.activate_sprint(user, sprint)
            ctx.db.update_sprint(sprint)
            return {"message": f"Activated sprint '{sprint.name}'"}, [event]

        elif action == "close_sprint":
            sprint = ctx.db.get_sprint(params["sprint_id"])
            if not sprint:
                raise DomainError(f"Sprint '{params['sprint_id']}' not found.")
            sprint_issues = ctx.db.get_sprint_issues(sprint.id)
            event = engine.close_sprint(user, sprint, sprint_issues)
            ctx.db.update_sprint(sprint)
            return {"message": f"Closed sprint '{sprint.name}'"}, [event]

        # --- Project actions ---
        elif action == "activate_project":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            event = engine.activate_project(user, proj)
            ctx.db.update_project(proj)
            return {"message": f"Activated project '{proj.name}'"}, [event]

        elif action == "close_project":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            proj_sprints = ctx.db.get_project_sprints(proj.id)
            event = engine.close_project(user, proj, proj_sprints)
            ctx.db.update_project(proj)
            return {"message": f"Closed project '{proj.name}'"}, [event]

        elif action == "add_project_member":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            member = ctx.get_user(params["member_id"])
            if not member:
                raise DomainError(f"User '{params['member_id']}' not found.")
            event = engine.add_project_member(user, proj, member)
            ctx.db.update_project(proj)
            return {"message": f"Added {member.name} to '{proj.name}'"}, [event]

        elif action == "remove_project_member":
            proj = ctx.db.get_project(params["project_id"])
            if not proj:
                raise DomainError(f"Project '{params['project_id']}' not found.")
            event = engine.remove_project_member(user, proj, params["member_id"])
            ctx.db.update_project(proj)
            return {"message": f"Removed member from '{proj.name}'"}, [event]

        else:
            raise DomainError(f"Unknown action: {action}")
