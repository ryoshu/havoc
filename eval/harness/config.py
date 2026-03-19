"""Configuration for eval runs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    name: str  # display name, e.g. "GPT-4o (OpenAI)"
    model: str  # API model ID
    api_base: str  # OpenAI-compatible endpoint
    api_key: str  # from env var
    tier: str = "local"  # "local", "open-weights", "frontier"
    is_ollama: bool = False
    is_anthropic: bool = False


def parse_mode(mode_str: str) -> tuple[str, int | str]:
    """Parse a CLI mode string into (eval_mode, tool_level).

    Examples: "gas" → ("gas", 3), "trad-15" → ("trad", 15),
              "trad-60-poly" → ("trad", "60-poly").
    """
    if mode_str == "gas":
        return "gas", 3
    prefix, _, rest = mode_str.partition("-")
    try:
        return "trad", int(rest)
    except ValueError:
        return "trad", rest  # e.g. "60-poly"


class EvalConfig(BaseModel):
    """Configuration for a single eval run."""
    mode: str  # "gas" or "trad"
    tool_level: int | str = 3  # 3 for GAS, 15/30/60/"60-poly" for trad
    model: ModelConfig
    acting_user_id: str = "user-mgr-1"  # default: Carol Reyes (manager)
    max_retries: int = 3
    timeout_seconds: float = 300.0


class MatrixConfig(BaseModel):
    """Configuration for a full eval matrix run."""
    models: list[ModelConfig] = Field(default_factory=list)
    modes: list[str] = Field(default_factory=lambda: ["gas", "trad-15"])
    task_tiers: list[int] = Field(default_factory=lambda: [1, 3])
    runs_per_cell: int = 1  # repeat count for statistical significance
