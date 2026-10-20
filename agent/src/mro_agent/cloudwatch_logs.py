"""Read a single MR Optimum worker execution from CloudWatch Logs.

This module is intentionally read-only. It first finds the log stream that
contains the CloudMR pipeline identifier, then reads only that stream in a
bounded time window. The agent therefore never receives a broad dump of logs
from other jobs that happen to share the worker log group.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .diagnostics import redact_log_message
from .errors import ConfigurationError


DEFAULT_LOG_GROUP = "/ecs/mroptimum-worker-mode2"
DEFAULT_REGION = "us-east-1"
DEFAULT_LOOKBACK_MINUTES = 120
DEFAULT_MAX_EVENTS = 250


@dataclass(frozen=True)
class CloudWatchLogConfig:
    """Non-secret configuration for the MR Optimum worker logs."""

    log_group: str = DEFAULT_LOG_GROUP
    region: str = DEFAULT_REGION
    profile: str | None = None
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES
    max_events: int = DEFAULT_MAX_EVENTS

    @classmethod
    def from_environment(cls) -> "CloudWatchLogConfig":
        def positive_int(name: str, default: int, maximum: int) -> int:
            raw = os.environ.get(name)
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ConfigurationError(f"{name} must be an integer") from exc
            if not 1 <= value <= maximum:
                raise ConfigurationError(f"{name} must be between 1 and {maximum}")
            return value

        return cls(
            log_group=os.environ.get("MRO_CLOUDWATCH_LOG_GROUP", DEFAULT_LOG_GROUP),
            region=os.environ.get(
                "MRO_CLOUDWATCH_REGION", os.environ.get("AWS_REGION", DEFAULT_REGION)
            ),
            # A profile is for local development only. AgentCore uses its IAM role.
            profile=os.environ.get("MRO_CLOUDWATCH_AWS_PROFILE") or None,
            lookback_minutes=positive_int(
                "MRO_CLOUDWATCH_LOOKBACK_MINUTES", DEFAULT_LOOKBACK_MINUTES, 360
            ),
            max_events=positive_int("MRO_CLOUDWATCH_MAX_EVENTS", DEFAULT_MAX_EVENTS, 500),
        )


class CloudWatchLogReader:
    """Retrieve a bounded, sanitized log excerpt for one pipeline."""

    def __init__(
        self,
        config: CloudWatchLogConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or CloudWatchLogConfig.from_environment()
        self._provided_client = client
        self._client_instance: Any | None = None

    def read_pipeline_logs(self, pipeline_id: str, updated_at: str | None) -> dict:
        """Find the pipeline-correlated stream and return safe events only."""
        window_start, window_end = self._window(updated_at)
        client = self._client()

        try:
            matches = client.filter_log_events(
                logGroupName=self.config.log_group,
                # app.py writes ``pipeline <id>`` before beginning computation.
                filterPattern=f'"{pipeline_id}"',
                startTime=self._epoch_millis(window_start),
                endTime=self._epoch_millis(window_end),
                limit=50,
            ).get("events", [])
        except Exception as exc:  # Do not disclose AWS credential details.
            raise ConfigurationError("Unable to search MR Optimum worker logs") from exc

        matching_streams = [
            event.get("logStreamName")
            for event in matches
            if isinstance(event, dict) and event.get("logStreamName")
        ]
        stream_name = self._unique_stream(matching_streams)
        if stream_name is None:
            return {
                "found": False,
                "events": [],
                "window_start": self._iso(window_start),
                "window_end": self._iso(window_end),
            }

        try:
            events = self._get_stream_events(client, stream_name, window_start, window_end)
        except Exception as exc:
            raise ConfigurationError("Unable to read the matched MR Optimum worker log stream") from exc

        safe_events = []
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("message"), str):
                continue
            safe_events.append(
                {
                    "timestamp": self._timestamp_from_millis(event.get("timestamp")),
                    "message": redact_log_message(event["message"]),
                }
            )
        return {
            "found": True,
            "events": safe_events,
            "window_start": self._iso(window_start),
            "window_end": self._iso(window_end),
        }

    def _client(self) -> Any:
        if self._provided_client is not None:
            return self._provided_client
        if self._client_instance is None:
            try:
                import boto3

                session = boto3.Session(
                    profile_name=self.config.profile,
                    region_name=self.config.region,
                )
                self._client_instance = session.client("logs")
            except Exception as exc:
                raise ConfigurationError("CloudWatch Logs client is not configured") from exc
        return self._client_instance

    def _get_stream_events(
        self,
        client: Any,
        stream_name: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[dict]:
        events: list[dict] = []
        token: str | None = None
        while len(events) < self.config.max_events:
            request: dict[str, Any] = {
                "logGroupName": self.config.log_group,
                "logStreamName": stream_name,
                "startTime": self._epoch_millis(window_start),
                "endTime": self._epoch_millis(window_end),
                "startFromHead": True,
                "limit": min(10000, self.config.max_events - len(events)),
            }
            if token:
                request["nextToken"] = token
            response = client.get_log_events(**request)
            page = response.get("events", [])
            events.extend(event for event in page if isinstance(event, dict))
            next_token = response.get("nextForwardToken")
            if not page or not next_token or next_token == token:
                break
            token = next_token
        return events[: self.config.max_events]

    def _window(self, updated_at: str | None) -> tuple[datetime, datetime]:
        reference = self._parse_time(updated_at) or datetime.now(UTC)
        return (
            reference - timedelta(minutes=self.config.lookback_minutes),
            reference + timedelta(minutes=5),
        )

    @staticmethod
    def _unique_stream(stream_names: list[str]) -> str | None:
        counts: dict[str, int] = {}
        for stream_name in stream_names:
            counts[stream_name] = counts.get(stream_name, 0) + 1
        if not counts:
            return None
        return max(counts, key=lambda name: (counts[name], name))

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @staticmethod
    def _epoch_millis(value: datetime) -> int:
        return int(value.timestamp() * 1000)

    @staticmethod
    def _timestamp_from_millis(value: Any) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
