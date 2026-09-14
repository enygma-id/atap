# SPDX-License-Identifier: AGPL-3.0-only
"""Focused unit tests for algorithms and failure-safe output."""

import os
from pathlib import Path

import numpy as np
import pytest
from scipy import ndimage as ndi
from shapely.geometry import Polygon

from atap import Config
from atap.engine.height import kmeans_1d
from atap.engine.output import atomic_write_geojson
from atap.engine.polygon import fill_small_holes, regularize_polygon
from atap.engine.raster import gdal_cache_env


def reference_kmeans(values: np.ndarray, k: int, iters: int = 60):
    x = values[np.isfinite(values)].astype(float)
    centers = np.unique(np.quantile(x, np.linspace(0, 1, min(k, x.size))))
    for _ in range(iters):
        labels = np.argmin(np.abs(x[:, None] - centers[None, :]), axis=1)
        updated = np.array([x[labels == i].mean() if np.any(labels == i) else centers[i]
                            for i in range(len(centers))])
        if np.allclose(updated, centers, atol=1e-7, rtol=0):
            centers = updated
            break
        centers = updated
    return labels, centers


def test_exact_kmeans_matches_distance_matrix_reference():
    rng = np.random.default_rng(42)
    values = np.concatenate([rng.normal(5, 0.3, 300), rng.normal(15, 0.8, 400)])
    _, actual = kmeans_1d(values, 4)
    _, expected = reference_kmeans(values, 4)
    assert actual == pytest.approx(expected, abs=1e-10)


def test_fill_small_holes_respects_area_threshold():
    mask = np.ones((12, 12), dtype=bool)
    mask[2:4, 2:4] = False
    mask[6:10, 6:10] = False
    result = fill_small_holes(mask, max_area_m2=4, pixel_area_m2=1)
    assert result[2:4, 2:4].all()
    assert not result[6:10, 6:10].any()
    assert ndi.label(~result)[1] == 1


def test_atomic_writer_removes_temporary_file_on_replace_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "output.geojson"
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        atomic_write_geojson({"type": "FeatureCollection", "features": []}, str(target))
    assert not target.exists()
    assert not list(tmp_path.glob(".atap_*"))


def test_gdal_cache_is_configured_in_bytes():
    env = gdal_cache_env(64)
    assert env.options["GDAL_CACHEMAX"] == 64 * 1024 * 1024


def test_regularization_preserves_large_hole():
    polygon = Polygon(
        [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)],
        [[(5, 5), (15, 5), (15, 15), (5, 15), (5, 5)]],
    )
    result, _ = regularize_polygon(polygon, Config(regularize=True))
    assert result is not None
    parts = [result] if result.geom_type == "Polygon" else result.geoms
    assert sum(len(part.interiors) for part in parts) == 1
