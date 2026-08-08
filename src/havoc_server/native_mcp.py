"""Native MCP tools rendered from a contextual GIA capability set.

The renderer creates one tool per advertised capability.  Each generated
handler closes over the capability ID and scope, so the client cannot replace
the command binding with an action name.  The handler still delegates to the
same caller-supplied reference monitor used by GAS.

Native tools should be installed on a context-specific MCP server (or another
isolated tool registry).  Installing a session's capabilities into the shared
module-level GAS server would make stale tools look globally available.

Originally relocated from ``src/gia/renderers/native_mcp.py`` during the PR 17
transport work, then made Havoc-owned here in RS-03
(`docs/GIA-REPOSITORY-SPLIT-PLAN.md`): nothing outside Havoc ever consumed
this renderer (the live server wires only the generic ``gas_mcp.install_gas_mcp``
— see ``havoc_server.app.build_mcp_server``), so ``gas_mcp`` staying
genuinely GIA-free per RS-03's goal meant moving the renderer to its one
real consumer rather than inventing a second reusable-but-unused ``gia_mcp``
package for it. No compatibility shim was left at either old import path
(``gas_mcp.native`` or ``gia.renderers.native_mcp``); update callers to
import from here directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Callable

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from gia_core.capabilities import Capability, CapabilitySet


NativeInvoker = Callable[..., Any]


@dataclass(frozen=True)
class NativeMcpTool:
    """One generated MCP tool and the capability it represents."""

    name: str
    title: str
    description: str
    capability: Capability
    annotations: ToolAnnotations
    handler: Callable[..., Any]

    @property
    def capability_id(self) -> str:
        """Expose the bound capability ID without making it an input field."""
        return self.capability.id

    def install(self, server: MCPServer) -> None:
        """Register this tool with an MCP server."""
        server.add_tool(
            self.handler,
            name=self.name,
            title=self.title,
            description=self.description,
            annotations=self.annotations,
            structured_output=False,
        )


class NativeMcpRenderer:
    """Render filtered, per-capability MCP tools from the shared IR."""

    def __init__(self, *, tool_prefix: str = "gia"):
        if not isinstance(tool_prefix, str) or not tool_prefix.strip():
            raise ValueError("tool_prefix must be a non-empty string.")
        self.tool_prefix = tool_prefix.strip()

    def render(
        self,
        capability_set: CapabilitySet,
        invoker: NativeInvoker,
    ) -> list[NativeMcpTool]:
        """Create one native tool per command in the already-filtered set.

        ``invoker`` is called with keyword arguments ``capability_id``,
        ``expected_revision``, ``input``, ``idempotency_key``, ``session_id``,
        and ``scope``.  It should delegate to the same execution service as
        ``gia_gas_adapter.GiaGasAdapter.act``.
        """
        if not callable(invoker):
            raise TypeError("invoker must be callable.")
        tools: list[NativeMcpTool] = []
        names: set[str] = set()
        for capability in capability_set.commands:
            name = self._tool_name(capability)
            if name in names:
                raise ValueError(f"Capability tool name collision: {name}")
            names.add(name)
            tools.append(self._tool(capability_set, capability, name, invoker))
        return tools

    def install(
        self,
        server: MCPServer,
        capability_set: CapabilitySet,
        invoker: NativeInvoker,
    ) -> list[NativeMcpTool]:
        """Render and install a capability set on an isolated MCP server."""
        tools = self.render(capability_set, invoker)
        for tool in tools:
            tool.install(server)
        return tools

    def _tool(
        self,
        capability_set: CapabilitySet,
        capability: Capability,
        name: str,
        invoker: NativeInvoker,
    ) -> NativeMcpTool:
        # The command schema remains nested under ``input``.  Field metadata
        # lets the MCP SDK publish that exact schema while the wrapper adds
        # only the execution envelope required by the reference monitor.
        input_annotation = Annotated[
            dict[str, Any],
            Field(json_schema_extra=dict(capability.input_schema)),
        ]

        def handler(
            input: dict[str, Any],
            expected_revision: int,
            idempotency_key: str,
            session_id: str,
        ) -> Any:
            return invoker(
                capability_id=capability.id,
                expected_revision=expected_revision,
                input=input,
                idempotency_key=idempotency_key,
                session_id=session_id,
                scope=capability_set.scope,
            )

        handler.__name__ = name
        handler.__qualname__ = name
        handler.__doc__ = (
            f"Execute the advertised {capability.command} capability "
            f"{capability.id}."
        )
        handler.__annotations__ = {
            "input": input_annotation,
            "expected_revision": int,
            "idempotency_key": str,
            "session_id": str,
            "return": Any,
        }
        annotations = ToolAnnotations(
            readOnlyHint=not capability.effects.mutating,
            destructiveHint=capability.effects.destructive,
            idempotentHint=capability.effects.idempotent,
            openWorldHint=False,
        )
        return NativeMcpTool(
            name=name,
            title=capability.title,
            description=(
                f"Execute {capability.command} through the GIA reference "
                "monitor; the advertised capability ID is bound by this tool."
            ),
            capability=capability,
            annotations=annotations,
            handler=handler,
        )

    def _tool_name(self, capability: Capability) -> str:
        command = "".join(
            character if character.isalnum() or character == "_" else "_"
            for character in capability.command
        )
        # The suffix remains opaque and deterministic while keeping names
        # below MCP's 64-character recommendation for long command names.
        suffix = capability.id.removeprefix("cap-")[-16:]
        return f"{self.tool_prefix}_{command}_{suffix}"
