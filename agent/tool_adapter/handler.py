"""Lambda entry point for the MR Optimum tool adapter.

The surrounding AgentCore Gateway target should map an MCP/tool call to the
simple {"tool": ..., "arguments": {...}} event used here.
"""

from __future__ import annotations

import os

from mro_agent.brain_client import BrainCredentials, CloudMRBrainClient
from mro_agent.errors import AgentError
from mro_agent.runtime import MROAgentRuntime
from mro_agent.tool_service import MROToolService


def build_runtime() -> MROAgentRuntime:
    brain = None
    if all(os.environ.get(key) for key in ("CLOUDMR_BRAIN_ROOT", "CLOUDMR_EMAIL", "CLOUDMR_PASSWORD")):
        brain = CloudMRBrainClient(
            BrainCredentials(
                root=os.environ["CLOUDMR_BRAIN_ROOT"],
                email=os.environ["CLOUDMR_EMAIL"],
                password=os.environ["CLOUDMR_PASSWORD"],
            )
        )
    # The CloudMR-Brain-backed file resolver is deliberately not substituted
    # with a local registry. Wire it here only after the authenticated catalogue
    # adapter has been implemented.
    return MROAgentRuntime(MROToolService(brain=brain))


def lambda_handler(event: dict, _context=None) -> dict:
    tool = event.get("tool")
    arguments = event.get("arguments", {})
    if not isinstance(tool, str) or not isinstance(arguments, dict):
        return {"ok": False, "error": "Expected event with string 'tool' and object 'arguments'"}
    try:
        return build_runtime().invoke_tool(tool, arguments)
    except (AgentError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
