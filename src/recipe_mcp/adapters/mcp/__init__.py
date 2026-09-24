"""MCP server exposing the four household recipe tools over stdio."""

from recipe_mcp.adapters.mcp.server import TOOL_NAMES, build_server

__all__ = ["TOOL_NAMES", "build_server"]
