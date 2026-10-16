"""Thin AgentCore-facing runtime adapter.

This module is model/framework neutral.  The later AgentCore Runtime entry point
can provide the tool schemas and dispatch validated tool calls through Gateway.
"""

from __future__ import annotations

from .errors import AgentError
from .tool_service import MROToolService

SYSTEM_INSTRUCTIONS = """You are the MR Optimum technical workflow assistant.
Use only the declared tools. Do not fabricate a scientific method, raw file
location, job status, or result. Plan before submission and request explicit
user confirmation before submit_mro_run. Provide technical workflow diagnosis,
not medical or clinical interpretation."""


class MROAgentRuntime:
    def __init__(self, tools: MROToolService):
        self.tools = tools

    def invoke_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Dispatch a validated tool name for local tests or a Gateway adapter."""
        tool = getattr(self.tools, name, None)
        if tool is None or not callable(tool) or name.startswith("_"):
            return {"ok": False, "error": f"Unknown MR Optimum tool '{name}'"}
        try:
            return tool(**(arguments or {}))
        except AgentError as exc:
            return {"ok": False, "error": str(exc)}
