# SPDX-License-Identifier: AGPL-3.0-only
"""Package output stays equivalent to all frozen Phase 0 baselines."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generated_goldens(synthetic: Path, tmp_path_factory):
    candidate = tmp_path_factory.mktemp("release-goldens")
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_baselines.py"),
            "--data",
            str(synthetic),
            "--out",
            str(candidate),
            "--engine",
            "atap",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    return candidate


def verify(candidate):
    return subprocess.run(
        [sys.executable, str(ROOT / "tests/golden/verify.py"), str(candidate),
         "--ignore-engine-version", "--expected-engine-version", "0.3.0"],
        capture_output=True, text=True, check=False,
    )


def test_all_four_frozen_goldens(generated_goldens):
    result = verify(generated_goldens)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All four golden cases and summaries are EQUIVALENT." in result.stdout


def test_fresh_output_records_release_version(generated_goldens):
    for path in generated_goldens.glob("*.geojson"):
        assert json.loads(path.read_text(encoding="utf-8"))["atap"]["engine_version"] == "0.3.0"


def test_engine_version_normalization_is_explicit(tmp_path):
    original = ROOT / "tests/golden/stepped_default.geojson"
    candidate = tmp_path / "candidate.geojson"
    data = json.loads(original.read_text(encoding="utf-8"))
    assert data["atap"]["engine_version"] == "0.2.0"
    data["atap"]["engine_version"] = "0.3.0"
    candidate.write_text(json.dumps(data), encoding="utf-8")
    command = [sys.executable, str(ROOT / "tools/compare_outputs.py"), str(original), str(candidate)]
    strict = subprocess.run(command, capture_output=True, text=True)
    assert strict.returncode == 1 and "atap.engine_version" in strict.stdout
    normalized = subprocess.run([*command, "--ignore-engine-version"], capture_output=True, text=True)
    assert normalized.returncode == 0, normalized.stdout + normalized.stderr


@pytest.mark.parametrize("mutation", ["height", "coordinate", "parent", "profile", "crs", "missing-version"])
def test_cross_version_mode_rejects_other_changes(generated_goldens, tmp_path, mutation):
    data = json.loads((generated_goldens / "stepped_default.geojson").read_text(encoding="utf-8"))
    if mutation == "height":
        data["features"][0]["properties"]["part_height_m"] += 1
    elif mutation == "coordinate":
        data["features"][0]["geometry"]["coordinates"][0][0][0] += 0.00001
    elif mutation == "parent":
        data["features"][0]["properties"]["parent_part_id"] = "unexpected-parent"
    elif mutation == "profile":
        data["atap"]["profile_version"] = "changed"
    elif mutation == "crs":
        data["processing"]["working_crs"] = "EPSG:32631"
    else:
        del data["atap"]["engine_version"]
    candidate = tmp_path / "tampered.geojson"
    candidate.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/compare_outputs.py"), "--ignore-engine-version",
         str(ROOT / "tests/golden/stepped_default.geojson"), str(candidate)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_scientific_benchmark_digest_rejects_changed_measurement(generated_goldens, tmp_path):
    for source in generated_goldens.iterdir():
        (tmp_path / source.name).write_bytes(source.read_bytes())
    path = tmp_path / "bench_default.geojson"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["features"][0]["properties"]["part_height_m"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    verify = subprocess.run(
        [sys.executable, str(ROOT / "tests/golden/verify.py"), str(tmp_path), "--ignore-engine-version"],
        capture_output=True, text=True, check=False,
    )
    assert verify.returncode != 0 and "benchmark SHA-256" in verify.stderr
