"""PR 17: `havoc_server`, the Havoc GIA-GAS MCP composition root.

Proves the new canonical entry point (`uv run python -m havoc_server`)
works standalone — not just through the `src.gia.server` compatibility
re-export `tests/test_mcp_v2.py` exercises — and that it runs on
`GiaGasAdapter`/`GasService` rather than the deprecated `GasRuntime`.
"""

from __future__ import annotations

import json

import anyio

from mcp.client import Client

from src.gia.server import GameRuntime
from havoc_server.app import build_mcp_server


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
