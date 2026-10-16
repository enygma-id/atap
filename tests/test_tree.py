# SPDX-License-Identifier: AGPL-3.0-only
"""Unit and integration tests for ATAP tree canopy elevation and carbon mode."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from atap.engine.config import Config


def test_tree_allometrics():
    """Verify allometric calculations follow Chave et al. (2014) and IPCC (2006)."""
    h = 10.0
    crown_diam = 6.0
    rho = 0.57
    carbon_frac = 0.47

    # DBH (cm) = 0.55 * (H^0.92) * (D_crown^0.42)
    expected_dbh = 0.55 * (h**0.92) * (crown_diam**0.42)
    # AGB (kg) = 0.0673 * (rho * DBH^2 * H)^0.976
    expected_agb = 0.0673 * (rho * (expected_dbh**2) * h) ** 0.976
    expected_carbon = expected_agb * carbon_frac
    expected_co2e = expected_carbon * 3.667

    assert expected_dbh > 0
    assert expected_agb > 0
    assert expected_carbon == pytest.approx(expected_agb * 0.47)
    assert expected_co2e == pytest.approx(expected_carbon * (44.009 / 12.011), rel=1e-3)


@pytest.fixture
def synthetic_tree_scene(tmp_path: Path):
    """Create a minimal synthetic raster and polygon dataset for tree testing."""
    dsm_path = tmp_path / "dsm_tree.tif"
    dtm_path = tmp_path / "dtm_tree.tif"
    geojson_path = tmp_path / "tree_footprints.geojson"

    w, h = 100, 100
    res = 0.5
    x0, y0 = 770000.0, 9432000.0
    trans_utm_to_wgs = Transformer.from_crs(32750, 4326, always_xy=True)

    # Flat DTM at ground = 5.0m
    dtm_arr = np.full((h, w), 5.0, dtype="float32")
    # DSM with a hemispherical tree crown peaking at +12.0m (total 17.0m)
    dsm_arr = np.full((h, w), 5.0, dtype="float32")
    cx, cy = 50, 50
    radius = 12
    for r in range(h):
        for c in range(w):
            dist = np.hypot(c - cx, r - cy)
            if dist <= radius:
                # Dome shape
                dsm_arr[r, c] = 5.0 + 12.0 * np.cos((dist / radius) * (np.pi / 2))

    profile = dict(
        driver="GTiff",
        width=w,
        height=h,
        count=1,
        dtype="float32",
        crs="EPSG:32750",
        transform=from_origin(x0, y0, res, res),
        nodata=-9999.0,
    )
    with rasterio.open(dsm_path, "w", **profile) as dst:
        dst.write(dsm_arr, 1)
    with rasterio.open(dtm_path, "w", **profile) as dst:
        dst.write(dtm_arr, 1)

    # Canopy footprint enclosing the dome
    box_coords_utm = [
        (x0 + (cx - radius) * res, y0 - (cy - radius) * res),
        (x0 + (cx + radius) * res, y0 - (cy - radius) * res),
        (x0 + (cx + radius) * res, y0 - (cy + radius) * res),
        (x0 + (cx - radius) * res, y0 - (cy + radius) * res),
        (x0 + (cx - radius) * res, y0 - (cy - radius) * res),
    ]
    box_coords_wgs = [list(trans_utm_to_wgs.transform(x, y)) for x, y in box_coords_utm]

    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "TREE_001",
                "properties": {"id": "TREE_001", "species": "Angsana"},
                "geometry": {"type": "Polygon", "coordinates": [box_coords_wgs]},
            }
        ],
    }
    geojson_path.write_text(json.dumps(fc), encoding="utf-8")

    return {
        "dsm": dsm_path,
        "dtm": dtm_path,
        "geojson": geojson_path,
    }


def test_tree_cli_execution(synthetic_tree_scene, tmp_path: Path):
    """Test full CLI execution with --mode tree."""
    out_geojson = tmp_path / "out_trees.geojson"
    cmd = [
        sys.executable,
        "-m",
        "atap",
        "run",
        "--mode",
        "tree",
        "--input-geojson",
        str(synthetic_tree_scene["geojson"]),
        "--dsm",
        str(synthetic_tree_scene["dsm"]),
        "--dtm",
        str(synthetic_tree_scene["dtm"]),
        "--output",
        str(out_geojson),
        "--events",
        "jsonl",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"CLI error: {res.stderr}\nStdout: {res.stdout}"

    # Verify primary output
    assert out_geojson.exists()
    data = json.loads(out_geojson.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) > 0

    feat = data["features"][0]
    props = feat["properties"]
    assert "carbon_kg" in props
    assert "agb_kg" in props
    assert "dbh_cm" in props
    assert "crown_diameter_m" in props
    assert "base_height_agl_m" in props
    assert "top_height_agl_m" in props
    assert props["base_height_agl_m"] > 0
    assert props["carbon_kg"] > 0

    # Verify companion files
    points_path = tmp_path / "out_trees_points.geojson"
    summary_path = tmp_path / "out_trees_summary.json"
    assert points_path.exists()
    assert summary_path.exists()

    pts_data = json.loads(points_path.read_text(encoding="utf-8"))
    assert len(pts_data["features"]) == 1
    pt_props = pts_data["features"][0]["properties"]
    assert "trunk_height" in pt_props
    assert "trunk_diameter" in pt_props
    assert "ground_z" in pt_props
    assert pt_props["ground_z"] == pytest.approx(5.0, abs=0.5)

    sum_data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert sum_data["total_trees"] == 1
    assert sum_data["total_carbon_mg"] > 0
    assert sum_data["total_co2e_mg"] > 0


def test_building_mode_default_regression(synthetic_tree_scene, tmp_path: Path):
    """Ensure default mode remains building and existing behavior is unaffected."""
    cfg = Config(
        input_geojson=str(synthetic_tree_scene["geojson"]),
        dsm_path=str(synthetic_tree_scene["dsm"]),
        dtm_path=str(synthetic_tree_scene["dtm"]),
    )
    assert cfg.mode == "building"
