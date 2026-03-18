"""Pydantic models for the project management eval domain."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# --- Enums ---

class IssueStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    in_review = "in_review"
    resolved = "resolved"
    closed = "closed"


class SprintStatus(str, Enum):
    planning = "planning"
    active = "active"
    closed = "closed"


class ProjectStatus(str, Enum):
    setup = "setup"
    active = "active"
    review = "review"
    closed = "closed"


class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    developer = "developer"
    viewer = "viewer"


class Priority(str, Enum):
    p1 = "p1"
    p2 = "p2"
    p3 = "p3"
    p4 = "p4"


# --- Templates (immutable, from JSON) ---

class UserTemplate(BaseModel):
    id: str
    name: str
    email: str
    role: UserRole


class ProjectTemplate(BaseModel):
    id: str
    name: str
    description: str
    status: ProjectStatus = ProjectStatus.setup
    owner_id: str = ""


class LabelTemplate(BaseModel):
    id: str
    name: str
    color: str = ""
    description: str = ""


# --- Mutable State Models (stored in SQLite) ---

class IssueState(BaseModel):
    id: str = ""
    session_id: str = ""
    project_id: str = ""
    title: str = ""
    description: str = ""
    status: IssueStatus = IssueStatus.open
    priority: Priority = Priority.p3
    assignee_id: str = ""
    reporter_id: str = ""
    sprint_id: str = ""
    labels: list[str] = Field(default_factory=list)
    linked_issue_ids: list[str] = Field(default_factory=list)
    is_locked: bool = False
    created_at: str = ""
    updated_at: str = ""


class SprintState(BaseModel):
    id: str = ""
    session_id: str = ""
    project_id: str = ""
    name: str = ""
    status: SprintStatus = SprintStatus.planning
    created_at: str = ""


class ProjectState(BaseModel):
    id: str = ""
    session_id: str = ""
    template_id: str = ""
    name: str = ""
    description: str = ""
    status: ProjectStatus = ProjectStatus.setup
    owner_id: str = ""
    member_ids: list[str] = Field(default_factory=list)
    created_at: str = ""


class CommentState(BaseModel):
    id: str = ""
    session_id: str = ""
    issue_id: str = ""
    author_id: str = ""
    body: str = ""
    created_at: str = ""


class EvalSession(BaseModel):
    id: str = ""
    acting_user_id: str = ""
    created_at: str = ""


# --- Affordance Model (same structure as GIA) ---

class Affordance(BaseModel):
    action: str
    description: str
    schema_: dict = Field(default_factory=dict, alias="schema")
    constraints: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# --- Domain Events ---

class DomainEvent(BaseModel):
    type: str
    data: dict = Field(default_factory=dict)


# --- Decision Records (reasoning traces) ---

class DecisionRecord(BaseModel):
    id: str = ""
    session_id: str = ""
    actor_id: str = ""
    actor_name: str = ""
    action: str = ""
    params: dict = Field(default_factory=dict)
    affordances_snapshot: list[dict] = Field(default_factory=list)
    affordances_not_taken: list[str] = Field(default_factory=list)
    result_summary: str = ""
    events: list[dict] = Field(default_factory=list)
    was_valid: bool = True
    error_message: str = ""
    timestamp: str = ""
