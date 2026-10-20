"""Implementation of the small typed tool surface exposed to the LLM."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .brain_client import CloudMRBrainClient
from .catalogue import list_profiles
from .cloudwatch_logs import CloudWatchLogReader
from .diagnostics import summarize_pipeline
from .errors import ConfigurationError, ValidationError
from .planner import CloudMRFileResolver, ExperimentPlanner, InMemoryPlanStore
from .recipe_builder import build_queue_payload


_DEMO_SIGNAL_FILENAME = "BrainMultiSliceSignal.dat"
_DEMO_NOISE_FILENAME = "BrainMultiSliceNoise.dat"


class MROToolService:
    def __init__(
        self,
        files: CloudMRFileResolver | None = None,
        brain: CloudMRBrainClient | None = None,
        plans: InMemoryPlanStore | None = None,
        logs: CloudWatchLogReader | None = None,
    ) -> None:
        self.plans = plans or InMemoryPlanStore()
        self.files = files
        self.planner = ExperimentPlanner(files, self.plans) if files else None
        self.brain = brain
        self.logs = logs

    def list_mro_profiles(self) -> dict:
        return {"ok": True, "profiles": list_profiles()}

    def list_mro_files(self) -> dict:
        """Return a safe view of live MR Optimum files from CloudMR Brain.

        Brain's generic data catalogue does not yet assign scientific file
        roles. That classification belongs to the later metadata/compatibility
        phase.
        """
        files = self._safe_brain_files()
        return {
            "ok": True,
            "application": "MR Optimum",
            "files": files,
            "note": (
                "Files are listed from CloudMR Brain. Scientific role and "
                "compatibility validation are not configured yet."
            ),
        }

    def select_mro_files(self, signal_file_id: str, noise_file_id: str) -> dict:
        """Verify that two user selections are currently visible in Brain.

        This is an availability check only. Scientific roles and compatibility
        are validated later by the unified metadata layer.
        """
        if signal_file_id == noise_file_id:
            raise ValidationError("Signal and noise must be different CloudMR files")

        files_by_id = {file["file_id"]: file for file in self._safe_brain_files()}
        missing = [
            file_id
            for file_id in (signal_file_id, noise_file_id)
            if file_id not in files_by_id
        ]
        if missing:
            raise ValidationError(
                "Selected CloudMR file is not currently available to the shared agent: "
                + ", ".join(missing)
            )

        return {
            "ok": True,
            "application": "MR Optimum",
            "selected": {
                "signal": files_by_id[signal_file_id],
                "noise": files_by_id[noise_file_id],
            },
            "note": (
                "Selection availability is confirmed. Scientific signal/noise "
                "classification and compatibility validation are not configured yet."
            ),
        }

    def submit_brain_multislice_demo_ac_rss(self, confirm: bool = False) -> dict:
        """Queue one explicitly-confirmed AC/RSS run for the curated demo pair.

        This is a narrow end-to-end integration test, not the future general
        submission path for arbitrary selected or uploaded files.
        """
        if confirm is not True:
            raise ValidationError(
                "Set confirm=true to queue the real BrainMultiSlice AC/RSS demo job"
            )

        raw_by_name = {
            item.get("filename"): item
            for item in self._brain().list_files("MR Optimum")
            if item.get("filename")
        }
        signal = self._demo_file(raw_by_name.get(_DEMO_SIGNAL_FILENAME), "signal")
        noise = self._demo_file(raw_by_name.get(_DEMO_NOISE_FILENAME), "noise")
        alias = "mro-agent-demo-ac-rss-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

        payload = {
            "cloudapp_name": "MR Optimum",
            "mode": "mode_2",
            "alias": alias,
            "task": {
                "name": "ac",
                "queued": False,
                "version": "v0",
                "acquisition": 2,
                "type": "snr",
                "options": {
                    "reconstructor": {
                        "type": "recon",
                        "id": 0,
                        "name": "rss",
                        "options": {
                            "sensitivityMap": {
                                "type": "sensitivityMap",
                                "name": "inner",
                                "id": 2,
                                "options": {
                                    "loadSensitivity": False,
                                    "sensitivityMapMethod": "inner",
                                    "mask": {"method": "no"},
                                },
                            },
                            "correction": {"useCorrection": False},
                            "gfactor": False,
                            "signal": signal,
                            "noise": noise,
                        },
                    },
                    "agent_profile": "demo_ac_rss",
                },
                "files": ["signal", "noise"],
                "id": 0,
            },
            "output": {"coilsensitivity": False, "gfactor": False, "matlab": True},
        }
        response, unit, returned_unit_id = self._submit_to_active_mro_mode2(payload)
        return self._verified_submission_response(
            response=response,
            requested_unit=unit,
            returned_unit_id=returned_unit_id,
            extra={"profile": "demo_ac_rss", "alias": alias},
        )

    def inspect_mro_inputs(self, **arguments) -> dict:
        return self._planner().preflight(**arguments)

    def plan_mro_run(self, **arguments) -> dict:
        return {"ok": True, **self._planner().create_plan(**arguments).public_summary()}

    def submit_mro_run(self, plan_id: str) -> dict:
        plan = self.plans.get(plan_id)
        payload = build_queue_payload(plan)
        response, unit, returned_unit_id = self._submit_to_active_mro_mode2(payload)
        return self._verified_submission_response(
            response=response,
            requested_unit=unit,
            returned_unit_id=returned_unit_id,
            extra={"plan_id": plan_id, "alias": plan.alias},
        )

    def _verified_submission_response(
        self,
        *,
        response: dict,
        requested_unit: dict,
        returned_unit_id: str | None,
        extra: dict,
    ) -> dict:
        """Never report a submission as verified without unit-ID agreement."""
        pipeline_id = response.get("pipeline") or response.get("pipeline_id")
        requested_unit_id = str(requested_unit["computingUnitId"])
        result = {
            "action": "submit",
            **extra,
            "pipeline_id": pipeline_id,
            "job_id": response.get("job_id") or response.get("task_id"),
            "status": response.get("status", "queued"),
            "dispatch": response.get("dispatch"),
            "computing_unit_id": returned_unit_id,
            "computing_unit_alias": requested_unit.get("alias"),
        }
        if returned_unit_id != requested_unit_id:
            return {
                "ok": False,
                **result,
                "error": (
                    "CloudMR accepted the pipeline but did not confirm the requested "
                    "active Mode 2 computing unit; do not treat this submission as verified."
                ),
                "requested_computing_unit_id": requested_unit_id,
            }
        return {"ok": True, **result}

    def _submit_to_active_mro_mode2(self, payload: dict) -> tuple[dict, dict, str | None]:
        """Pin a queue request to the one active MR Optimum Mode 2 unit.

        The live Brain queue service treats ``mode`` as a fallback selector.
        API-based Mode 2 units intentionally have no Step Functions ARN, so
        sending both fields lets that fallback overwrite an otherwise explicit
        unit choice.  Send the exact ID alone.
        """
        unit = self._active_mro_mode2_unit()
        payload["computing_unit_id"] = unit["computingUnitId"]
        payload.pop("mode", None)
        response = self._brain().submit(payload)
        if not isinstance(response, dict):
            raise ValidationError("CloudMR Brain returned an invalid submission response")
        returned = response.get("computingUnit")
        returned_unit_id = None
        if isinstance(returned, dict) and returned.get("id"):
            returned_unit_id = str(returned["id"])
        elif response.get("computing_unit_id"):
            returned_unit_id = str(response["computing_unit_id"])
        return response, unit, returned_unit_id

    def _active_mro_mode2_unit(self) -> dict:
        units = [
            unit
            for unit in self._brain().list_computing_units("MR Optimum", "mode_2")
            if unit.get("status") == "active" and unit.get("computingUnitId")
        ]
        if len(units) != 1:
            raise ValidationError(
                "Expected exactly one active MR Optimum Mode 2 computing unit; "
                f"found {len(units)}"
            )
        return units[0]

    # Existing generic planning methods remain useful for the later catalogue
    # resolver. Both submission paths use the same active-unit pinning above.

    def get_mro_run_status(self, pipeline_id: str) -> dict:
        return {"ok": True, "action": "status", **summarize_pipeline(self._brain().get_pipeline(pipeline_id))}

    def diagnose_mro_run(self, pipeline_id: str) -> dict:
        return {
            "ok": True,
            "action": "diagnose",
            **summarize_pipeline(self._brain().get_pipeline(pipeline_id)),
        }

    def get_mro_run_logs(self, pipeline_id: str) -> dict:
        """Return a bounded, redacted CloudWatch excerpt for one pipeline.

        The reader first locates a log stream containing that exact pipeline
        identifier. It never exposes a generic log-group dump or lets the LLM
        choose an arbitrary CloudWatch stream/path.
        """
        pipeline = self._brain().get_pipeline(pipeline_id)
        summary = summarize_pipeline(pipeline)
        resolved_id = summary.get("pipeline_id")
        if not resolved_id:
            raise ValidationError("CloudMR Brain pipeline record did not include a pipeline ID")

        logs = (self.logs or CloudWatchLogReader()).read_pipeline_logs(
            str(resolved_id), summary.get("updated_at")
        )
        if not logs["found"]:
            return {
                "ok": True,
                "action": "logs",
                **summary,
                "logs_available": False,
                "message": (
                    "No MR Optimum worker log stream matching this pipeline was found "
                    "in the bounded search window. The job may not have reached the "
                    "worker yet, or CloudWatch delivery may still be in progress."
                ),
            }
        return {
            "ok": True,
            "action": "logs",
            **summary,
            "logs_available": True,
            "event_count": len(logs["events"]),
            "log_window": {"start": logs["window_start"], "end": logs["window_end"]},
            "events": logs["events"],
            "message": "Sanitized worker log excerpt is ready for technical diagnosis.",
        }

    def get_mro_result_manifest(self, pipeline_id: str) -> dict:
        pipeline = self._brain().get_pipeline(pipeline_id)
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

    # ------------------------------------------------------------------
    # Internal dependency accessors and safe data shaping

    def _brain(self) -> CloudMRBrainClient:
        if self.brain is None:
            raise ConfigurationError("CloudMR Brain credentials are not configured")
        return self.brain

    def _files(self) -> CloudMRFileResolver:
        if self.files is None:
            raise ConfigurationError("CloudMR Brain file catalogue is not configured")
        return self.files

    def _planner(self) -> ExperimentPlanner:
        if self.planner is None:
            raise ConfigurationError("CloudMR Brain file catalogue is not configured")
        return self.planner

    def _safe_brain_files(self) -> list[dict]:
        """Allowlist Brain data records for all LLM-facing file tools."""
        raw_files = self._brain().list_files("MR Optimum")
        files = []
        for item in raw_files:
            file_id = item.get("id")
            filename = item.get("filename")
            if not file_id or not filename:
                continue
            files.append(
                {
                    "file_id": str(file_id),
                    "filename": str(filename),
                    "size": item.get("size"),
                    "status": item.get("status", "unknown"),
                    "source": "shared_demo"
                    if item.get("is_demo_data") is True
                    else "shared_agent_account",
                }
            )
        return files

    @staticmethod
    def _demo_file(item: dict | None, role: str) -> dict:
        if not isinstance(item, dict):
            raise ValidationError(f"Curated BrainMultiSlice {role} demo file is unavailable")
        raw_location = item.get("location")
        try:
            location = json.loads(raw_location) if isinstance(raw_location, str) else raw_location
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Curated BrainMultiSlice {role} location is invalid") from exc
        if not isinstance(location, dict) or not location.get("Bucket") or not location.get("Key"):
            raise ValidationError(f"Curated BrainMultiSlice {role} has no usable Brain location")
        if not item.get("id") or not item.get("filename"):
            raise ValidationError(f"Curated BrainMultiSlice {role} record is incomplete")

        # These properties were verified for this exact curated demo pair.
        # General user-selected files must instead use the later metadata layer.
        return {
            "type": "file",
            "id": item["id"],
            "options": {
                "type": "s3",
                "filename": item["filename"],
                "options": {},
                "multiraid": True,
                "bucket": location["Bucket"],
                "key": location["Key"],
                "vendor": "Siemens",
            },
        }
