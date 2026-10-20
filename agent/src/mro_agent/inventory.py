"""Run and interpret the MR Optimum Siemens raw-data inventory tool."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError, ValidationError


@dataclass(frozen=True)
class InventorySummary:
    coil_count: int
    replica_count: int
    slice_count: int
    has_orientation: bool
    acceleration: list[int | float | None] | None
    multiraid: bool
    inventory_path: str


class DatInventoryRunner:
    """Adapter around the versioned `chloe-mroptimum-tools` inventory script."""

    def __init__(self, script_path: str | Path | None = None, python_executable: str | None = None):
        script_path = script_path or os.environ.get("MRO_DAT_INVENTORY_SCRIPT")
        if not script_path:
            raise ConfigurationError(
                "MRO_DAT_INVENTORY_SCRIPT must point to the packaged dat_inventory.py script"
            )
        self.script_path = Path(script_path)
        self.python_executable = python_executable or os.environ.get("MRO_INVENTORY_PYTHON", sys.executable)

    def inspect(self, dat_path: str | Path, output_dir: str | Path) -> InventorySummary:
        dat_path = Path(dat_path)
        output_dir = Path(output_dir)
        if dat_path.suffix.lower() != ".dat":
            raise ValidationError("Only Siemens .dat input is supported by this inventory runner")
        if not dat_path.is_file():
            raise ValidationError(f"Raw data file does not exist: {dat_path}")
        output_dir.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [self.python_executable, str(self.script_path), "-i", str(dat_path), "-o", str(output_dir)],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-1500:]
            raise ValidationError(f"Raw-data inventory failed: {detail}")
        manifest_path = output_dir / "inventory.json"
        if not manifest_path.is_file():
            raise ValidationError("Inventory completed without producing inventory.json")
        return self._summary(manifest_path)

    @staticmethod
    def _summary(manifest_path: Path) -> InventorySummary:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = [
            entry
            for raid in manifest.get("raids", {}).values()
            for entry in raid.values()
            if entry.get("scan_type") == "image"
        ]
        if len(entries) != 1:
            raise ValidationError("Expected exactly one image data set in inventory")
        entry = entries[0]
        shape = entry.get("shape", [])
        if len(shape) < 3:
            raise ValidationError("Inventory k-space shape does not include a coil dimension")
        return InventorySummary(
            coil_count=int(shape[2]),
            replica_count=int(entry.get("reps", 1)),
            slice_count=int(entry.get("slices", 1)),
            has_orientation=bool(entry.get("has_orient")),
            acceleration=entry.get("acceleration"),
            multiraid=bool(manifest.get("version_info", {}).get("is_multiraid")),
            inventory_path=str(manifest_path),
        )
