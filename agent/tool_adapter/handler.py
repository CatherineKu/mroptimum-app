"""Lambda entry point for the MR Optimum tool adapter.

The surrounding AgentCore Gateway target should map an MCP/tool call to the
simple {"tool": ..., "arguments": {...}} event used here.
"""

from __future__ import annotations

import os
from pathlib import Path

from mro_agent.brain_client import BrainCredentials, CloudMRBrainClient
from mro_agent.dataset_registry import DatasetRegistry
from mro_agent.errors import AgentError
from mro_agent.runtime import MROAgentRuntime
from mro_agent.tool_service import MROToolService


def build_runtime() -> MROAgentRuntime:
    registry_path = os.environ.get(
        "MRO_DATASET_REGISTRY_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "datasets.json"),
    )
    registry = DatasetRegistry.from_json(registry_path)
    brain = CloudMRBrainClient(
        BrainCredentials(
            root=os.environ.get("CLOUDMR_BRAIN_ROOT", ""),
            email=os.environ.get("CLOUDMR_EMAIL", ""),
            password=os.environ.get("CLOUDMR_PASSWORD", ""),
        )
    )
    return MROAgentRuntime(MROToolService(registry, brain))


def lambda_handler(event: dict, _context=None) -> dict:
    tool = event.get("tool")
    arguments = event.get("arguments", {})
    if not isinstance(tool, str) or not isinstance(arguments, dict):
        return {"ok": False, "error": "Expected event with string 'tool' and object 'arguments'"}
    try:
        return build_runtime().invoke_tool(tool, arguments)
    except (AgentError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
