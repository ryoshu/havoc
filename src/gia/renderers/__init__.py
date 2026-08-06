"""Alternative renderings of the transport-independent GIA capability IR."""

from .debug import DebugRenderer, render_debug
from .native_mcp import NativeMcpRenderer, NativeMcpTool
from .protocol import CapabilityRenderer

__all__ = [
    "CapabilityRenderer",
    "DebugRenderer",
    "NativeMcpRenderer",
    "NativeMcpTool",
    "render_debug",
]

