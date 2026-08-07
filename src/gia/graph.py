"""Deprecated re-export shim (PR 18) — see ``src/havoc_domain/graph.py``.

``GameGraph`` and its Oxigraph plumbing have no Havoc-specific concept in
them structurally, but they only ever load Havoc data (the ``etr#``
vocabulary, character/enemy/location JSON) — the same shape of move PR 18's
own docstring names for ``context.py``/``db.py``/``domain.py``. Kept here so
existing imports (``from gia.graph import GameGraph``) keep working; PR 19
migrates callers to import from ``havoc_domain`` directly.
"""

from __future__ import annotations

from havoc_domain.graph import (
    ETR,
    GRAPH_SCHEMA_VERSION,
    PREFIXES,
    PROVENANCE_PREDICATE_VERSION,
    RDF,
    RDFS,
    XSD,
    GameGraph,
    GraphValidationReport,
)

__all__ = [
    "ETR",
    "GRAPH_SCHEMA_VERSION",
    "PREFIXES",
    "PROVENANCE_PREDICATE_VERSION",
    "RDF",
    "RDFS",
    "XSD",
    "GameGraph",
    "GraphValidationReport",
]
