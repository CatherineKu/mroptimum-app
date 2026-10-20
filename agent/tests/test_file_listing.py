import pytest

from mro_agent.errors import ValidationError
from mro_agent.tool_service import MROToolService


class FakeBrain:
    def __init__(self):
        self.submitted_payload = None

    def list_files(self, cloudapp_name):
        assert cloudapp_name == "MR Optimum"
        return [
            {
                "id": "demo-signal-id",
                "filename": "BrainMultiSliceSignal.dat",
                "size": 82123456,
                "status": "available",
                "is_demo_data": True,
                "location": '{"Bucket":"private","Key":"do-not-leak"}',
                "link": "https://signed.example.invalid/do-not-leak",
                "user_id": "cloudmr-admin",
            },
            {
                "id": "shared-noise-id",
                "filename": "BrainMultiSliceNoise.dat",
                "size": 81123456,
                "status": "available",
                "location": '{"Bucket":"private","Key":"do-not-leak-noise"}',
            },
        ]

    def list_computing_units(self, app_name, mode):
        assert (app_name, mode) == ("MR Optimum", "mode_2")
        return [
            {
                "computingUnitId": "active-unit-id",
                "alias": "test-mode2",
                "mode": "mode_2",
                "status": "active",
            }
        ]

    def submit(self, payload):
        self.submitted_payload = payload
        return {
            "pipeline": "pipeline-test",
            "job_id": "job-test",
            "dispatch": "api",
            "computingUnit": {"id": "active-unit-id", "alias": "test-mode2"},
        }


def test_list_mro_files_returns_only_safe_brain_fields():
    result = MROToolService(brain=FakeBrain()).list_mro_files()

    assert result["ok"] is True
    assert result["application"] == "MR Optimum"
    assert result["files"] == [
        {
            "file_id": "demo-signal-id",
            "filename": "BrainMultiSliceSignal.dat",
            "size": 82123456,
            "status": "available",
            "source": "shared_demo",
        },
        {
            "file_id": "shared-noise-id",
            "filename": "BrainMultiSliceNoise.dat",
            "size": 81123456,
            "status": "available",
            "source": "shared_agent_account",
        },
    ]


def test_select_mro_files_revalidates_live_file_ids():
    result = MROToolService(brain=FakeBrain()).select_mro_files(
        signal_file_id="demo-signal-id",
        noise_file_id="shared-noise-id",
    )

    assert result["ok"] is True
    assert result["selected"]["signal"]["filename"] == "BrainMultiSliceSignal.dat"
    assert "location" not in result["selected"]["signal"]
    assert "link" not in result["selected"]["signal"]


def test_select_mro_files_rejects_unknown_or_duplicate_ids():
    tools = MROToolService(brain=FakeBrain())
    with pytest.raises(ValidationError, match="not currently available"):
        tools.select_mro_files("not-a-brain-file", "shared-noise-id")
    with pytest.raises(ValidationError, match="must be different"):
        tools.select_mro_files("demo-signal-id", "demo-signal-id")


def test_submit_demo_requires_confirmation_and_uses_brain_locations():
    brain = FakeBrain()
    tools = MROToolService(brain=brain)

    with pytest.raises(ValidationError, match="confirm=true"):
        tools.submit_brain_multislice_demo_ac_rss()

    result = tools.submit_brain_multislice_demo_ac_rss(confirm=True)

    assert result["ok"] is True
    assert result["pipeline_id"] == "pipeline-test"
    assert "mode" not in brain.submitted_payload
    assert brain.submitted_payload["computing_unit_id"] == "active-unit-id"
    assert result["computing_unit_id"] == "active-unit-id"
    options = brain.submitted_payload["task"]["options"]["reconstructor"]["options"]
    assert options["signal"]["options"]["bucket"] == "private"
    assert options["signal"]["options"]["multiraid"] is True
    assert "presigned_url" not in options["signal"]["options"]


def test_submit_demo_refuses_to_claim_verification_for_a_mismatched_unit():
    class MismatchedBrain(FakeBrain):
        def submit(self, payload):
            self.submitted_payload = payload
            return {
                "pipeline": "pipeline-test",
                "computingUnit": {"id": "wrong-unit-id"},
            }

    result = MROToolService(brain=MismatchedBrain()).submit_brain_multislice_demo_ac_rss(
        confirm=True
    )

    assert result["ok"] is False
    assert result["computing_unit_id"] == "wrong-unit-id"
    assert result["requested_computing_unit_id"] == "active-unit-id"
