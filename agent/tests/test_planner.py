from pathlib import Path

import pytest

from mro_agent.dataset_registry import DatasetRegistry
from mro_agent.errors import ValidationError
from mro_agent.planner import ExperimentPlanner, InMemoryPlanStore
from mro_agent.recipe_builder import build_queue_payload


@pytest.fixture()
def planner():
    registry = DatasetRegistry.from_json(
        Path(__file__).parents[1] / "data" / "datasets.example.json"
    )
    return ExperimentPlanner(registry, InMemoryPlanStore())


def test_ac_profile_requires_matching_noise(planner):
    plan = planner.create_plan("ac_rss", "signal-example", "noise-example")
    payload = build_queue_payload(plan)

    assert payload["cloudapp_name"] == "MR Optimum"
    assert payload["mode"] == "mode_2"
    assert payload["task"]["name"] == "ac"
    assert payload["task"]["files"] == ["signal", "noise"]
    assert payload["task"]["options"]["reconstructor"]["options"]["signal"]["id"] == "signal-example"
    assert "bucket" not in plan.public_summary()["inputs"]


def test_mr_profile_requires_replicas(planner):
    with pytest.raises(ValidationError, match="replica_count"):
        planner.create_plan("mr_rss", "signal-example")


def test_fa_profile_requires_fa_map(planner):
    with pytest.raises(ValidationError, match="flip-angle"):
        planner.create_plan("ac_rss_fa90", "signal-example", "noise-example")
