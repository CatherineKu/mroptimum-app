"""Implementation of the small typed tool surface exposed to the LLM."""

from __future__ import annotations

from .brain_client import CloudMRBrainClient
from .catalogue import list_profiles
from .dataset_registry import DatasetRegistry
from .diagnostics import summarize_pipeline
from .planner import ExperimentPlanner, InMemoryPlanStore
from .recipe_builder import build_queue_payload


class MROToolService:
    def __init__(
        self,
        registry: DatasetRegistry,
        brain: CloudMRBrainClient,
        plans: InMemoryPlanStore | None = None,
    ) -> None:
        self.registry = registry
        self.plans = plans or InMemoryPlanStore()
        self.planner = ExperimentPlanner(registry, self.plans)
        self.brain = brain

    def list_mro_profiles(self) -> dict:
        return {"ok": True, "profiles": list_profiles()}

    def list_mro_datasets(self, role: str | None = None) -> dict:
        return {"ok": True, "datasets": self.registry.list_public(role)}

    def inspect_mro_inputs(self, **arguments) -> dict:
        return self.planner.preflight(**arguments)

    def plan_mro_run(self, **arguments) -> dict:
        return {"ok": True, **self.planner.create_plan(**arguments).public_summary()}

    def submit_mro_run(self, plan_id: str) -> dict:
        plan = self.plans.get(plan_id)
        response = self.brain.submit(build_queue_payload(plan))
        return {
            "ok": True,
            "action": "submit",
            "plan_id": plan_id,
            "pipeline_id": response.get("pipeline") or response.get("pipeline_id"),
            "job_id": response.get("job_id") or response.get("task_id"),
            "alias": plan.alias,
            "status": response.get("status", "queued"),
        }

    def get_mro_run_status(self, pipeline_id: str) -> dict:
        return {"ok": True, "action": "status", **summarize_pipeline(self.brain.get_pipeline(pipeline_id))}

    def diagnose_mro_run(self, pipeline_id: str) -> dict:
        return {
            "ok": True,
            "action": "diagnose",
            **summarize_pipeline(self.brain.get_pipeline(pipeline_id)),
        }

    def get_mro_result_manifest(self, pipeline_id: str) -> dict:
        pipeline = self.brain.get_pipeline(pipeline_id)
        summary = summarize_pipeline(pipeline)
        return {
            "ok": True,
            "action": "result_manifest",
            "pipeline_id": summary["pipeline_id"],
            "status": summary["status"],
            "result_available": summary["status"] == "completed" and bool(
                pipeline.get("results") or pipeline.get("output")
            ),
            "message": "Result location is intentionally withheld from the LLM; retrieve it through an authorized result-download service.",
        }
