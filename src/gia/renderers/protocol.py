"""Transport-neutral renderer contracts for the GIA capability IR."""

from __future__ import annotations

from typing import Protocol, TypeVar

from ..capabilities import CapabilitySet


RenderedT = TypeVar("RenderedT")


class CapabilityRenderer(Protocol[RenderedT]):
    """Render one contextual capability set without changing its authority."""

    def render(self, capability_set: CapabilitySet) -> RenderedT:
        """Return a transport-specific view of ``capability_set``."""

