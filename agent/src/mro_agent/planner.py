"""Validate an MR Optimum request before it can become a Brain job."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from .catalogue import PROFILES
from .errors import NotFoundError, ValidationError
from .models import CloudMRFile, FileRole, PlannedRun


class CloudMRFileResolver(Protocol):
    """Trusted bridge from a CloudMR file ID to validated file metadata.

    The production implementation must query CloudMR Brain using the calling
    user's identity and enforce ownership/demo-data access before returning a
    record. It intentionally has no local JSON or S3 implementation.
    """

    def get(self, file_id: str, expected_role: FileRole | None = None) -> CloudMRFile: ...


class InMemoryPlanStore:
    """Development-only plan storage.

    Replace this with DynamoDB before deploying.  A Lambda execution environment
    is ephemeral and must not be trusted as a durable approval/audit store.
    """

    def __init__(self) -> None:
        self._plans: dict[str, PlannedRun] = {}

    def save(self, plan: PlannedRun) -> None:
        self._plans[plan.plan_id] = plan

    def get(self, plan_id: str) -> PlannedRun:
        try:
            return self._plans[plan_id]
        except KeyError as exc:
            raise NotFoundError(
                f"Plan '{plan_id}' was not found. Create a new plan before submitting."
            ) from exc


class ExperimentPlanner:
    def __init__(self, files: CloudMRFileResolver, plans: InMemoryPlanStore):
        self.files = files
        self.plans = plans

    def preflight(
        self,
        profile_id: str,
        signal_file_id: str,
        noise_file_id: str | None = None,
        flip_angle_file_id: str | None = None,
    ) -> dict:
        plan = self._build_plan(
            profile_id,
            signal_file_id,
            noise_file_id,
            flip_angle_file_id,
            persist=False,
        )
        return {
            "ok": True,
            "profile_id": profile_id,
            "inputs": plan.public_summary()["inputs"],
            "warnings": plan.warnings,
        }

    def create_plan(
        self,
        profile_id: str,
        signal_file_id: str,
        noise_file_id: str | None = None,
        flip_angle_file_id: str | None = None,
        alias: str | None = None,
    ) -> PlannedRun:
        plan = self._build_plan(
            profile_id,
            signal_file_id,
            noise_file_id,
            flip_angle_file_id,
            persist=True,
        )
        plan.alias = alias or self._default_alias(profile_id)
        return plan

    def _build_plan(
        self,
        profile_id: str,
        signal_file_id: str,
        noise_file_id: str | None,
        flip_angle_file_id: str | None,
        persist: bool,
    ) -> PlannedRun:
        try:
            profile = PROFILES[profile_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown MR Optimum profile '{profile_id}'") from exc

        signal = self.files.get(signal_file_id, FileRole.SIGNAL)
        noise = self._optional_file(noise_file_id, FileRole.NOISE)
        flip_angle = self._optional_file(flip_angle_file_id, FileRole.FLIP_ANGLE)
        warnings: list[str] = []

        if profile.requires_noise and noise is None:
            raise ValidationError(f"Profile '{profile_id}' requires a noise file")
        if not profile.requires_noise and noise is not None:
            raise ValidationError(f"Profile '{profile_id}' does not accept a noise file")
        if profile.requires_flip_angle and flip_angle is None:
            raise ValidationError(f"Profile '{profile_id}' requires a flip-angle dataset")
        if not profile.requires_flip_angle and flip_angle is not None:
            raise ValidationError(f"Profile '{profile_id}' does not accept a flip-angle dataset")

        if noise is not None:
            signal_coils = signal.metadata.get("coil_count")
            noise_coils = noise.metadata.get("coil_count")
            if signal_coils is None or noise_coils is None:
                raise ValidationError("Signal and noise datasets must declare coil_count metadata")
            if signal_coils != noise_coils:
                raise ValidationError(
                    "Signal and noise coil_count values must match for noise covariance"
                )

        if profile.requires_replicas:
            replicas = signal.metadata.get("replica_count", 0)
            if not isinstance(replicas, int) or replicas < 2:
                raise ValidationError(
                    "Multiple-replica SNR requires a signal dataset with replica_count >= 2"
                )

        if flip_angle is not None and flip_angle.metadata.get("fa_units") != "degrees":
            raise ValidationError("Flip-angle data must be registered with fa_units='degrees'")

        if not signal.metadata.get("has_orientation", False):
            warnings.append("Signal orientation metadata is absent; verify geometry before submission.")

        plan = PlannedRun(
            plan_id=f"mro-plan-{uuid4()}",
            profile=profile,
            signal=signal,
            noise=noise,
            flip_angle=flip_angle,
            warnings=warnings,
        )
        if persist:
            self.plans.save(plan)
        return plan

    def _optional_file(self, file_id: str | None, role: FileRole):
        return self.files.get(file_id, role) if file_id else None

    @staticmethod
    def _default_alias(profile_id: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"mro-agent-{profile_id}-{timestamp}"
