"""Context layer — composes SQLite (mutable state) + in-memory template cache."""

from __future__ import annotations

import json
from pathlib import Path

from .db import CruiseDB
from .models import (
    CabinTypeTemplate,
    CruiseSession,
    CruiseState,
    CruiseStatus,
    CruiseTemplate,
    CruiseUserTemplate,
    CruiseRole,
)

DATA_DIR = Path(__file__).parent.parent / "cruise_data"


class CruiseContext:
    """Unified access to cruise templates and mutable state."""

    def __init__(self, db_path: str = ":memory:"):
        self.db = CruiseDB(db_path)

        self._user_templates: dict[str, CruiseUserTemplate] = {}
        self._cruise_templates: dict[str, CruiseTemplate] = {}
        self._cabin_type_templates: dict[str, CabinTypeTemplate] = {}

        self._load_data()

    def _load_data(self):
        users_path = DATA_DIR / "users.json"
        if users_path.exists():
            with open(users_path) as f:
                users_data = json.load(f)
            for u in users_data:
                self._user_templates[u["id"]] = CruiseUserTemplate(**u)

        cruises_path = DATA_DIR / "cruises.json"
        if cruises_path.exists():
            with open(cruises_path) as f:
                cruises_data = json.load(f)
            for c in cruises_data:
                cruise_tmpl = CruiseTemplate(**c)
                self._cruise_templates[cruise_tmpl.id] = cruise_tmpl
                for ct in cruise_tmpl.cabin_types:
                    self._cabin_type_templates[ct.id] = ct

    # --- Template Access ---

    def get_user(self, user_id: str) -> CruiseUserTemplate | None:
        return self._user_templates.get(user_id)

    def get_all_users(self) -> list[CruiseUserTemplate]:
        return list(self._user_templates.values())

    def get_cruise_template(self, cruise_id: str) -> CruiseTemplate | None:
        return self._cruise_templates.get(cruise_id)

    def get_cabin_type(self, cabin_type_id: str) -> CabinTypeTemplate | None:
        return self._cabin_type_templates.get(cabin_type_id)

    def get_cabin_types_for_cruise(self, cruise_id: str) -> list[CabinTypeTemplate]:
        tmpl = self._cruise_templates.get(cruise_id)
        if not tmpl:
            return []
        return list(tmpl.cabin_types)

    # --- Session Shortcuts ---

    def get_session(self, session_id: str) -> CruiseSession | None:
        return self.db.get_session(session_id)

    # --- Composite: seed a cruise from template ---

    def create_cruise_from_template(
        self, session_id: str, template_id: str, cruise_id: str = ""
    ) -> CruiseState:
        tmpl = self._cruise_templates.get(template_id)
        if not tmpl:
            raise ValueError(f"Cruise template '{template_id}' not found.")

        cruise = CruiseState(
            session_id=session_id,
            template_id=template_id,
            name=tmpl.name,
            ship=tmpl.ship,
            departure_date=tmpl.departure_date,
            status=CruiseStatus(tmpl.status.value),
        )
        if cruise_id:
            cruise.id = cruise_id
        return self.db.create_cruise(cruise)
