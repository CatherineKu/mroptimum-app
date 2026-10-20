from mro_agent.cloudwatch_logs import CloudWatchLogConfig, CloudWatchLogReader
from mro_agent.tool_service import MROToolService


class FakeCloudWatch:
    def __init__(self, matched=True):
        self.matched = matched
        self.filter_request = None
        self.stream_request = None

    def filter_log_events(self, **request):
        self.filter_request = request
        if not self.matched:
            return {"events": []}
        return {
            "events": [
                {
                    "logStreamName": "task/worker-1",
                    "timestamp": 1792436608000,
                    "message": "pipeline pipeline-1",
                }
            ]
        }

    def get_log_events(self, **request):
        self.stream_request = request
        if request.get("nextToken"):
            return {"events": [], "nextForwardToken": "done"}
        return {
            "events": [
                {"timestamp": 1792436608000, "message": "pipeline pipeline-1"},
                {"timestamp": 1792436610000, "message": "token abc-secret"},
                {
                    "timestamp": 1792436611000,
                    "message": "ERROR: invalid input at /tmp/private/run.log",
                },
            ],
            "nextForwardToken": "done",
        }


class FakeBrain:
    def get_pipeline(self, pipeline_id):
        assert pipeline_id == "pipeline-1"
        return {
            "pipeline": "pipeline-1",
            "job_id": "job-1",
            "status": "failed",
            "updated_at": "2026-10-19T19:03:30.837568",
        }


def _reader(fake):
    return CloudWatchLogReader(
        CloudWatchLogConfig(
            log_group="/ecs/mroptimum-worker-mode2",
            region="us-east-1",
            lookback_minutes=120,
            max_events=20,
        ),
        client=fake,
    )


def test_log_tool_reads_only_pipeline_matched_stream_and_redacts_messages():
    cloudwatch = FakeCloudWatch()
    result = MROToolService(brain=FakeBrain(), logs=_reader(cloudwatch)).get_mro_run_logs(
        "pipeline-1"
    )

    assert result["ok"] is True
    assert result["logs_available"] is True
    assert result["event_count"] == 3
    assert cloudwatch.filter_request["filterPattern"] == '"pipeline-1"'
    assert cloudwatch.stream_request["logStreamName"] == "task/worker-1"
    messages = "\n".join(event["message"] for event in result["events"])
    assert "abc-secret" not in messages
    assert "[REDACTED]" in messages
    assert "/tmp/private" not in messages
    assert "invalid input" in messages


def test_log_tool_does_not_return_unmatched_worker_logs():
    result = MROToolService(
        brain=FakeBrain(), logs=_reader(FakeCloudWatch(matched=False))
    ).get_mro_run_logs("pipeline-1")

    assert result["ok"] is True
    assert result["logs_available"] is False
    assert "matching this pipeline was found" in result["message"]
