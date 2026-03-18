"""Context layer — composes SQLite (mutable state) + in-memory template cache."""

from __future__ import annotations

import json
from pathlib import Path

from .db import EvalDB
from .models import (
    EvalSession,
    LabelTemplate,
    ProjectState,
    ProjectStatus,
    UserTemplate,
    UserRole,
)

DATA_DIR = Path(__file__).parent.parent / "data"


class EvalContext:
    """Unified access to eval templates and mutable state."""

    def __init__(self, db_path: str = ":memory:"):
        self.db = EvalDB(db_path)

        self._user_templates: dict[str, UserTemplate] = {}
        self._project_templates: dict[str, dict] = {}
        self._label_templates: dict[str, LabelTemplate] = {}

        self._load_data()

    def _load_data(self):
        users_path = DATA_DIR / "users.json"
        if users_path.exists():
            with open(users_path) as f:
                users_data = json.load(f)
            for u in users_data:
                self._user_templates[u["id"]] = UserTemplate(**u)

        projects_path = DATA_DIR / "projects.json"
        if projects_path.exists():
            with open(projects_path) as f:
                self._project_templates = {p["id"]: p for p in json.load(f)}

        labels_path = DATA_DIR / "labels.json"
        if labels_path.exists():
            with open(labels_path) as f:
                labels_data = json.load(f)
            for lb in labels_data:
                self._label_templates[lb["id"]] = LabelTemplate(**lb)

    # --- Template Access ---

    def get_user(self, user_id: str) -> UserTemplate | None:
        return self._user_templates.get(user_id)

    def get_all_users(self) -> list[UserTemplate]:
        return list(self._user_templates.values())

    def get_label(self, label_id: str) -> LabelTemplate | None:
        return self._label_templates.get(label_id)

    def get_all_labels(self) -> list[LabelTemplate]:
        return list(self._label_templates.values())

    def get_project_template(self, project_id: str) -> dict | None:
        return self._project_templates.get(project_id)

    # --- Session Shortcuts ---

    def get_session(self, session_id: str) -> EvalSession | None:
        return self.db.get_session(session_id)

    # --- Composite: seed a project from template ---

    def create_project_from_template(
        self, session_id: str, template_id: str, project_id: str = ""
    ) -> ProjectState:
        tmpl = self._project_templates.get(template_id)
        if not tmpl:
            raise ValueError(f"Project template '{template_id}' not found.")

        project = ProjectState(
            session_id=session_id,
            template_id=template_id,
            name=tmpl["name"],
            description=tmpl.get("description", ""),
            status=ProjectStatus(tmpl.get("status", "setup")),
            owner_id=tmpl.get("owner_id", ""),
            member_ids=list(tmpl.get("member_ids", [])),
        )
        if project_id:
            project.id = project_id
        return self.db.create_project(project)
