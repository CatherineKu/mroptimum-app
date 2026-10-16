"""Validate an MR Optimum request before it can become a Brain job."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .catalogue import PROFILES
from .dataset_registry import DatasetRegistry
from .errors import NotFoundError, ValidationError
from .models import DatasetRole, PlannedRun


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
    def __init__(self, registry: DatasetRegistry, plans: InMemoryPlanStore):
        self.registry = registry
        self.plans = plans

    def preflight(
        self,
        profile_id: str,
        signal_dataset_id: str,
        noise_dataset_id: str | None = None,
        flip_angle_dataset_id: str | None = None,
    ) -> dict:
        plan = self._build_plan(
            profile_id,
            signal_dataset_id,
            noise_dataset_id,
            flip_angle_dataset_id,
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
        signal_dataset_id: str,
        noise_dataset_id: str | None = None,
        flip_angle_dataset_id: str | None = None,
        alias: str | None = None,
    ) -> PlannedRun:
        plan = self._build_plan(
            profile_id,
            signal_dataset_id,
            noise_dataset_id,
            flip_angle_dataset_id,
            persist=True,
        )
        plan.alias = alias or self._default_alias(profile_id)
        return plan

    def _build_plan(
        self,
        profile_id: str,
        signal_dataset_id: str,
        noise_dataset_id: str | None,
        flip_angle_dataset_id: str | None,
        persist: bool,
    ) -> PlannedRun:
        try:
            profile = PROFILES[profile_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown MR Optimum profile '{profile_id}'") from exc

        signal = self.registry.get(signal_dataset_id, DatasetRole.SIGNAL)
        noise = self._optional_dataset(noise_dataset_id, DatasetRole.NOISE)
        flip_angle = self._optional_dataset(flip_angle_dataset_id, DatasetRole.FLIP_ANGLE)
        warnings: list[str] = []

        if profile.requires_noise and noise is None:
            raise ValidationError(f"Profile '{profile_id}' requires a noise dataset")
        if not profile.requires_noise and noise is not None:
            raise ValidationError(f"Profile '{profile_id}' does not accept a noise dataset")
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

    def _optional_dataset(self, dataset_id: str | None, role: DatasetRole):
        return self.registry.get(dataset_id, role) if dataset_id else None

    @staticmethod
    def _default_alias(profile_id: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"mro-agent-{profile_id}-{timestamp}"
