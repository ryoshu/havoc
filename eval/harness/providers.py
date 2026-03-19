"""Model provider configuration — single source of truth for the eval model catalog.

All display metadata (labels, colors, ordering) lives here so that
charts, summaries, and the CLI stay in sync automatically.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from .config import ModelConfig

DEEPINFRA_API_BASE = "https://api.deepinfra.com/v1/openai"
OPENAI_API_BASE = "https://api.openai.com/v1"
ANTHROPIC_API_BASE = "https://api.anthropic.com"


@dataclass
class ModelCatalogEntry:
    """Authoritative metadata for a model in the eval catalog."""
    name: str          # canonical DB name, e.g. "GPT-4o (OpenAI)"
    model_id: str      # API model ID
    label: str         # short chart label, e.g. "GPT-4o"
    color: str         # hex color for charts
    provider: str      # "deepinfra", "openai", "anthropic"
    tier: str = "open-weights"
    is_anthropic: bool = False
    aliases: list[str] = field(default_factory=list)
    legacy_names: list[str] = field(default_factory=list)


# --- Authoritative model catalog ---
# Order here determines chart ordering.

MODEL_CATALOG: list[ModelCatalogEntry] = [
    ModelCatalogEntry(
        name="GPT-4o (OpenAI)",
        model_id=os.environ.get("OPENAI_MODEL_GPT_4O", "gpt-4o"),
        label="GPT-4o",
        color="#0ea5e9",
        provider="openai",
        tier="frontier",
        aliases=["gpt-4o"],
    ),
    ModelCatalogEntry(
        name="GPT-5.4 (OpenAI)",
        model_id=os.environ.get("OPENAI_MODEL_GPT_5_4", "gpt-5.4"),
        label="GPT-5.4",
        color="#6366f1",
        provider="openai",
        tier="frontier",
        aliases=["gpt-5.4"],
        legacy_names=["gpt-5.4"],
    ),
    ModelCatalogEntry(
        name="Claude Haiku 4.5 (Anthropic)",
        model_id=os.environ.get("ANTHROPIC_MODEL_HAIKU_4_5", "claude-haiku-4-5"),
        label="Claude Haiku 4.5",
        color="#f59e0b",
        provider="anthropic",
        tier="frontier",
        is_anthropic=True,
        aliases=["claude-haiku-4.5"],
    ),
    ModelCatalogEntry(
        name="GLM-5 (DeepInfra)",
        model_id=os.environ.get("DEEPINFRA_MODEL_GLM_5", "zai-org/GLM-5"),
        label="GLM-5",
        color="#16a34a",
        provider="deepinfra",
        aliases=["glm-5"],
        legacy_names=[],  # Old "GLM-5" runs were collected under buggy harness — keep separate
    ),
    ModelCatalogEntry(
        name="DeepSeek V3.2 (DeepInfra)",
        model_id=os.environ.get("DEEPINFRA_MODEL_DEEPSEEK_V3_2", "deepseek-ai/DeepSeek-V3.2"),
        label="DeepSeek V3.2",
        color="#2563eb",
        provider="deepinfra",
        aliases=["deepseek-v3.2"],
    ),
    ModelCatalogEntry(
        name="Qwen3 32B (DeepInfra)",
        model_id=os.environ.get("DEEPINFRA_MODEL_QWEN3_32B", "Qwen/Qwen3-32B"),
        label="Qwen3 32B",
        color="#0891b2",
        provider="deepinfra",
        aliases=["qwen3-32b"],
    ),
]

# --- Derived lookups (built once from catalog) ---

# Ordered canonical names for chart axes
MODEL_ORDER: list[str] = [e.name for e in MODEL_CATALOG]

# Canonical name → short chart label
MODEL_LABELS: dict[str, str] = {e.name: e.label for e in MODEL_CATALOG}

# Canonical name → hex color
MODEL_COLORS: dict[str, str] = {e.name: e.color for e in MODEL_CATALOG}

# Legacy DB name → canonical name (for normalizing old runs)
LEGACY_NAME_MAP: dict[str, str] = {}
for _entry in MODEL_CATALOG:
    for _legacy in _entry.legacy_names:
        LEGACY_NAME_MAP[_legacy] = _entry.name

# CLI alias → canonical name
NAME_ALIASES: dict[str, str] = {}
for _entry in MODEL_CATALOG:
    for _alias in _entry.aliases:
        NAME_ALIASES[_alias] = _entry.name


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def get_available_models() -> list[ModelConfig]:
    """Auto-detect available models from the catalog based on API keys."""
    models = []
    key_sources = {
        "deepinfra": os.environ.get("DEEPINFRA_API_KEY", ""),
        "openai": os.environ.get("OPENAI_API_KEY", ""),
        "anthropic": os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_KEY", ""),
    }
    api_bases = {
        "deepinfra": DEEPINFRA_API_BASE,
        "openai": OPENAI_API_BASE,
        "anthropic": ANTHROPIC_API_BASE,
    }

    for entry in MODEL_CATALOG:
        api_key = key_sources.get(entry.provider, "")
        if not api_key:
            continue
        models.append(ModelConfig(
            name=entry.name,
            model=entry.model_id,
            api_base=api_bases[entry.provider],
            api_key=api_key,
            tier=entry.tier,
            is_anthropic=entry.is_anthropic,
        ))

    return models


def get_model_by_name(name: str) -> ModelConfig | None:
    """Find a model config by display name, alias, or model ID."""
    search = _normalize_name(name)
    canonical = NAME_ALIASES.get(search, name)
    canonical_norm = _normalize_name(canonical)
    for m in get_available_models():
        if (
            m.name == name
            or m.model == name
            or _normalize_name(m.name) == search
            or _normalize_name(m.model) == search
            or _normalize_name(m.name) == canonical_norm
        ):
            return m
    return None


def print_available_models():
    """Print available models to stderr."""
    models = get_available_models()
    print("Available models:", file=sys.stderr)
    for m in models:
        print(f"  [{m.tier}] {m.name} ({m.model})", file=sys.stderr)
