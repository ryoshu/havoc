"""Model provider configuration — auto-detect available providers."""

from __future__ import annotations

import os
import sys

from .config import ModelConfig


def get_available_models() -> list[ModelConfig]:
    """Auto-detect available models based on environment variables."""
    models = []

    # Ollama (always available if running)
    models.append(ModelConfig(
        name="qwen3.5:9b",
        model="qwen3.5:9b",
        api_base="http://localhost:11434/v1",
        api_key="ollama",
        tier="local",
        is_ollama=True,
    ))

    # DeepInfra
    deepinfra_key = os.environ.get("DEEPINFRA_API_KEY", "")
    if deepinfra_key:
        models.append(ModelConfig(
            name="Qwen2.5-72B",
            model="Qwen/Qwen2.5-72B-Instruct",
            api_base="https://api.deepinfra.com/v1/openai",
            api_key=deepinfra_key,
            tier="open-weights",
        ))
        models.append(ModelConfig(
            name="Llama-3.3-70B",
            model="meta-llama/Llama-3.3-70B-Instruct",
            api_base="https://api.deepinfra.com/v1/openai",
            api_key=deepinfra_key,
            tier="open-weights",
        ))
        models.append(ModelConfig(
            name="GLM-5",
            model="zai-org/GLM-5",
            api_base="https://api.deepinfra.com/v1/openai",
            api_key=deepinfra_key,
            tier="open-weights",
        ))

    # OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        models.append(ModelConfig(
            name="gpt-4o",
            model="gpt-4o",
            api_base="https://api.openai.com/v1",
            api_key=openai_key,
            tier="frontier",
        ))
        models.append(ModelConfig(
            name="gpt-5.4",
            model="gpt-5.4",
            api_base="https://api.openai.com/v1",
            api_key=openai_key,
            tier="frontier",
        ))

    # Anthropic (native SDK — not OpenAI-compatible)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_KEY", "")
    if anthropic_key:
        models.append(ModelConfig(
            name="claude-sonnet",
            model="claude-sonnet-4-20250514",
            api_base="https://api.anthropic.com",
            api_key=anthropic_key,
            tier="frontier",
            is_anthropic=True,
        ))
        models.append(ModelConfig(
            name="claude-opus",
            model="claude-opus-4-6",
            api_base="https://api.anthropic.com",
            api_key=anthropic_key,
            tier="frontier",
            is_anthropic=True,
        ))

    return models


def get_model_by_name(name: str) -> ModelConfig | None:
    """Find a model config by display name."""
    for m in get_available_models():
        if m.name == name or m.model == name:
            return m
    return None


def print_available_models():
    """Print available models to stderr."""
    models = get_available_models()
    print("Available models:", file=sys.stderr)
    for m in models:
        print(f"  [{m.tier}] {m.name} ({m.model})", file=sys.stderr)
