"""Dataset registry and public/private metadata boundary."""

from __future__ import annotations

import json
from pathlib import Path

from .errors import NotFoundError, ValidationError
from .models import DatasetRecord, DatasetRole


class DatasetRegistry:
    def __init__(self, records: list[DatasetRecord]):
        self._records = {record.dataset_id: record for record in records}

    @classmethod
    def from_json(cls, path: str | Path) -> "DatasetRegistry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        records: list[DatasetRecord] = []
        for item in raw.get("datasets", []):
            try:
                role = DatasetRole(item["role"])
                brain_file = item["brain_file"]
                if not isinstance(brain_file, dict):
                    raise TypeError("brain_file must be an object")
                records.append(
                    DatasetRecord(
                        dataset_id=item["dataset_id"],
                        display_name=item["display_name"],
                        role=role,
                        format=item["format"],
                        vendor=item.get("vendor", "unknown"),
                        metadata=item.get("metadata", {}),
                        brain_file=brain_file,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(f"Invalid dataset registry record: {exc}") from exc
        return cls(records)

    def get(self, dataset_id: str, expected_role: DatasetRole | None = None) -> DatasetRecord:
        record = self._records.get(dataset_id)
        if record is None:
            raise NotFoundError(f"Dataset '{dataset_id}' is not registered")
        if expected_role and record.role != expected_role:
            raise ValidationError(
                f"Dataset '{dataset_id}' has role '{record.role.value}', expected "
                f"'{expected_role.value}'"
            )
        return record

    def list_public(self, role: str | None = None) -> list[dict]:
        records = self._records.values()
        if role:
            try:
                expected_role = DatasetRole(role)
            except ValueError as exc:
                raise ValidationError(f"Unknown dataset role '{role}'") from exc
            records = (record for record in records if record.role == expected_role)
        return [record.public_summary() for record in records]
