"""Command-policy kernel primitives (PR 3 of the GIA/GAS 2.0 plan).

``Binding``, ``Command``, and ``Snapshot`` moved to ``src.gia_core.command``
(PR 14) — none of the three ever needed a Havoc type to be honest about
their own shape. Re-exported here for backward compatibility.
"""

from __future__ import annotations

from ...gia_core.command import Binding, Command, Snapshot
from ..policy import Actor

__all__ = ["Actor", "Binding", "Command", "Snapshot"]
