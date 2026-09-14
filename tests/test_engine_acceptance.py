# SPDX-License-Identifier: AGPL-3.0-only
"""Core acceptance tests for terrain-aware hierarchical output."""

import json
from pathlib import Path

import pytest

from atap import AtapInputError, run_elevation


def run_case(dataset: Path, output: Path, footprint: str = "footprints_fid.geojson", **kwargs):
    return run_elevation(
        str(dataset / footprint), str(dataset / "dtm.tif"), str(dataset / "dsm.tif"),
        str(output), workers=1, log_cb=lambda _: None, **kwargs,
    )


def test_dtm_is_mandatory_and_writes_nothing(synthetic: Path, tmp_path: Path):
    output = tmp_path / "missing-dtm.geojson"
    with pytest.raises(AtapInputError, match="DTM is required"):
        run_elevation(
            str(synthetic / "stepped/footprints_fid.geojson"),
            str(tmp_path / "missing.tif"), str(synthetic / "stepped/dsm.tif"),
            str(output), workers=1,
        )
    assert not output.exists()


def test_dsm_remains_master_grid_and_nested_intervals_hold(synthetic: Path, tmp_path: Path):
    output = tmp_path / "stepped.geojson"
    run_case(synthetic / "stepped", output)
    doc = json.loads(output.read_text(encoding="utf-8"))
    assert doc["processing"]["analysis_grid_source"] == "DSM"
    assert doc["processing"]["analysis_resolution_x_m"] == pytest.approx(0.1)
    by_id = {f["properties"]["part_id"]: f["properties"] for f in doc["features"]}
    for part in by_id.values():
        if part["parent_part_id"]:
            parent = by_id[part["parent_part_id"]]
            assert part["base_height_agl_m"] == pytest.approx(parent["top_height_agl_m"])
            assert part["part_level"] == parent["part_level"] + 1


def test_courtyard_hole_survives_and_excludes_volume(synthetic: Path, tmp_path: Path):
    output = tmp_path / "courtyard.geojson"
    run_case(synthetic / "courtyard", output)
    doc = json.loads(output.read_text(encoding="utf-8"))
    upper = next(f for f in doc["features"] if f["properties"]["part_level"] == 1)
    p = upper["properties"]
    assert p["interior_ring_count"] >= 1
    assert len(upper["geometry"]["coordinates"]) > 1
    assert p["volume_m3"] == pytest.approx(p["area_m2"] * p["part_height_m"], abs=0.1)


def test_stable_id_policy_and_duplicate_rejection(synthetic: Path, tmp_path: Path):
    source = json.loads((synthetic / "stepped/footprints.geojson").read_text(encoding="utf-8"))
    for feature in source["features"]:
        feature["properties"].pop("id", None)
    missing = tmp_path / "missing-id.geojson"
    missing.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(AtapInputError, match="ID"):
        run_case(synthetic / "stepped", tmp_path / "no-id-output.geojson", footprint=str(missing))
    source = json.loads((synthetic / "stepped/footprints_fid.geojson").read_text(encoding="utf-8"))
    source["features"][1]["id"] = source["features"][0]["id"]
    duplicate = tmp_path / "duplicate.geojson"
    duplicate.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(AtapInputError, match="duplikat|Duplicate"):
        run_case(synthetic / "stepped", tmp_path / "duplicate-output.geojson", footprint=str(duplicate))


def test_cancelled_run_writes_nothing(synthetic: Path, tmp_path: Path):
    output = tmp_path / "cancelled.geojson"
    result = run_elevation(
        str(synthetic / "stepped/footprints_fid.geojson"),
        str(synthetic / "stepped/dtm.tif"), str(synthetic / "stepped/dsm.tif"),
        str(output), workers=1, cancel_flag=lambda: True, log_cb=lambda _: None,
    )
    assert result["cancelled"] is True
    assert not output.exists()


def test_non_metric_working_crs_fails(synthetic: Path, tmp_path: Path):
    with pytest.raises(AtapInputError, match="projected metric CRS"):
        run_case(synthetic / "stepped", tmp_path / "degrees.geojson", working_crs="EPSG:4326")


def test_outside_building_has_stable_skipped_reason(synthetic: Path, tmp_path: Path):
    output = tmp_path / "skipped.geojson"
    run_case(synthetic / "stepped", output)
    summary = json.loads(output.read_text(encoding="utf-8"))["summary"]
    assert summary["skipped_buildings"] == [
        {"object_id": "B5_out", "reason": "OUTSIDE_ANALYSIS_GRID"}
    ]
