"""PR10 coverage for renderers over the shared capability IR."""

from __future__ import annotations

import anyio

from mcp.client import Client
from mcp.server import MCPServer

from havoc_server.runtime import GameRuntime, build_gas_service
from gia_core.renderers import DebugRenderer
from havoc_server.native_mcp import NativeMcpRenderer


def _example_input(capability) -> dict:
    values = {}
    for name, schema in capability.input_schema.get("properties", {}).items():
        if "const" in schema:
            values[name] = schema["const"]
        elif schema.get("enum"):
            values[name] = schema["enum"][0]
    return values


def test_debug_renderer_is_deterministic_and_round_trips():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        capability_set = runtime.capability_set(session_id)
        renderer = DebugRenderer()

        rendered = renderer.render(capability_set)
        assert rendered["scope"] == capability_set.scope
        assert renderer.render_json(capability_set) == renderer.render_json(capability_set)
        assert capability_set.model_validate(rendered) == capability_set
    finally:
        runtime.ctx.db.close()


def test_gas_and_native_renderers_preserve_the_same_capability_ids():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    try:
        session_id = gas.create_session().data["id"]
        capability_set = runtime.capability_set(session_id)
        gas_response = gas.get(f"gia://session/{session_id}")
        native = NativeMcpRenderer().render(capability_set, lambda **kwargs: kwargs)

        expected_ids = {command.id for command in capability_set.commands}
        assert {command.id for command in gas_response.commands} == expected_ids
        assert {tool.capability_id for tool in native} == expected_ids
        assert all(tool.capability.effects == next(
            command.effects for command in capability_set.commands
            if command.id == tool.capability_id
        ) for tool in native)
    finally:
        runtime.ctx.db.close()


def test_native_renderer_filters_and_registers_contextual_mcp_tools():
    runtime = GameRuntime()
    gas = build_gas_service(runtime)
    calls = []
    try:
        session_id = gas.create_session().data["id"]
        capability_set = runtime.capability_set(session_id)
        selected = capability_set.model_copy(update={"commands": capability_set.commands[:1]})
        server = MCPServer()
        renderer = NativeMcpRenderer()
        tools = renderer.install(
            server,
            selected,
            lambda **kwargs: calls.append(kwargs) or {"ok": True},
        )

        async def exercise():
            async with Client(server) as client:
                listed = (await client.list_tools()).tools
                assert [tool.name for tool in listed] == [tools[0].name]
                schema = listed[0].input_schema
                assert schema["properties"]["input"]["properties"] == selected.commands[0].input_schema["properties"]
                assert schema["properties"]["input"]["required"] == selected.commands[0].input_schema["required"]
                result = await client.call_tool(
                    tools[0].name,
                    {
                        "input": _example_input(selected.commands[0]),
                        "expected_revision": selected.state_revision,
                        "idempotency_key": "native-renderer-test",
                        "session_id": session_id,
                    },
                )
                assert result.is_error is False

        anyio.run(exercise)
        assert calls == [{
            "capability_id": selected.commands[0].id,
            "expected_revision": selected.state_revision,
            "input": _example_input(selected.commands[0]),
            "idempotency_key": "native-renderer-test",
            "session_id": session_id,
            "scope": selected.scope,
        }]
    finally:
        runtime.ctx.db.close()
