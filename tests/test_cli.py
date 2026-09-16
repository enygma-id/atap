# SPDX-License-Identifier: AGPL-3.0-only
"""CLI exit-code, JSONL, parameter precedence, and validation tests."""

import json
import subprocess
import sys
from pathlib import Path

import atap.cli


def invoke(*args: str):
    return subprocess.run([sys.executable, "-m", "atap", *args], text=True,
                          capture_output=True, check=False)


def test_version():
    result = invoke("--version")
    assert result.returncode == 0
    assert "engine 0.2.0, profile 0.6" in result.stdout


def test_input_error_exit_code_and_jsonl(tmp_path: Path):
    result = invoke(
        "run", "--input-geojson", "missing.geojson", "--dsm", "missing.tif",
        "--dtm", "missing.tif", "--output", str(tmp_path / "out.geojson"),
        "--events", "jsonl",
    )
    assert result.returncode == 2
    event = json.loads(result.stdout)
    assert event["type"] == "error" and event["code"] == "INPUT"


def test_params_json_and_explicit_flag_precedence(synthetic: Path, tmp_path: Path):
    params = tmp_path / "params.json"
    params.write_text(json.dumps({"workers": 2, "max_height_classes": 8}), encoding="utf-8")
    output = tmp_path / "cli.geojson"
    d = synthetic / "stepped"
    result = invoke(
        "run", "--input-geojson", str(d / "footprints_fid.geojson"),
        "--dsm", str(d / "dsm.tif"), "--dtm", str(d / "dtm.tif"),
        "--output", str(output), "--params-json", str(params), "--workers", "1",
        "--events", "jsonl", "--raster-drivers", "GTiff",
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["type"] == "result"
    doc = json.loads(output.read_text(encoding="utf-8"))
    assert doc["processing"]["execution"]["workers"] == 1
    assert doc["processing"]["parameters"]["max_height_classes"] == 8


def test_validate_good_and_tampered(synthetic: Path, tmp_path: Path):
    d = synthetic / "stepped"
    output = tmp_path / "good.geojson"
    run = invoke(
        "run", "--input-geojson", str(d / "footprints_fid.geojson"),
        "--dsm", str(d / "dsm.tif"), "--dtm", str(d / "dtm.tif"),
        "--output", str(output), "--workers", "1", "--quiet",
    )
    assert run.returncode == 0, run.stderr
    assert invoke("validate", str(output)).returncode == 0
    doc = json.loads(output.read_text(encoding="utf-8"))
    doc["features"][0]["properties"]["part_height_m"] += 1
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    assert invoke("validate", str(bad)).returncode == 3


def test_cancel_file_returns_130_without_output(synthetic: Path, tmp_path: Path):
    cancel = tmp_path / "cancel"
    cancel.touch()
    output = tmp_path / "cancelled.geojson"
    d = synthetic / "stepped"
    result = invoke(
        "run", "--input-geojson", str(d / "footprints_fid.geojson"),
        "--dsm", str(d / "dsm.tif"), "--dtm", str(d / "dtm.tif"),
        "--output", str(output), "--workers", "1", "--cancel-file", str(cancel),
        "--quiet",
    )
    assert result.returncode == 130
    assert not output.exists()


def test_keep_properties_omitted_means_all_and_empty_flag_means_none(monkeypatch):
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return {"cancelled": False, "output_path": "out.geojson"}
    monkeypatch.setattr(atap.cli, "run_elevation", fake_run)
    common = ["run", "--input-geojson", "footprints.geojson", "--dsm", "dsm.tif",
              "--dtm", "dtm.tif", "--output", "out.geojson", "--quiet"]
    assert atap.cli.main(common) == 0
    assert "keep_properties" not in calls[-1]
    assert atap.cli.main([*common, "--keep-properties", ""]) == 0
    assert calls[-1]["keep_properties"] == []


def test_unexpected_error_returns_4(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setattr(atap.cli, "run_elevation", lambda *args, **kwargs: 1 / 0)
    code = atap.cli.main([
        "run", "--input-geojson", "input.geojson", "--dsm", "dsm.tif",
        "--dtm", "dtm.tif", "--output", str(tmp_path / "out.geojson"), "--quiet",
    ])
    assert code == 4
    assert "ZeroDivisionError" in capsys.readouterr().err
