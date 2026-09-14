# SPDX-License-Identifier: AGPL-3.0-only
"""Determinism across sequential and spawned-worker execution."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def canonical(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("process", None)
    doc.get("processing", {}).pop("execution", None)
    return doc


@pytest.mark.parametrize("case,footprint", [
    ("stepped", "footprints.geojson"),
    ("bench", "footprints_fid.geojson"),
])
def test_workers_one_and_two_are_equivalent(
    synthetic: Path, tmp_path: Path, case: str, footprint: str,
):
    outputs = []
    for workers in (1, 2):
        directory = tmp_path / f"w{workers}"
        directory.mkdir()
        output = directory / "output.geojson"
        command = [
            sys.executable, "-m", "atap", "run",
            "--input-geojson", str(synthetic / case / footprint),
            "--dsm", str(synthetic / case / "dsm.tif"),
            "--dtm", str(synthetic / case / "dtm.tif"),
            "--output", str(output), "--workers", str(workers), "--quiet",
        ]
        if case == "stepped":
            command.extend(("--id-field", "id"))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        outputs.append(output)
    assert canonical(outputs[0]) == canonical(outputs[1])
