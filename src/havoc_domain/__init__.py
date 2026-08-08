"""The Havoc (Eat the Reich) game domain (PR 18 of the GIA/GAS 2.0 plan).

The concrete implementation of the GIA application boundary
(`gia_core.ports.ResourceProvider`/`CapabilityAuthority`) for Eat the
Reich: game state and commands (`models.py`, `commands/`), the
projector/dispatcher and execution service (`kernel.py`, `execution.py`),
repositories and transaction implementation (`db.py`), game graph/ontology
access (`graph.py`), game mechanics (`engine.py`), and the port
implementation itself (`application.py`) plus the back-compat composition
object (`runtime.py`). Moved here from `src/gia/domain.py`, `context.py`,
`db.py`, `graph.py`, `models.py`, and the concrete command modules under
`src/gia/commands/` — each of those old paths is now a thin re-export shim
pointing back at the real module here. See
the import-boundary checker for the full dependency account, including why
`GameRuntime` moved here while `src/gia/server.py` kept the
module-level singleton/back-compat machinery.
"""
