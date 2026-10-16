"""Typed models used at the agent boundary.

These models intentionally expose dataset IDs rather than bucket/key pairs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DatasetRole(str, Enum):
    SIGNAL = "signal"
    NOISE = "noise"
    FLIP_ANGLE = "flip_angle"


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    display_name: str
    role: DatasetRole
    format: str
    vendor: str
    metadata: dict[str, Any]
    brain_file: dict[str, Any]

    def public_summary(self) -> dict[str, Any]:
        """Return only metadata appropriate for the LLM/user-facing layer."""
        safe_metadata_keys = {
            "coil_count",
            "replica_count",
            "fa_units",
            "has_orientation",
            "acceleration",
            "has_reference_data",
            "has_sensitivity_map",
        }
        return {
            "dataset_id": self.dataset_id,
            "display_name": self.display_name,
            "role": self.role.value,
            "format": self.format,
            "vendor": self.vendor,
            "metadata": {
                key: value
                for key, value in self.metadata.items()
                if key in safe_metadata_keys
            },
        }


@dataclass(frozen=True)
class ExperimentProfile:
    profile_id: str
    title: str
    method: str
    reconstructor: str
    requires_noise: bool = False
    requires_flip_angle: bool = False
    requires_replicas: bool = False
    description: str = ""
    output: dict[str, Any] = field(default_factory=dict)

    def public_summary(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "title": self.title,
            "method": self.method,
            "reconstructor": self.reconstructor,
            "required_inputs": [
                "signal",
                *(["noise"] if self.requires_noise else []),
                *(["flip_angle"] if self.requires_flip_angle else []),
            ],
            "requires_repeated_signal_acquisitions": self.requires_replicas,
            "description": self.description,
        }


@dataclass
class PlannedRun:
    plan_id: str
    profile: ExperimentProfile
    signal: DatasetRecord
    noise: DatasetRecord | None = None
    flip_angle: DatasetRecord | None = None
    alias: str | None = None
    warnings: list[str] = field(default_factory=list)

    def public_summary(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "profile": self.profile.public_summary(),
            "inputs": {
                "signal_dataset_id": self.signal.dataset_id,
                "noise_dataset_id": self.noise.dataset_id if self.noise else None,
                "flip_angle_dataset_id": self.flip_angle.dataset_id if self.flip_angle else None,
            },
            "warnings": self.warnings,
            "requires_confirmation": True,
        }
