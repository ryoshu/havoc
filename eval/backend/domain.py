"""Domain logic — ProjectEngine for the project management eval domain."""

from __future__ import annotations

from .models import (
    CommentState,
    DomainEvent,
    IssueState,
    IssueStatus,
    Priority,
    ProjectState,
    ProjectStatus,
    SprintState,
    SprintStatus,
    UserRole,
    UserTemplate,
)


class DomainError(Exception):
    """Raised when a domain constraint is violated."""


# Valid status transitions
ISSUE_TRANSITIONS: dict[IssueStatus, list[IssueStatus]] = {
    IssueStatus.open: [IssueStatus.in_progress, IssueStatus.closed],
    IssueStatus.in_progress: [IssueStatus.in_review, IssueStatus.open],
    IssueStatus.in_review: [IssueStatus.resolved, IssueStatus.in_progress],
    IssueStatus.resolved: [IssueStatus.closed, IssueStatus.open],
    IssueStatus.closed: [IssueStatus.open],  # reopen
}


class ProjectEngine:
    """Implements project management business rules."""

    # --- Permission checks ---

    @staticmethod
    def check_not_viewer(user: UserTemplate) -> None:
        if user.role == UserRole.viewer:
            raise DomainError(f"{user.name} is a viewer and cannot modify resources.")

    @staticmethod
    def check_can_manage(user: UserTemplate) -> None:
        if user.role not in (UserRole.admin, UserRole.manager):
            raise DomainError(f"{user.name} must be admin or manager for this operation.")

    @staticmethod
    def check_admin(user: UserTemplate) -> None:
        if user.role != UserRole.admin:
            raise DomainError(f"{user.name} must be admin for this operation.")

    # --- Issue Operations ---

    @staticmethod
    def create_issue(
        user: UserTemplate,
        project: ProjectState,
        title: str,
        description: str = "",
        priority: Priority = Priority.p3,
    ) -> tuple[IssueState, DomainEvent]:
        ProjectEngine.check_not_viewer(user)

        if project.status == ProjectStatus.closed:
            raise DomainError(f"Cannot create issues in closed project '{project.name}'.")

        issue = IssueState(
            project_id=project.id,
            session_id=project.session_id,
            title=title,
            description=description,
            priority=priority,
            reporter_id=user.id,
            status=IssueStatus.open,
        )
        event = DomainEvent(
            type="IssueCreated",
            data={"title": title, "project": project.name, "reporter": user.name},
        )
        return issue, event

    @staticmethod
    def transition_issue(
        user: UserTemplate,
        issue: IssueState,
        new_status: IssueStatus,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue.is_locked:
            raise DomainError(f"Issue '{issue.title}' is locked and cannot be modified.")

        valid = ISSUE_TRANSITIONS.get(issue.status, [])
        if new_status not in valid:
            raise DomainError(
                f"Cannot transition issue from '{issue.status.value}' to '{new_status.value}'. "
                f"Valid transitions: {[s.value for s in valid]}"
            )

        old_status = issue.status
        issue.status = new_status
        return DomainEvent(
            type="IssueTransitioned",
            data={
                "issue": issue.title,
                "from": old_status.value,
                "to": new_status.value,
                "by": user.name,
            },
        )

    @staticmethod
    def assign_issue(
        user: UserTemplate,
        issue: IssueState,
        assignee: UserTemplate,
        all_users: dict[str, UserTemplate],
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue.is_locked:
            raise DomainError(f"Issue '{issue.title}' is locked and cannot be modified.")

        if assignee.id not in all_users:
            raise DomainError(f"User '{assignee.id}' does not exist.")

        if assignee.role == UserRole.viewer:
            raise DomainError(f"Cannot assign issues to viewer '{assignee.name}'.")

        issue.assignee_id = assignee.id
        return DomainEvent(
            type="IssueAssigned",
            data={"issue": issue.title, "assignee": assignee.name, "by": user.name},
        )

    @staticmethod
    def change_priority(
        user: UserTemplate,
        issue: IssueState,
        new_priority: Priority,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue.is_locked:
            raise DomainError(f"Issue '{issue.title}' is locked and cannot be modified.")

        old = issue.priority
        issue.priority = new_priority
        return DomainEvent(
            type="PriorityChanged",
            data={"issue": issue.title, "from": old.value, "to": new_priority.value},
        )

    @staticmethod
    def add_label(
        user: UserTemplate,
        issue: IssueState,
        label_id: str,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue.is_locked:
            raise DomainError(f"Issue '{issue.title}' is locked and cannot be modified.")

        if label_id in issue.labels:
            raise DomainError(f"Label '{label_id}' already on issue '{issue.title}'.")

        issue.labels.append(label_id)
        return DomainEvent(
            type="LabelAdded",
            data={"issue": issue.title, "label": label_id},
        )

    @staticmethod
    def remove_label(
        user: UserTemplate,
        issue: IssueState,
        label_id: str,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if label_id not in issue.labels:
            raise DomainError(f"Label '{label_id}' not on issue '{issue.title}'.")

        issue.labels.remove(label_id)
        return DomainEvent(
            type="LabelRemoved",
            data={"issue": issue.title, "label": label_id},
        )

    @staticmethod
    def link_issues(
        user: UserTemplate,
        issue_a: IssueState,
        issue_b: IssueState,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue_b.id in issue_a.linked_issue_ids:
            raise DomainError(f"Issues already linked.")

        issue_a.linked_issue_ids.append(issue_b.id)
        issue_b.linked_issue_ids.append(issue_a.id)
        return DomainEvent(
            type="IssuesLinked",
            data={"issue_a": issue_a.title, "issue_b": issue_b.title},
        )

    @staticmethod
    def unlink_issues(
        user: UserTemplate,
        issue_a: IssueState,
        issue_b: IssueState,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue_b.id not in issue_a.linked_issue_ids:
            raise DomainError(f"Issues are not linked.")

        issue_a.linked_issue_ids.remove(issue_b.id)
        issue_b.linked_issue_ids.remove(issue_a.id)
        return DomainEvent(
            type="IssuesUnlinked",
            data={"issue_a": issue_a.title, "issue_b": issue_b.title},
        )

    @staticmethod
    def lock_issue(
        user: UserTemplate,
        issue: IssueState,
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)
        issue.is_locked = True
        return DomainEvent(
            type="IssueLocked",
            data={"issue": issue.title, "by": user.name},
        )

    @staticmethod
    def unlock_issue(
        user: UserTemplate,
        issue: IssueState,
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)
        issue.is_locked = False
        return DomainEvent(
            type="IssueUnlocked",
            data={"issue": issue.title, "by": user.name},
        )

    @staticmethod
    def move_to_sprint(
        user: UserTemplate,
        issue: IssueState,
        sprint: SprintState,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if sprint.status == SprintStatus.closed:
            raise DomainError(f"Cannot add issues to closed sprint '{sprint.name}'.")

        if issue.is_locked:
            raise DomainError(f"Issue '{issue.title}' is locked.")

        issue.sprint_id = sprint.id
        return DomainEvent(
            type="IssueMovedToSprint",
            data={"issue": issue.title, "sprint": sprint.name},
        )

    @staticmethod
    def remove_from_sprint(
        user: UserTemplate,
        issue: IssueState,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if not issue.sprint_id:
            raise DomainError(f"Issue '{issue.title}' is not in a sprint.")

        old_sprint = issue.sprint_id
        issue.sprint_id = ""
        return DomainEvent(
            type="IssueRemovedFromSprint",
            data={"issue": issue.title, "sprint_id": old_sprint},
        )

    # --- Comment Operations ---

    @staticmethod
    def add_comment(
        user: UserTemplate,
        issue: IssueState,
        body: str,
    ) -> tuple[CommentState, DomainEvent]:
        ProjectEngine.check_not_viewer(user)

        comment = CommentState(
            session_id=issue.session_id,
            issue_id=issue.id,
            author_id=user.id,
            body=body,
        )
        event = DomainEvent(
            type="CommentAdded",
            data={"issue": issue.title, "author": user.name},
        )
        return comment, event

    @staticmethod
    def update_comment(
        user: UserTemplate,
        comment: CommentState,
        new_body: str,
    ) -> DomainEvent:
        if comment.author_id != user.id and user.role != UserRole.admin:
            raise DomainError(f"Only the author or an admin can edit this comment.")

        comment.body = new_body
        return DomainEvent(
            type="CommentUpdated",
            data={"comment_id": comment.id, "by": user.name},
        )

    @staticmethod
    def delete_comment(
        user: UserTemplate,
        comment: CommentState,
    ) -> DomainEvent:
        if comment.author_id != user.id and user.role != UserRole.admin:
            raise DomainError(f"Only the author or an admin can delete this comment.")

        return DomainEvent(
            type="CommentDeleted",
            data={"comment_id": comment.id, "by": user.name},
        )

    # --- Sprint Operations ---

    @staticmethod
    def create_sprint(
        user: UserTemplate,
        project: ProjectState,
        name: str,
    ) -> tuple[SprintState, DomainEvent]:
        ProjectEngine.check_can_manage(user)

        if project.status not in (ProjectStatus.active, ProjectStatus.setup):
            raise DomainError(
                f"Cannot create sprints in project with status '{project.status.value}'."
            )

        sprint = SprintState(
            session_id=project.session_id,
            project_id=project.id,
            name=name,
            status=SprintStatus.planning,
        )
        event = DomainEvent(
            type="SprintCreated",
            data={"sprint": name, "project": project.name},
        )
        return sprint, event

    @staticmethod
    def activate_sprint(
        user: UserTemplate,
        sprint: SprintState,
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)

        if sprint.status != SprintStatus.planning:
            raise DomainError(
                f"Sprint '{sprint.name}' must be in 'planning' to activate (is '{sprint.status.value}')."
            )

        sprint.status = SprintStatus.active
        return DomainEvent(
            type="SprintActivated",
            data={"sprint": sprint.name},
        )

    @staticmethod
    def close_sprint(
        user: UserTemplate,
        sprint: SprintState,
        sprint_issues: list[IssueState],
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)

        if sprint.status != SprintStatus.active:
            raise DomainError(
                f"Sprint '{sprint.name}' must be active to close (is '{sprint.status.value}')."
            )

        # Cannot close with open P1 issues
        open_p1 = [
            i for i in sprint_issues
            if i.priority == Priority.p1
            and i.status not in (IssueStatus.resolved, IssueStatus.closed)
        ]
        if open_p1:
            titles = [i.title for i in open_p1]
            raise DomainError(
                f"Cannot close sprint '{sprint.name}' with unresolved P1 issues: {titles}"
            )

        sprint.status = SprintStatus.closed
        return DomainEvent(
            type="SprintClosed",
            data={"sprint": sprint.name},
        )

    # --- Project Operations ---

    @staticmethod
    def activate_project(
        user: UserTemplate,
        project: ProjectState,
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)

        if project.status != ProjectStatus.setup:
            raise DomainError(
                f"Project must be in 'setup' to activate (is '{project.status.value}')."
            )

        project.status = ProjectStatus.active
        return DomainEvent(
            type="ProjectActivated",
            data={"project": project.name},
        )

    @staticmethod
    def close_project(
        user: UserTemplate,
        project: ProjectState,
        project_sprints: list[SprintState],
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)

        active_sprints = [s for s in project_sprints if s.status == SprintStatus.active]
        if active_sprints:
            names = [s.name for s in active_sprints]
            raise DomainError(
                f"Cannot close project '{project.name}' with active sprints: {names}"
            )

        project.status = ProjectStatus.closed
        return DomainEvent(
            type="ProjectClosed",
            data={"project": project.name},
        )

    @staticmethod
    def add_project_member(
        user: UserTemplate,
        project: ProjectState,
        member: UserTemplate,
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)

        if member.id in project.member_ids:
            raise DomainError(f"{member.name} is already a member of '{project.name}'.")

        project.member_ids.append(member.id)
        return DomainEvent(
            type="MemberAdded",
            data={"project": project.name, "member": member.name},
        )

    @staticmethod
    def remove_project_member(
        user: UserTemplate,
        project: ProjectState,
        member_id: str,
    ) -> DomainEvent:
        ProjectEngine.check_can_manage(user)

        if member_id not in project.member_ids:
            raise DomainError(f"User '{member_id}' is not a member of '{project.name}'.")

        project.member_ids.remove(member_id)
        return DomainEvent(
            type="MemberRemoved",
            data={"project": project.name, "member_id": member_id},
        )

    # --- PR Approval ---

    @staticmethod
    def approve_pr(
        user: UserTemplate,
        issue: IssueState,
    ) -> DomainEvent:
        ProjectEngine.check_not_viewer(user)

        if issue.status != IssueStatus.in_review:
            raise DomainError(
                f"Issue '{issue.title}' must be in_review to approve (is '{issue.status.value}')."
            )

        # Cannot self-approve
        if issue.assignee_id == user.id:
            raise DomainError(f"Cannot self-approve: {user.name} is the assignee.")

        issue.status = IssueStatus.resolved
        return DomainEvent(
            type="PRApproved",
            data={"issue": issue.title, "approver": user.name},
        )
