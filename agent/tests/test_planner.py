import pytest

from mro_agent.errors import ValidationError
from mro_agent.models import CloudMRFile, FileRole
from mro_agent.planner import ExperimentPlanner, InMemoryPlanStore
from mro_agent.recipe_builder import build_queue_payload


class FakeCloudMRFiles:
    """Test-only stand-in for the future authenticated Brain catalogue."""

    def __init__(self):
        self.records = {
            "signal-file": CloudMRFile(
                file_id="signal-file",
                display_name="signal.dat",
                role=FileRole.SIGNAL,
                format="dat",
                vendor="Siemens",
                metadata={"coil_count": 16, "replica_count": 1, "has_orientation": True},
                brain_file={
                    "type": "file",
                    "id": "cloudmr-signal-id",
                    "options": {
                        "type": "s3",
                        "filename": "signal.dat",
                        "bucket": "brain-managed-bucket",
                        "key": "authorized/signal.dat",
                        "vendor": "Siemens",
                        "multiraid": True,
                        "options": {},
                    },
                },
            ),
            "noise-file": CloudMRFile(
                file_id="noise-file",
                display_name="noise.dat",
                role=FileRole.NOISE,
                format="dat",
                vendor="Siemens",
                metadata={"coil_count": 16, "replica_count": 1, "has_orientation": True},
                brain_file={
                    "type": "file",
                    "id": "cloudmr-noise-id",
                    "options": {
                        "type": "s3",
                        "filename": "noise.dat",
                        "bucket": "brain-managed-bucket",
                        "key": "authorized/noise.dat",
                        "vendor": "Siemens",
                        "multiraid": True,
                        "options": {},
                    },
                },
            ),
        }

    def get(self, file_id, expected_role=None):
        record = self.records[file_id]
        if expected_role and record.role != expected_role:
            raise ValidationError("Selected CloudMR file has the wrong role")
        return record


@pytest.fixture()
def planner():
    return ExperimentPlanner(FakeCloudMRFiles(), InMemoryPlanStore())


def test_ac_profile_requires_matching_noise(planner):
    plan = planner.create_plan("ac_rss", "signal-file", "noise-file")
    payload = build_queue_payload(plan)

    assert payload["cloudapp_name"] == "MR Optimum"
    assert payload["mode"] == "mode_2"
    assert payload["task"]["name"] == "ac"
    assert payload["task"]["files"] == ["signal", "noise"]
    assert payload["task"]["options"]["reconstructor"]["options"]["signal"]["id"] == "cloudmr-signal-id"
    assert "presigned_url" not in payload["task"]["options"]["reconstructor"]["options"]["signal"]["options"]
    assert "bucket" not in plan.public_summary()["inputs"]


def test_mr_profile_requires_replicas(planner):
    with pytest.raises(ValidationError, match="replica_count"):
        planner.create_plan("mr_rss", "signal-file")


def test_fa_profile_requires_fa_map(planner):
    with pytest.raises(ValidationError, match="flip-angle"):
        planner.create_plan("ac_rss_fa90", "signal-file", "noise-file")
