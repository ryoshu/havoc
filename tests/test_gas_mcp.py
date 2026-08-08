"""PR 17: the generic GAS MCP installer (`gas_mcp`).

`gas_mcp.generic.install_gas_mcp` registers MCP tools purely against
`gas_protocol.service.GasService` — no GIA, no Havoc. These tests exercise
it over `gas_protocol.fake_backend.InMemoryGasBackend`, the same
domain-neutral "notes" backend PR 15's own tests use, proving the
installer needs no GIA or Havoc to function (the concrete MCP-transport
instantiation of PR 15's "GIA is not required to implement GAS" claim).

Also proves the packaging boundary PR 17 makes load-bearing for the first
time: `gia_core`/`gas_protocol`/`gia_gas_adapter` must import successfully
with the `mcp` package entirely absent from `sys.modules`,
and `gas_mcp` itself must never import a Havoc-domain module.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from mcp.client import Client
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError

from gas_mcp import install_gas_mcp
from gas_protocol.fake_backend import InMemoryGasBackend
from gas_protocol.service import GasService

REPO_ROOT = Path(__file__).resolve().parent.parent


def _text(result) -> dict:
    return json.loads(result.content[0].text)


def _build_server() -> MCPServer:
    server = MCPServer(name="gas-mcp-test")
    install_gas_mcp(server, GasService(InMemoryGasBackend()))
    return server


async def _exercise_server() -> None:
    server = _build_server()
    async with Client(server) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "create_session",
            "get",
            "search",
            "act",
            "why_not",
        }
        by_name = {tool.name: tool for tool in tools.tools}
        assert by_name["get"].annotations.read_only_hint is True
        assert by_name["act"].annotations.destructive_hint is True
        assert by_name["why_not"].annotations.read_only_hint is True
        # The generic installer carries no domain-specific Literal enums —
        # resource_type is a plain string, unlike the Havoc-specific
        # SearchType this generalizes (see gas_mcp/generic.py's module
        # docstring).
        assert by_name["search"].input_schema["properties"]["resource_type"]["type"] == "string"

        created = _text(await client.call_tool("create_session", {}))
        session_id = created["data"]["id"]
        assert created["commands"][0]["command"] == "create_note"

        state = _text(
            await client.call_tool("get", {"resource_uri": f"gas://session/{session_id}"})
        )
        assert state["data"]["id"] == session_id
        create_note = next(c for c in state["commands"] if c["command"] == "create_note")

        acted = await client.call_tool(
            "act",
            {
                "capability_id": create_note["id"],
                "expected_revision": state["state_revision"],
                "input": {"title": "hello", "body": "world"},
                "idempotency_key": "gas-mcp-test",
                "session_id": session_id,
            },
        )
        assert acted.is_error is False
        acted_data = _text(acted)
        assert acted_data["events"][0]["type"] == "note_created"

        searched = _text(
            await client.call_tool(
                "search", {"resource_type": "notes", "session_id": session_id}
            )
        )
        assert len(searched["data"]) == 1

        why_not = _text(
            await client.call_tool(
                "why_not",
                {"resource_uri": f"gas://session/{session_id}", "command": "delete_note"},
            )
        )
        assert why_not["data"]["available"] is False

        with pytest.raises(MCPError) as error:
            await client.call_tool(
                "act",
                {
                    "capability_id": create_note["id"],
                    "expected_revision": state["state_revision"] + 5,
                    "input": {"title": "hello", "body": "world"},
                    "idempotency_key": "gas-mcp-test-stale",
                    "session_id": session_id,
                },
            )
        assert error.value.code == -32000
        assert error.value.message == "stale_state"


def test_install_gas_mcp_over_fake_backend():
    anyio.run(_exercise_server)


def _run_probe(probe: str) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return [name for name in result.stdout.strip().split(",") if name]


def test_gas_mcp_does_not_import_havoc_domain():
    """gas-mcp | gas-protocol, MCP SDK | Havoc, databases, GIA policy internals.

    Also proves the RS-03 acceptance criterion (docs/GIA-REPOSITORY-SPLIT-PLAN.md):
    ``gas_mcp`` no longer loads ``gia_core`` at all now that the native
    per-capability renderer (the one thing that used to pull ``gia_core.
    CapabilitySet`` in) moved to ``havoc_server.native_mcp``.
    """
    probe = (
        "import sys\n"
        "import gas_mcp\n"
        "forbidden_prefixes = ("
        "'havoc_server.runtime', 'havoc_domain', 'gia_core',\n"
        "    'havoc_server', 'gia_mcp',\n"
        ")\n"
        "hits = sorted(\n"
        "    name for name in sys.modules\n"
        "    if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden_prefixes)\n"
        ")\n"
        "print(','.join(hits))\n"
    )
    assert _run_probe(probe) == []


@pytest.mark.parametrize("module", ["gia_core", "gas_protocol", "gia_gas_adapter", "havoc_server.runtime"])
def test_reusable_cores_do_not_import_mcp(module):
    """The claim `mcp` becoming an optional dependency (PR 17) makes real."""
    probe = (
        "import sys\n"
        f"import {module}\n"
        "hits = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name == 'mcp' or name.startswith('mcp.')\n"
        ")\n"
        "print(','.join(hits))\n"
    )
    assert _run_probe(probe) == []
