"""Context layer — composes SQLite (mutable state) + in-memory template cache."""

from __future__ import annotations

import json
from pathlib import Path

from .db import AutoDB
from .models import (
    AutoSession,
    AutoUserTemplate,
    AutoRole,
    VehicleState,
    VehicleStatus,
    VehicleTemplate,
)

DATA_DIR = Path(__file__).parent.parent / "auto_data"


class AutoContext:
    """Unified access to automotive templates and mutable state."""

    def __init__(self, db_path: str = ":memory:"):
        self.db = AutoDB(db_path)

        self._user_templates: dict[str, AutoUserTemplate] = {}
        self._vehicle_templates: dict[str, VehicleTemplate] = {}

        self._load_data()

    def _load_data(self):
        users_path = DATA_DIR / "users.json"
        if users_path.exists():
            with open(users_path) as f:
                users_data = json.load(f)
            for u in users_data:
                self._user_templates[u["id"]] = AutoUserTemplate(**u)

        vehicles_path = DATA_DIR / "vehicles.json"
        if vehicles_path.exists():
            with open(vehicles_path) as f:
                vehicles_data = json.load(f)
            for v in vehicles_data:
                self._vehicle_templates[v["id"]] = VehicleTemplate(**v)

    # --- Template Access ---

    def get_user(self, user_id: str) -> AutoUserTemplate | None:
        return self._user_templates.get(user_id)

    def get_all_users(self) -> list[AutoUserTemplate]:
        return list(self._user_templates.values())

    def get_vehicle_template(self, template_id: str) -> VehicleTemplate | None:
        return self._vehicle_templates.get(template_id)

    def get_all_vehicle_templates(self) -> list[VehicleTemplate]:
        return list(self._vehicle_templates.values())

    # --- Session Shortcuts ---

    def get_session(self, session_id: str) -> AutoSession | None:
        return self.db.get_session(session_id)

    # --- Composite: seed a vehicle from template ---

    def create_vehicle_from_template(
        self, session_id: str, template_id: str, vehicle_id: str = ""
    ) -> VehicleState:
        tmpl = self._vehicle_templates.get(template_id)
        if not tmpl:
            raise ValueError(f"Vehicle template '{template_id}' not found.")

        vehicle = VehicleState(
            session_id=session_id,
            template_id=template_id,
            make=tmpl.make,
            model=tmpl.model,
            year=tmpl.year,
            trim=tmpl.trim,
            vin=tmpl.vin,
            color=tmpl.color,
            msrp=tmpl.msrp,
            invoice_price=tmpl.invoice_price,
            mileage=tmpl.mileage,
            condition=tmpl.condition,
            status=VehicleStatus.available,
            features=list(tmpl.features),
        )
        if vehicle_id:
            vehicle.id = vehicle_id
        return self.db.create_vehicle(vehicle)
