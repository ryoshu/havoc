"""Protocol smoke tests against the official MCP Python SDK v2 client."""

from __future__ import annotations

import json

import anyio

from mcp.client import Client
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from src.gia.server import mcp


def _text(result) -> dict:
    return json.loads(result.content[0].text)


async def _exercise_server() -> None:
    async with Client(mcp) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.server_info.name == "gia-eat-the-reich"
        assert client.server_info.title == "GIA — EAT THE REICH"

        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} >= {"create_session", "get", "search", "act"}
        by_name = {tool.name: tool for tool in tools.tools}
        assert by_name["get"].input_schema["properties"]["resource_type"]["enum"]
        assert "expected_revision" in by_name["act"].input_schema["required"]
        assert by_name["get"].annotations.read_only_hint is True
        assert by_name["act"].annotations.destructive_hint is True

        created = _text(await client.call_tool("create_session", {}))
        session_id = created["data"]["id"]
        assert (await client.call_tool("create_session", {})).structured_content is not None
        state = _text(
            await client.call_tool(
                "get",
                {"resource_type": "session", "session_id": session_id},
            )
        )
        assert state["data"]["id"] == session_id
        assert state["state_revision"] == 0

        acted = await client.call_tool(
            "act",
            {
                "action": "select_character",
                "params": {"template_id": "iryna"},
                "session_id": session_id,
                "expected_revision": 0,
            },
        )
        assert acted.is_error is False
        assert acted.structured_content is not None

        rejected = await client.call_tool(
            "act",
            {
                "action": "select_character",
                "params": {"template_id": "iryna", "unexpected": True},
                "session_id": session_id,
                "expected_revision": 1,
            },
        )
        assert rejected.is_error is True


def test_mcp_v2_in_memory_client_contract():
    anyio.run(_exercise_server)


def test_stateless_streamable_http_app_exposes_mcp_route():
    app = mcp.streamable_http_app(
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1", "localhost"]
        ),
    )
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)
