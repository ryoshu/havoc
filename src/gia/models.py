"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/models.py``.

``Affordance`` and ``DomainEvent`` moved to ``gia_core.contracts`` (PR 14
of the GIA/GAS 2.0 plan) — neither ever referenced a Havoc concept. Every
other name here is concrete Havoc state, moved to ``havoc_domain.models``
in PR 18. Both are re-exported here so every existing
``from .models import ...``/``from gia.models import ...`` import keeps
working unchanged; PR 19 migrates callers to import from the real homes
directly.
"""

from __future__ import annotations

from gia_core.contracts import Affordance, DomainEvent
from havoc_domain.models import (
    AbilityTemplate,
    AdvanceTemplate,
    CharacterState,
    CharacterTemplate,
    DecisionProvenance,
    DecisionRecord,
    DiceAllocation,
    DiceRoll,
    EnemyTemplate,
    EquipmentState,
    EquipmentTemplate,
    GamePhase,
    GameSession,
    InjurySlotTemplate,
    InjuryState,
    LocationTemplate,
    LootTemplate,
    ObjectiveState,
    ObjectiveTemplate,
    SecondaryObjectiveTemplate,
    SceneState,
    Stat,
    ThreatState,
)

__all__ = [
    "Affordance",
    "DomainEvent",
    "AbilityTemplate",
    "AdvanceTemplate",
    "CharacterState",
    "CharacterTemplate",
    "DecisionProvenance",
    "DecisionRecord",
    "DiceAllocation",
    "DiceRoll",
    "EnemyTemplate",
    "EquipmentState",
    "EquipmentTemplate",
    "GamePhase",
    "GameSession",
    "InjurySlotTemplate",
    "InjuryState",
    "LocationTemplate",
    "LootTemplate",
    "ObjectiveState",
    "ObjectiveTemplate",
    "SecondaryObjectiveTemplate",
    "SceneState",
    "Stat",
    "ThreatState",
]
