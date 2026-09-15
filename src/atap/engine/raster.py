# SPDX-License-Identifier: AGPL-3.0-only
"""DSM master-grid and aligned DTM raster access."""

import math
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError, WindowError
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

from .config import AtapInputError, Config


# =============================================================================
#                 RASTER: DSM master grid + DTM aligned  (spec §3.2)
# =============================================================================
def _vrt_nodata(src) -> float:
    return float(src.nodata) if src.nodata is not None else float("nan")


def _raster_driver(cfg: Config) -> str | None:
    """Return the single GDAL driver accepted by rasterio.open."""
    if cfg.raster_drivers is None:
        return None
    if len(cfg.raster_drivers) != 1 or not cfg.raster_drivers[0]:
        raise AtapInputError("raster_drivers must contain exactly one GDAL driver.")
    return cfg.raster_drivers[0]


@dataclass
class AnalysisGrid:
    dsm_src: Any
    dtm_src: Any
    dsm_reader: Any          # Native dsm_src or a WarpedVRT; never coarsened to DTM.
    dtm_reader: Any          # DTM WarpedVRT aligned to the DSM grid.
    transform: Any
    width: int
    height: int
    res_x: float
    res_y: float
    dsm_warped: bool

    def close(self):
        for h in (self.dtm_reader, self.dsm_reader, self.dtm_src, self.dsm_src):
            try:
                if h is not None:
                    h.close()
            except Exception:
                pass


def open_dsm_master_grid(cfg: Config, work_crs: CRS):
    if not cfg.dsm_path or not os.path.isfile(cfg.dsm_path):
        raise AtapInputError(f"DSM is required and was not found: {cfg.dsm_path!r}")
    try:
        dsm_src = rasterio.open(cfg.dsm_path, driver=_raster_driver(cfg))
    except RasterioIOError as exc:
        raise AtapInputError(f"Cannot open DSM as an allowed raster: {exc}") from exc
    if dsm_src.crs is None:
        dsm_src.close()
        raise AtapInputError(f"Cannot determine DSM CRS: {cfg.dsm_path}")

    tf = dsm_src.transform
    same_crs = CRS.from_user_input(dsm_src.crs) == work_crs
    axis_aligned = tf.b == 0 and tf.d == 0
    if same_crs and axis_aligned:
        # Preserve the DSM exactly when it already matches the metric working grid.
        reader, warped = dsm_src, False
    else:
        # Reproject at the DSM's own native resolution.
        reader = WarpedVRT(dsm_src, crs=work_crs, resampling=Resampling.bilinear,
                           nodata=_vrt_nodata(dsm_src), dtype="float64")
        warped = True
    return dsm_src, reader, warped


def align_dtm_to_dsm(cfg: Config, work_crs: CRS, dsm_src, dsm_reader, dsm_warped) -> AnalysisGrid:
    if not cfg.dtm_path:
        raise AtapInputError("DTM is required for ATAP processing; --dtm was not provided.")
    if not os.path.isfile(cfg.dtm_path):
        raise AtapInputError(f"DTM is required and was not found: {cfg.dtm_path}")
    try:
        dtm_src = rasterio.open(cfg.dtm_path, driver=_raster_driver(cfg))
    except RasterioIOError as exc:
        dsm_reader.close()
        if dsm_reader is not dsm_src:
            dsm_src.close()
        raise AtapInputError(f"Cannot open DTM as an allowed raster: {exc}") from exc
    if dtm_src.crs is None:
        dtm_src.close()
        raise AtapInputError(f"Cannot determine DTM CRS: {cfg.dtm_path}")

    tf = dsm_reader.transform
    w, h = dsm_reader.width, dsm_reader.height

    # Confirm DTM and DSM overlap in the working CRS before warping.
    dl, db, dr, dt = transform_bounds(dtm_src.crs, work_crs, *dtm_src.bounds, densify_pts=21)
    xs = (tf.c, tf.c + tf.a * w)
    ys = (tf.f, tf.f + tf.e * h)
    gl, gr = min(xs), max(xs)
    gb, gt = min(ys), max(ys)
    if dr <= gl or dl >= gr or dt <= gb or db >= gt:
        dtm_src.close()
        raise AtapInputError("DTM and DSM do not overlap and cannot be aligned.")

    try:
        dtm_reader = WarpedVRT(dtm_src, crs=work_crs, transform=tf, width=w, height=h,
                               resampling=Resampling.bilinear,
                               nodata=_vrt_nodata(dtm_src), dtype="float64")
    except Exception as e:
        dtm_src.close()
        raise AtapInputError(f"Cannot warp DTM to the DSM grid: {e}") from e

    return AnalysisGrid(dsm_src=dsm_src, dtm_src=dtm_src, dsm_reader=dsm_reader,
                        dtm_reader=dtm_reader, transform=tf, width=w, height=h,
                        res_x=abs(tf.a), res_y=abs(tf.e), dsm_warped=dsm_warped)


def _read_float(reader, window) -> np.ndarray:
    a = reader.read(1, window=window, masked=True).astype("float64")
    arr = np.ma.filled(a, np.nan)
    nd = reader.nodata
    if nd is not None and math.isfinite(nd):
        arr[arr == nd] = np.nan
    return arr


def read_building_window(geom, grid: AnalysisGrid, pad_px: int):
    minx, miny, maxx, maxy = geom.bounds
    win = from_bounds(minx, miny, maxx, maxy, transform=grid.transform)
    win = win.round_offsets().round_lengths()
    win = Window(win.col_off - pad_px, win.row_off - pad_px,
                 win.width + 2 * pad_px, win.height + 2 * pad_px)
    try:
        win = win.intersection(Window(0, 0, grid.width, grid.height))
    except WindowError:
        return None
    if win.width <= 0 or win.height <= 0:
        return None
    dsm = _read_float(grid.dsm_reader, win)
    dtm = _read_float(grid.dtm_reader, win)
    return dtm, dsm, window_transform(win, grid.transform)


def gdal_cache_env(cache_mb: int) -> rasterio.Env:
    # Rasterio passes GDAL_CACHEMAX to GDALSetCacheMax64 in bytes rather than
    # the megabyte unit used by ordinary GDAL configuration.
    return rasterio.Env(GDAL_CACHEMAX=int(cache_mb) * 1024 * 1024)
