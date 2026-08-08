"""RS-09: `havoc_server`, the Havoc GIA-GAS MCP composition root.

Proves the canonical entry point (`uv run python -m havoc_server`) works
standalone and that it runs on
`GiaGasAdapter`/`GasService` rather than the deprecated `GasRuntime`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import anyio

from mcp.client import Client

from havoc_server.runtime import GameRuntime
from havoc_server.app import build_mcp_server

REPO_ROOT = Path(__file__).resolve().parent.parent


def _text(result) -> dict:
    return json.loads(result.content[0].text)


async def _exercise(server) -> None:
    async with Client(server) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.server_info.name == "gia-eat-the-reich"

        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} >= {
            "create_session",
            "get",
            "search",
            "act",
            "why_not",
        }

        resources = await client.list_resources()
        resource_uris = {str(resource.uri) for resource in resources.resources}
        assert resource_uris >= {
            "gia://rules",
            "gia://characters",
            "gia://enemies",
            "gia://locations",
            "gia://ontology",
        }
        characters = await client.read_resource("gia://characters")
        assert any(item["id"] == "iryna" for item in json.loads(characters.contents[0].text))

        created = _text(await client.call_tool("create_session", {}))
        session_id = created["data"]["id"]
        state = _text(
            await client.call_tool("get", {"resource_uri": f"gia://session/{session_id}"})
        )
        capability = next(
            command
            for command in state["commands"]
            if command["command"] == "select_character"
            and command["input_schema"]["properties"]["template_id"]["const"] == "iryna"
        )
        acted = await client.call_tool(
            "act",
            {
                "capability_id": capability["id"],
                "expected_revision": state["state_revision"],
                "input": {"template_id": "iryna"},
                "idempotency_key": "havoc-server-test",
                "session_id": session_id,
            },
        )
        assert acted.is_error is False


def test_havoc_server_build_mcp_server_is_a_standalone_gia_backed_gas_server():
    runtime = GameRuntime()
    try:
        server, built_runtime = build_mcp_server(runtime=runtime)
        assert built_runtime is runtime
        anyio.run(_exercise, server)
    finally:
        runtime.ctx.db.close()


def test_importing_native_mcp_does_not_build_the_default_app_server():
    """RS-03 (docs/GIA-REPOSITORY-SPLIT-PLAN.md) moved the native renderer
    into `havoc_server.native_mcp`. Python always runs a package's
    `__init__.py` before any of its submodules, so if that `__init__.py`
    eagerly imported `.app` (whose module level does
    `mcp, _runtime = build_mcp_server()` — opening a live `GameRuntime`/
    SQLite database as a side effect), merely importing the renderer would
    silently boot the whole application. `havoc_server/__init__.py` defers
    that import behind `__getattr__` for exactly this reason; this proves
    `havoc_server.app` never lands in `sys.modules` from the renderer import
    alone. Runs in a subprocess (mirroring `tests/test_gas_mcp.py`'s own
    import-boundary probes) so this process's already-imported `havoc_server`
    can't mask the regression.
    """
    probe = (
        "import sys\n"
        "import havoc_server.native_mcp\n"
        "print('havoc_server.app' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_rs09_removes_the_legacy_gia_composition_module():
    """The Havoc application has one canonical runtime namespace now."""
    probe = (
        "import importlib.util, sys\n"
        "import havoc_server.runtime\n"
        "print(importlib.util.find_spec('gia.server'))\n"
        "print(any(name == 'gia.server' or name.startswith('gia.server.') for name in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["None", "False"]
