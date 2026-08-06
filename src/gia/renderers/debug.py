"""A deterministic debug/CLI renderer for inspecting the raw capability IR."""

from __future__ import annotations

import json
from typing import Any

from ..capabilities import CapabilitySet


class DebugRenderer:
    """Expose the canonical capability-set representation for operators."""

    def render(self, capability_set: CapabilitySet) -> dict[str, Any]:
        """Return a detached JSON-compatible mapping."""
        return capability_set.model_dump(mode="json")

    def render_json(self, capability_set: CapabilitySet) -> str:
        """Serialize a capability set deterministically for CLI/debug output."""
        return json.dumps(
            self.render(capability_set),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def render_debug(capability_set: CapabilitySet) -> dict[str, Any]:
    """Functional convenience wrapper for the debug renderer."""
    return DebugRenderer().render(capability_set)

