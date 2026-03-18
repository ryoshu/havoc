"""Data types for the playthrough system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlaythroughStrategy:
    """Configuration for how the Director plays the game."""
    characters: list[str]  # template_ids to select
    stat_preference: str = "best"  # "best" picks highest stat, or a specific stat name
    allocation_strategy: str = "objective_first"  # "objective_first" | "balanced"


@dataclass
class NarrativeBeat:
    """A single narrative moment captured during the playthrough."""
    type: str  # scene_arrival, combat_round, injury, scene_complete, death, advance, epilogue
    data: dict = field(default_factory=dict)  # raw game response data
    events: list[dict] = field(default_factory=list)  # domain events from this beat
    context: str = ""  # graph-enriched text from ContextBuilder
    narration: str = ""  # LLM prose from Narrator
