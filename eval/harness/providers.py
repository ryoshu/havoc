"""Model provider configuration for the authoritative eval model list."""

from __future__ import annotations

import os
import sys

from .config import ModelConfig

DEEPINFRA_API_BASE = "https://api.deepinfra.com/v1/openai"
OPENAI_API_BASE = "https://api.openai.com/v1"
ANTHROPIC_API_BASE = "https://api.anthropic.com"

# Canonical eval list (display name + provider in name for clarity).
DEEPINFRA_MODELS: tuple[tuple[str, str], ...] = (
    ("GLM-5 (DeepInfra)", os.environ.get("DEEPINFRA_MODEL_GLM_5", "zai-org/GLM-5")),
    ("DeepSeek V3.2 (DeepInfra)", os.environ.get("DEEPINFRA_MODEL_DEEPSEEK_V3_2", "deepseek-ai/DeepSeek-V3.2")),
    (
        "Llama 4 Scout 17B (DeepInfra)",
        os.environ.get("DEEPINFRA_MODEL_LLAMA_4_SCOUT_17B", "meta-llama/Llama-4-Scout-17B-16E-Instruct"),
    ),
    (
        "Nemotron 3 Nano 30B-A3B (DeepInfra)",
        os.environ.get("DEEPINFRA_MODEL_NEMOTRON_3_NANO_30B_A3B", "nvidia/Nemotron-3-Nano-30B-A3B-Instruct"),
    ),
    ("Qwen3 32B (DeepInfra)", os.environ.get("DEEPINFRA_MODEL_QWEN3_32B", "Qwen/Qwen3-32B")),
)

OPENAI_MODELS: tuple[tuple[str, str], ...] = (
    ("GPT-4o (OpenAI)", os.environ.get("OPENAI_MODEL_GPT_4O", "gpt-4o")),
)

ANTHROPIC_MODELS: tuple[tuple[str, str], ...] = (
    ("Claude Haiku 4.5 (Anthropic)", os.environ.get("ANTHROPIC_MODEL_HAIKU_4_5", "claude-haiku-4-5")),
)

# Short aliases accepted by `--model`.
NAME_ALIASES = {
    "gpt-4o": "GPT-4o (OpenAI)",
    "glm-5": "GLM-5 (DeepInfra)",
    "deepseek-v3.2": "DeepSeek V3.2 (DeepInfra)",
    "claude-haiku-4.5": "Claude Haiku 4.5 (Anthropic)",
    "llama-4-scout-17b": "Llama 4 Scout 17B (DeepInfra)",
    "nemotron-3-nano-30b-a3b": "Nemotron 3 Nano 30B-A3B (DeepInfra)",
    "qwen3-32b": "Qwen3 32B (DeepInfra)",
}


def _normalize_name(value: str) -> str:
    return value.strip().lower()


def get_available_models() -> list[ModelConfig]:
    """Auto-detect available models from the authoritative catalog."""
    models = []

    # DeepInfra
    deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")
    if deepinfra_key:
        for name, model_id in DEEPINFRA_MODELS:
            models.append(ModelConfig(
                name=name,
                model=model_id,
                api_base=DEEPINFRA_API_BASE,
                api_key=deepinfra_key,
                tier="open-weights",
            ))

    # OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        for name, model_id in OPENAI_MODELS:
            models.append(ModelConfig(
                name=name,
                model=model_id,
                api_base=OPENAI_API_BASE,
                api_key=openai_key,
                tier="frontier",
            ))

    # Anthropic (native SDK — not OpenAI-compatible)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_KEY", "")
    if anthropic_key:
        for name, model_id in ANTHROPIC_MODELS:
            models.append(ModelConfig(
                name=name,
                model=model_id,
                api_base=ANTHROPIC_API_BASE,
                api_key=anthropic_key,
                tier="frontier",
                is_anthropic=True,
            ))

    return models


def get_model_by_name(name: str) -> ModelConfig | None:
    """Find a model config by display name."""
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
