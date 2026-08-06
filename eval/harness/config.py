"""Configuration for eval runs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .controls import DEFAULT_RETRY_POLICY, HistoryPolicyName, RetryPolicy


class ModelConfig(BaseModel):
    name: str  # display name, e.g. "GPT-4o (OpenAI)"
    model: str  # API model ID
    api_base: str  # OpenAI-compatible endpoint
    api_key: str  # from env var
    tier: str = "local"  # "local", "open-weights", "frontier"
    is_ollama: bool = False
    is_anthropic: bool = False
    # Provider/model identifiers are pinned in the PR12 snapshot.  The field
    # is optional for historical callers that only have an API model ID.
    provider_version: str = ""


def parse_mode(mode_str: str) -> tuple[str, int | str]:
    """Parse a CLI mode string into (eval_mode, tool_level).

    Examples: "gas" → ("gas-advisory", 3), "gas-enforced" → ("gas-enforced", 3),
              "trad-60-poly" → ("trad", "60-poly").
    """
    if mode_str in {"gas", "gas-advisory"}:
        return "gas-advisory", 3
    if mode_str == "gas-enforced":
        return "gas-enforced", 3
    if mode_str in {"generic", "gas-generic"}:
        return "gas-generic", 3
    if mode_str in {"static-native", "state-filtered-native"}:
        return "trad", 15
    prefix, _, rest = mode_str.partition("-")
    try:
        return "trad", int(rest)
    except ValueError:
        return "trad", rest  # e.g. "60-poly"


class EvalConfig(BaseModel):
    """Configuration for a single eval run."""
    domain: str = "pm"  # "pm", "cruise", or "auto"
    mode: str  # "gas" or "trad"
    tool_level: int | str = 3  # 3 for GAS, 15/30/60/"60-poly" for trad
    model: ModelConfig
    acting_user_id: str = "user-mgr-1"  # default: Carol Reyes (manager) for PM
    max_retries: int = 3
    timeout_seconds: float = 300.0
    # PR12 study controls.  Defaults preserve the historical harness behavior.
    condition: str = ""
    experiment_id: str = ""
    run_seed: int = 0
    history_policy: HistoryPolicyName = "compact-affordances"
    retry_policy: RetryPolicy = Field(default_factory=lambda: DEFAULT_RETRY_POLICY)
    advertise_capabilities: bool = True
    state_filtered: bool = False
    retain_transcript: bool = True


# Default acting user per domain
DOMAIN_DEFAULT_USER: dict[str, str] = {
    "pm": "user-mgr-1",      # Carol Reyes (manager)
    "cruise": "user-agent-1",  # Sophie Chen (agent)
    "auto": "user-sales-1",   # Jake Morrison (salesperson)
}


class MatrixConfig(BaseModel):
    """Configuration for a full eval matrix run."""
    domain: str = "pm"  # "pm", "cruise", or "auto"
    models: list[ModelConfig] = Field(default_factory=list)
    modes: list[str] = Field(default_factory=lambda: ["gas-advisory", "trad-15"])
    task_tiers: list[int] = Field(default_factory=lambda: [1, 3])
    runs_per_cell: int = 1  # repeat count for statistical significance
    # When set, PR12 conditions take precedence over ``modes``.
    conditions: list[str] = Field(default_factory=list)
    experiment_id: str = ""
    history_policy: HistoryPolicyName = "compact-affordances"
    retry_policy: RetryPolicy = Field(default_factory=lambda: DEFAULT_RETRY_POLICY)
