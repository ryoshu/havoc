"""Protocol smoke tests against the official MCP Python SDK v2 client."""

from __future__ import annotations

import json

import anyio
import pytest
from starlette.testclient import TestClient

from mcp.client import Client
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError

from src.gia.server import _allowed_hosts, _configured_db_path, mcp


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
        assert by_name["get"].input_schema["properties"]["resource_uri"]["type"] == "string"
        assert set(by_name["act"].input_schema["required"]) >= {
            "capability_id",
            "expected_revision",
            "input",
            "idempotency_key",
        }
        assert "action" not in by_name["act"].input_schema["properties"]
        assert "params" not in by_name["act"].input_schema["properties"]
        assert "query" in by_name["search"].input_schema["properties"]
        assert "filters" not in by_name["search"].input_schema["properties"]
        assert by_name["get"].annotations.read_only_hint is True
        assert by_name["act"].annotations.destructive_hint is True

        resources = await client.list_resources()
        resource_uris = {str(resource.uri) for resource in resources.resources}
        assert resource_uris >= {
            "gia://rules",
            "gia://characters",
            "gia://enemies",
            "gia://locations",
            "gia://ontology",
        }
        assert resources.ttl_ms == 3_600_000
        characters = await client.read_resource("gia://characters")
        assert characters.contents[0].mime_type == "application/json"
        assert any(item["id"] == "iryna" for item in json.loads(characters.contents[0].text))
        ontology = await client.read_resource("gia://ontology")
        assert ontology.contents[0].mime_type == "text/turtle"
        assert "etr:" in ontology.contents[0].text

        created = _text(await client.call_tool("create_session", {}))
        session_id = created["data"]["id"]
        assert (await client.call_tool("create_session", {})).structured_content is not None
        state = _text(
            await client.call_tool(
                "get",
                {"resource_uri": f"gia://session/{session_id}"},
            )
        )
        assert state["data"]["id"] == session_id
        assert state["state_revision"] == 0
        assert state["commands"]
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
                "expected_revision": 0,
                "input": {"template_id": "iryna"},
                "idempotency_key": "mcp-v2-test",
                "session_id": session_id,
            },
        )
        assert acted.is_error is False
        assert acted.structured_content is not None

        with pytest.raises(MCPError) as error:
            await client.call_tool(
                "act",
                {
                    "capability_id": capability["id"],
                    "expected_revision": 1,
                    "input": {"template_id": "iryna", "unexpected": True},
                    "idempotency_key": "mcp-v2-invalid",
                    "session_id": session_id,
                },
            )
        assert error.value.code == -32000
        assert error.value.message == "action_unavailable"
        assert error.value.data["code"] == "action_unavailable"


def test_mcp_v2_in_memory_client_contract():
    anyio.run(_exercise_server)


def test_module_runtime_database_path_is_configurable(monkeypatch, tmp_path):
    db_path = tmp_path / "gia.db"
    monkeypatch.setenv("GIA_DB_PATH", str(db_path))
    assert _configured_db_path() == str(db_path)


def test_stateless_streamable_http_request_accepts_configured_host_port():
    allowed_hosts = _allowed_hosts(["127.0.0.1", "localhost"], 8000)
    assert allowed_hosts == ["127.0.0.1:8000", "localhost:8000"]
    app = mcp.streamable_http_app(
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={
                "host": "127.0.0.1:8000",
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "server/discover",
                "accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
        )

    assert response.status_code == 200
