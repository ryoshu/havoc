"""Canonical Havoc application runtime and GIA-to-GAS composition.

RS-09 makes Havoc the application repository and removes the transitional
``gia.server`` composition facade.  ``GameRuntime`` remains implemented by
``havoc_domain``; this module owns the one application-level composition
from that runtime to ``GiaGasAdapter`` and ``GasService``.  The MCP server
(``havoc_server.app``) and the Director/playthrough consumers all build from
this module, so there is one runtime singleton and no bare-vs-``src.`` module
duality to reconcile.

Importing this module does not require the optional MCP SDK.  Callers that
need MCP import ``havoc_server.app`` or run ``python -m havoc_server``.
"""

from __future__ import annotations

import os
from typing import Any

from gas_protocol.service import GasService
from gia_gas_adapter import GiaGasAdapter
from havoc_domain.runtime import GameRuntime

def _configured_db_path() -> str:
    """Return the database path used by the module-level runtime."""
    return os.environ.get("GIA_DB_PATH", ":memory:")


def build_gas_service(runtime: GameRuntime, **gas_service_kwargs: Any) -> GasService:
    """Render ``runtime`` as a GAS 2.0 operation surface.

    This is the one shared ``GameRuntime`` → ``GiaGasAdapter`` →
    ``GasService`` composition used by the Director, playthrough runner,
    and ``havoc_server.app``. ``gas_service_kwargs`` forwards to
    ``GasService`` for callers that need a non-default payload budget.
    """
    adapter = GiaGasAdapter(
        runtime._application,
        runtime._application,
        runtime._application,
        policy_provider=runtime.ctx.policy_provider,
        request_context=runtime.request_context,
    )
    return GasService(adapter, scheme="gia", **gas_service_kwargs)


# Module-level runtime. Stateful requests must carry their session handle.
# This lives in the canonical Havoc namespace now that the old ``gia.server``
# compatibility module is gone.
_default = GameRuntime(db_path=_configured_db_path())
gas_service = build_gas_service(_default)
ctx = _default.ctx
engine = _default.engine
