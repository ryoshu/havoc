"""Pydantic models for the Eat the Reich TTRPG domain (PR 18).

Moved here from ``src/gia/models.py`` — these are the concrete Havoc game
types (phases, stats, templates, mutable state). ``Affordance`` and
``DomainEvent`` stay in ``gia_core.contracts`` (PR 14); they never
referenced a Havoc concept. ``src/gia/models.py`` re-exports both this
module's names and ``gia_core.contracts``'s for backward compatibility.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field

from gia_core.provenance.models import DecisionProvenance, DecisionRecord


# --- Enums ---

class GamePhase(str, Enum):
    setup = "setup"
    exploration = "exploration"
    engagement_pre_roll = "engagement_pre_roll"
    engagement_post_roll = "engagement_post_roll"
    between_scenes = "between_scenes"
    downed = "downed"
    last_stand = "last_stand"
    mission_complete = "mission_complete"


class Stat(str, Enum):
    brawl = "brawl"
    con = "con"
    fix = "fix"
    search = "search"
    shoot = "shoot"
    sneak = "sneak"
    terrify = "terrify"


class DiceAllocation(str, Enum):
    objective = "objective"
    threat = "threat"
    defense = "defense"
    feed = "feed"
    special = "special"


# --- Template / Immutable Models (loaded from JSON / graph) ---

class AbilityTemplate(BaseModel):
    name: str
    description: str
    cost: int = 0
    bonus_condition: str | None = None
    bonus_dice: int = 0
    special: str | None = None


class AdvanceTemplate(BaseModel):
    name: str
    description: str
    cost: int = 0
    bonus_condition: str | None = None
    bonus_dice: int = 0


class EquipmentTemplate(BaseModel):
    name: str
    bonus_condition: str | None = None
    bonus_dice: int = 0
    max_uses: int = 3
    special_use: str | None = None
    scavenger_roll: int | None = None


class InjurySlotTemplate(BaseModel):
    category: str  # "1-2", "3-4", "5-6"
    minor: str
    major: str
    major_penalty: str


class CharacterTemplate(BaseModel):
    id: str
    name: str
    description: str
    hooks: list[str] = Field(default_factory=list)
    stats: dict[str, int]  # stat name -> value
    abilities: list[AbilityTemplate] = Field(default_factory=list)
    advances: list[AdvanceTemplate] = Field(default_factory=list)
    equipment: list[EquipmentTemplate] = Field(default_factory=list)
    injuries: dict[str, InjurySlotTemplate] = Field(default_factory=dict)
    last_stand: str = ""
    starting_blood: int = 0


class EnemyTemplate(BaseModel):
    id: str
    name: str
    description: str
    threat: int
    attack: int
    challenge: int = 0
    is_ubermensch: bool = False
    solo: bool = False
    special_rules: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    blood_flavour: str | None = None


class ObjectiveTemplate(BaseModel):
    name: str
    rating: int
    challenge: int = 0


class SecondaryObjectiveTemplate(BaseModel):
    name: str
    rating: int
    reward: str = ""


class LootTemplate(BaseModel):
    name: str
    bonus_condition: str | None = None
    bonus_dice: int = 0
    max_uses: int = 3


class LocationTemplate(BaseModel):
    id: str
    name: str
    sector: int
    description: str
    objective: ObjectiveTemplate
    enemies: list[str] = Field(default_factory=list)  # enemy template IDs
    loot: list[LootTemplate] = Field(default_factory=list)
    secondary_objectives: list[SecondaryObjectiveTemplate] = Field(default_factory=list)
    connections: list[str] = Field(default_factory=list)  # location IDs


# --- Mutable State Models (stored in SQLite) ---

class EquipmentState(BaseModel):
    name: str
    uses_remaining: int
    bonus_condition: str | None = None
    bonus_dice: int = 0
    is_loot: bool = False


class InjuryState(BaseModel):
    category: str  # "1-2", "3-4", "5-6"
    minor_marked: bool = False
    major_marked: bool = False


class CharacterState(BaseModel):
    id: str
    session_id: str
    template_id: str
    name: str
    blood: int = 0
    injuries: list[InjuryState] = Field(default_factory=list)
    equipment: list[EquipmentState] = Field(default_factory=list)
    unlocked_advances: list[str] = Field(default_factory=list)
    flashback_used: bool = False
    is_downed: bool = False
    is_dead: bool = False
    current_location_id: str | None = None


class ThreatState(BaseModel):
    enemy_id: str
    name: str
    current_rating: int
    current_attack: int
    base_attack: int
    challenge: int = 0
    is_defeated: bool = False


class ObjectiveState(BaseModel):
    name: str
    current_rating: int
    challenge: int = 0
    is_completed: bool = False


class SceneState(BaseModel):
    id: str
    session_id: str
    location_id: str
    active_threats: list[ThreatState] = Field(default_factory=list)
    active_objectives: list[ObjectiveState] = Field(default_factory=list)
    completed: bool = False


class DiceRoll(BaseModel):
    id: str
    session_id: str
    character_id: str
    scene_id: str
    pool_size: int
    results: list[int] = Field(default_factory=list)
    discarded: list[int] = Field(default_factory=list)
    kept: list[int] = Field(default_factory=list)
    allocations: dict[str, list[int]] = Field(default_factory=dict)
    gm_pool_size: int = 0
    gm_results: list[int] = Field(default_factory=list)
    gm_discarded: list[int] = Field(default_factory=list)
    gm_kept: list[int] = Field(default_factory=list)
    timestamp: str = ""


class GameSession(BaseModel):
    id: str
    tenant_id: str = "default"
    policy_version: str = "policy-v1"
    phase: GamePhase = GamePhase.setup
    state_revision: int = 0
    current_location_id: str | None = None
    active_character_id: str | None = None
    round_number: int = 0
    scene_number: int = 0
    created_at: str = ""


# --- Decision provenance ---

# Kept in a transport-independent package so persistence and graph renderers
# share one versioned contract. ``DecisionRecord`` remains an explicit 1.x
# compatibility alias; it no longer describes hidden reasoning or causality.
# `DecisionProvenance`/`DecisionRecord` are imported above from
# `gia_core.provenance.models`; the import-boundary checker protects this
# transport-independent split) and re-exported here so
# `havoc_domain.models` carries the full state-model surface `gia.models`
# used to.
