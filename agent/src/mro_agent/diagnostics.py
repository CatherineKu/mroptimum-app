"""Safe technical summaries of CloudMR job responses."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY = re.compile(r"(token|password|authorization|secret|presigned|signature)", re.I)
_URL_WITH_QUERY = re.compile(r"https?://[^\s\"']+\?[^\s\"']+", re.I)
_S3_URI = re.compile(r"s3://[^\s\"']+", re.I)
_ASSIGNMENT_SECRET = re.compile(
    r"\b(token|password|authorization|secret|signature)\s*[=:]\s*[^\s,;]+",
    re.I,
)
_STANDALONE_SECRET_LINE = re.compile(
    r"(?im)^(\s*(?:token|password|authorization|secret|signature)\b).*$"
)
_SENSITIVE_LOCATION_LINE = re.compile(r"(?im)^\s*(?:bucket_name|file_key)\b.*$")
_TEMP_PATH = re.compile(r"/tmp/[^\s\"']+")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = _URL_WITH_QUERY.sub("[REDACTED_URL]", value)
        value = _ASSIGNMENT_SECRET.sub(r"\1=[REDACTED]", value)
        return _S3_URI.sub("[REDACTED_S3_URI]", value)
    return value


def redact_log_message(message: str) -> str:
    """Redact credentials and storage paths while retaining diagnostic text."""
    message = _STANDALONE_SECRET_LINE.sub(r"\1 [REDACTED]", message)
    message = _SENSITIVE_LOCATION_LINE.sub("[REDACTED_STORAGE_LOCATION]", message)
    message = _TEMP_PATH.sub("[REDACTED_TEMP_PATH]", message)
    return str(redact(message))


def summarize_pipeline(pipeline: dict) -> dict:
    """Create an allowlisted status/diagnosis response for an LLM."""
    status = str(pipeline.get("status", "unknown")).lower()
    diagnosis = {
        "queued": "The job is queued and has not reached the MR worker yet.",
        "running": "The MR worker accepted the job and computation is in progress.",
        "completed": "The MR computation completed. Review the approved result manifest next.",
        "failed": "The MR computation failed. Review the sanitized technical error details.",
    }.get(status, "The job returned an unrecognized status; inspect the CloudMR pipeline record.")

    safe = {
        "pipeline_id": pipeline.get("pipeline") or pipeline.get("pipeline_id"),
        "job_id": pipeline.get("job_id"),
        "alias": pipeline.get("alias"),
        "computing_unit_id": pipeline.get("computing_unit_id"),
        "status": status,
        "mode": pipeline.get("mode"),
        "updated_at": pipeline.get("updated_at"),
        "diagnosis": diagnosis,
    }
    # Brain may eventually expose a human-readable error field.  Redact it
    # before forwarding and keep it bounded to avoid shipping entire log files.
    error = pipeline.get("error") or pipeline.get("message")
    if error:
        safe["technical_detail"] = str(redact(error))[:1000]
    return safe
