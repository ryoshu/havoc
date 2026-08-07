"""Context layer — composes SQLite (mutable state) + Oxigraph (immutable knowledge)."""

from __future__ import annotations

import json
from pathlib import Path

from gia.policy import (
    Actor,
    DeterministicPolicyProvider,
    PolicyProvider,
    RequestContext,
    Scope,
)
from havoc_domain.db import GameDB
from havoc_domain.graph import GameGraph
from havoc_domain.models import (
    CharacterState,
    CharacterTemplate,
    EnemyTemplate,
    EquipmentState,
    EquipmentTemplate,
    GameSession,
    InjurySlotTemplate,
    InjuryState,
    LocationTemplate,
    ObjectiveState,
    ObjectiveTemplate,
    SceneState,
    ThreatState,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "etr.ttl"


class GameContext:
    """Unified access to game knowledge (graph) and mutable state (db)."""

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        policy_provider: PolicyProvider | None = None,
    ):
        self.db = GameDB(db_path)
        self.graph = GameGraph()
        self.policy_provider = policy_provider or DeterministicPolicyProvider()

        # Load templates from JSON (faster than round-tripping through SPARQL)
        (
            self._char_templates,
            self._enemy_templates,
            self._location_templates,
        ) = self._load_data()

    def _load_data(self, graph: GameGraph | None = None):
        """Load immutable vocabulary/knowledge into ``graph``.

        Returning fresh template maps makes graph rebuilds transactional from
        the context's perspective: a malformed import leaves the current
        graph and template view untouched.
        """
        graph = graph or self.graph
        char_templates: dict[str, CharacterTemplate] = {}
        enemy_templates: dict[str, EnemyTemplate] = {}
        location_templates: dict[str, LocationTemplate] = {}

        # Load ontology + imported knowledge into the selected graph.
        if ONTOLOGY_PATH.exists():
            graph.load_ttl(ONTOLOGY_PATH)

        # Load and parse JSON templates
        chars_path = DATA_DIR / "characters.json"
        if chars_path.exists():
            with open(chars_path) as f:
                chars_data = json.load(f)
            graph.load_characters(chars_data)
            for c in chars_data:
                injuries = {}
                for cat, inj in c.get("injuries", {}).items():
                    injuries[cat] = InjurySlotTemplate(
                        category=cat, minor=inj["minor"],
                        major=inj["major"], major_penalty=inj["major_penalty"],
                    )
                char_templates[c["id"]] = CharacterTemplate(
                    id=c["id"], name=c["name"], description=c["description"],
                    hooks=c.get("hooks", []),
                    stats=c["stats"],
                    abilities=[
                        # Use model_validate to handle nested dicts
                        type(EquipmentTemplate)(**{}) or ab
                        for ab in []
                    ] if False else c.get("abilities", []),
                    advances=c.get("advances", []),
                    equipment=[EquipmentTemplate(**eq) for eq in c.get("equipment", [])],
                    injuries=injuries,
                    last_stand=c.get("last_stand", ""),
                    starting_blood=c.get("starting_blood", 0),
                )

        enemies_path = DATA_DIR / "enemies.json"
        if enemies_path.exists():
            with open(enemies_path) as f:
                enemies_data = json.load(f)
            graph.load_enemies(enemies_data)
            for e in enemies_data:
                enemy_templates[e["id"]] = EnemyTemplate(**e)

        locations_path = DATA_DIR / "locations.json"
        if locations_path.exists():
            with open(locations_path) as f:
                locations_data = json.load(f)
            graph.load_locations(locations_data)
            for loc in locations_data:
                location_templates[loc["id"]] = LocationTemplate(**loc)

        return char_templates, enemy_templates, location_templates

    def rebuild_graph(self) -> GameGraph:
        """Rebuild the read model from ontology, imports, and SQLite records.

        The new graph is validated before it replaces the active graph.  No
        command, policy, or transaction consults the graph, so a failed
        rebuild cannot create a partial domain commit.
        """
        rebuilt = GameGraph()
        templates = self._load_data(rebuilt)
        for session in self.db.get_all_sessions():
            decisions = self.db.get_session_provenance(session.id)
            if decisions:
                rebuilt.load_decisions(decisions)
        rebuilt.validate_shacl().raise_if_invalid()
        self.graph = rebuilt
        (
            self._char_templates,
            self._enemy_templates,
            self._location_templates,
        ) = templates
        return rebuilt

    rebuild_graph_from_authority = rebuild_graph

    def project_pending_graph(self, *, limit: int = 100) -> int:
        """Apply committed outbox records to the eventually-consistent graph.

        The event is marked published only after its provenance record has
        been projected and shape-validated.  Retrying an event is safe because
        RDF insertion is idempotent; a graph failure leaves the outbox row
        pending for retry or a full rebuild.
        """
        projected = 0
        for event in self.db.get_projection_outbox(limit=limit):
            request_id = event["payload"].get("request_id")
            if not request_id:
                raise ValueError(f"Projection event {event['id']} has no request_id")
            decision = self.db.get_provenance(request_id)
            if decision is None:
                raise ValueError(
                    f"Projection event {event['id']} references missing provenance"
                )
            self.graph.load_decisions([decision])
            self.graph.validate_shacl().raise_if_invalid()
            self.db.mark_projection_published(event["id"])
            projected += 1
        return projected

    publish_pending_graph = project_pending_graph

    # --- Template Access ---

    def get_character_template(self, template_id: str) -> CharacterTemplate | None:
        return self._char_templates.get(template_id)

    def get_all_character_templates(self) -> list[CharacterTemplate]:
        return list(self._char_templates.values())

    def get_enemy_template(self, enemy_id: str) -> EnemyTemplate | None:
        return self._enemy_templates.get(enemy_id)

    def get_location_template(self, location_id: str) -> LocationTemplate | None:
        return self._location_templates.get(location_id)

    def get_all_locations(self) -> list[LocationTemplate]:
        return list(self._location_templates.values())

    def get_connected_locations(self, location_id: str) -> list[LocationTemplate]:
        loc = self._location_templates.get(location_id)
        if not loc:
            return []
        return [
            self._location_templates[cid]
            for cid in loc.connections
            if cid in self._location_templates
        ]

    # --- Session Shortcuts ---

    def get_session(self, session_id: str) -> GameSession | None:
        return self.db.get_session(session_id)

    def get_active_scene(self, session_id: str) -> SceneState | None:
        return self.db.get_active_scene(session_id)

    # --- Composite Queries ---

    def get_character_sheet(self, char_id: str) -> dict | None:
        """Full character sheet: template data + current state."""
        state = self.db.get_character(char_id)
        if not state:
            return None
        template = self._char_templates.get(state.template_id)
        if not template:
            return None

        # Compute effective stats (apply injury penalties)
        effective_stats = dict(template.stats)
        for inj in state.injuries:
            if inj.major_marked:
                cat = inj.category
                slot = template.injuries.get(cat)
                if slot:
                    penalty = slot.major_penalty
                    if "-1 to all stats" in penalty:
                        effective_stats = {k: max(0, v - 1) for k, v in effective_stats.items()}
                    elif "+" in penalty and "-" in penalty:
                        # Parse "+2 STAT, -2 STAT" patterns
                        import re
                        for m in re.finditer(r'([+-]\d+)\s+(\w+)', penalty):
                            mod, stat = int(m.group(1)), m.group(2).lower()
                            if stat in effective_stats:
                                effective_stats[stat] = max(0, effective_stats[stat] + mod)

        return {
            "template": template.model_dump(),
            "state": state.model_dump(),
            "effective_stats": effective_stats,
            "injury_count": sum(
                (1 if i.minor_marked else 0) + (1 if i.major_marked else 0)
                for i in state.injuries
            ),
            "max_injuries": 6,
        }

    def create_character_state(self, session_id: str, template_id: str) -> CharacterState:
        """Create mutable character state from a template."""
        template = self._char_templates[template_id]
        equipment = [
            EquipmentState(
                name=eq.name,
                uses_remaining=eq.max_uses,
                bonus_condition=eq.bonus_condition,
                bonus_dice=eq.bonus_dice,
            )
            for eq in template.equipment
        ]
        injuries = [
            InjuryState(category=cat)
            for cat in ("1-2", "3-4", "5-6")
        ]
        cs = CharacterState(
            id="",
            session_id=session_id,
            template_id=template_id,
            name=template.name,
            blood=template.starting_blood,
            injuries=injuries,
            equipment=equipment,
        )
        return self.db.add_character(cs)

    def create_scene_from_location(self, session_id: str, location_id: str) -> SceneState:
        """Create a scene with threats and objectives from a location template."""
        loc = self._location_templates[location_id]

        threats = []
        for enemy_id in loc.enemies:
            enemy = self._enemy_templates.get(enemy_id)
            if enemy:
                threats.append(ThreatState(
                    enemy_id=enemy_id,
                    name=enemy.name,
                    current_rating=enemy.threat,
                    current_attack=enemy.attack,
                    base_attack=enemy.attack,
                    challenge=enemy.challenge,
                ))

        objectives = [
            ObjectiveState(
                name=loc.objective.name,
                current_rating=loc.objective.rating,
                challenge=loc.objective.challenge,
            )
        ]

        return self.db.create_scene(session_id, location_id, threats, objectives)
