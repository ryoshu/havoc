"""Havoc composition object + compatibility re-export.

`GameRuntime` moved to `havoc_domain.runtime` in PR 18 (concrete Havoc
composition — see that module's docstring for why this file keeps the
module-level singleton/back-compat machinery instead of moving wholesale).
It is re-exported below so every existing `from gia.server import
GameRuntime` keeps working. MCP registration itself — the `MCPServer`
instance, its resources and tools, and the transport entry point — moved
to `havoc_server` in PR 17 (`docs/GIA-GAS-SEPARATION-EXECUTION-PLAN.md`);
`mcp` and `_allowed_hosts` are re-exported below (lazily, so importing
`GameRuntime` alone never requires the `mcp` package to be installed) so
every existing `from src.gia.server import mcp, ...` keeps working, and
`uv run python -m src.gia.server` keeps working as a compatibility alias
for `uv run python -m havoc_server`.

PR 19 removed the deprecated `compat.py`/`gia.gas` (`JsonGameRuntimeAdapter`/
`GasRuntime`) compatibility path and the module-level legacy JSON
`create_session`/`get`/`search`/`act` functions that delegated to it. This
module now builds and exposes `gas_service` — a real, non-deprecated
`gas_protocol.service.GasService` over `gia_gas_adapter.GiaGasAdapter` — as
the one shared composition every GAS-shaped caller (Director, playthrough,
`havoc_server`) should build from, via `build_gas_service()` below.
"""

from __future__ import annotations

import os
from typing import Any

from gas_protocol.service import GasService
from gia_gas_adapter import GiaGasAdapter
from havoc_domain.runtime import GameRuntime

# ---------------------------------------------------------------------------
# Module-level runtime. Stateful requests must carry their session handle;
# importing this module does not create a game.
#
# Constructed through `gia._runtime_cache` (always the same, single bare
# module regardless of whether *this* file is currently executing as
# `gia.server` or `src.gia.server`) rather than directly, so the singleton
# is canonical across both import paths — see that module's docstring.
# ---------------------------------------------------------------------------

import gia._runtime_cache as _runtime_cache  # noqa: E402


def _configured_db_path() -> str:
    """Return the database path used by the module-level runtime."""
    return os.environ.get("GIA_DB_PATH", ":memory:")


def build_gas_service(runtime: GameRuntime, **gas_service_kwargs: Any) -> GasService:
    """Render ``runtime`` as a GAS 2.0 operation surface.

    The one shared composition (`GameRuntime` -> `GiaGasAdapter` ->
    `GasService`) every first-party GAS-shaped caller builds from — the
    Director, the playthrough runner, and `havoc_server.app.build_mcp_server`
    (which calls this instead of inlining its own copy). Replaces the
    deprecated, hand-rolled `gia.gas.GasRuntime`. ``gas_service_kwargs``
    forwards to `GasService` (e.g. ``max_page_size``) for callers that need
    a non-default payload budget.
    """
    adapter = GiaGasAdapter(
        runtime._application,
        runtime._application,
        runtime._application,
        policy_provider=runtime.ctx.policy_provider,
        request_context=runtime.request_context,
    )
    return GasService(adapter, scheme="gia", **gas_service_kwargs)


if not hasattr(_runtime_cache, "_default"):
    _runtime_cache._default = GameRuntime(db_path=_configured_db_path())
    _runtime_cache.gas_service = build_gas_service(_runtime_cache._default)
    _runtime_cache.ctx = _runtime_cache._default.ctx
    _runtime_cache.engine = _runtime_cache._default.engine

_default = _runtime_cache._default
gas_service = _runtime_cache.gas_service
ctx = _runtime_cache.ctx
engine = _runtime_cache.engine


# --- PR 17 compatibility re-export -----------------------------------------
#
# `mcp`/`_allowed_hosts` moved to `havoc_server` (the actual MCP composition
# root). Re-exported lazily via module `__getattr__` (PEP 562) so that
# `from src.gia.server import GameRuntime` — the overwhelming majority of
# this module's callers — never imports `havoc_server` or the `mcp`
# package; only a caller that actually asks for `mcp`/`_allowed_hosts`
# pays that cost.
def __getattr__(name: str) -> Any:
    if name in ("mcp", "_allowed_hosts"):
        from havoc_server import app as _havoc_server_app

        return getattr(_havoc_server_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    from havoc_server.__main__ import main

    main()
