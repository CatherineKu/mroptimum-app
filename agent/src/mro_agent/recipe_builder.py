"""Build the constrained Mode 2 task payload accepted by CloudMR Brain."""

from __future__ import annotations

from copy import deepcopy

from .models import PlannedRun


def build_queue_payload(plan: PlannedRun) -> dict:
    """Return a Brain queue_job payload from a previously validated plan.

    Dataset `brain_file` references remain inside the trusted tool adapter and
    never form part of a user-visible plan or LLM tool response.
    """
    reconstructor_options: dict = {
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
        "signal": _file(plan.signal),
    }
    files = ["signal"]
    if plan.noise:
        reconstructor_options["noise"] = _file(plan.noise)
        files.append("noise")
    if plan.flip_angle:
        # The computation integration will translate this approved input into
        # the mrotools --fa-map invocation.  Keep units/provenance in the task.
        reconstructor_options["flipAngle"] = _file(plan.flip_angle)
        files.append("flipAngle")

    return {
        "cloudapp_name": "MR Optimum",
        "mode": "mode_2",
        "alias": plan.alias,
        "task": {
            "name": plan.profile.method,
            "queued": False,
            "version": "v0",
            "acquisition": 2 if plan.profile.method == "mr" else 1,
            "type": "snr",
            "options": {
                "reconstructor": {
                    "type": "recon",
                    "id": 0,
                    "name": plan.profile.reconstructor,
                    "options": reconstructor_options,
                },
                "agent_profile": plan.profile.profile_id,
            },
            "files": files,
            "id": 0,
        },
        "output": deepcopy(plan.profile.output),
    }


def _file(dataset) -> dict:
    return {
        "type": "file",
        "id": dataset.dataset_id,
        "options": deepcopy(dataset.brain_file),
    }
