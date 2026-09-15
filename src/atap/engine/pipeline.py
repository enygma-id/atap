# SPDX-License-Identifier: AGPL-3.0-only
"""End-to-end ATAP elevation pipeline."""

import math
import multiprocessing as mp
import os
import platform
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, replace
from datetime import datetime, timezone

import numpy as np
import rasterio
import shapely
from pyproj import CRS

from .config import (
    ANALYSIS_GRID_SOURCE,
    CONFIG,
    DTM_RESAMPLING,
    ENGINE_VERSION,
    PROFILE_VERSION,
    AtapError,
    AtapInputError,
    Config,
)
from .io import is_metric_projected, load_footprints
from .output import atomic_write_geojson, build_feature_collection
from .parallel import (
    _worker_chunk,
    _worker_init,
    process_building,
    resolve_workers,
    spatial_order,
)
from .raster import (
    _raster_driver,
    align_dtm_to_dsm,
    gdal_cache_env,
    open_dsm_master_grid,
)
from .validation import validate_all

# =============================================================================
#                         END-TO-END PIPELINE
# =============================================================================
_OVERRIDABLE = (
    "input_geojson", "dtm_path", "dsm_path", "output_geojson", "id_field",
    "height_diff_threshold_m", "min_subregion_area_m2", "min_building_height_m",
    "base_elevation_stat", "ground_source_type", "vertical_datum",
    "max_height_classes", "min_footprint_change_ratio", "morph_closing_iters",
    "max_fill_hole_area_m2", "parent_min_containment_ratio",
    "regularize", "simplify_tolerance_m", "rectangular_ratio", "circularity_threshold",
    "working_crs", "output_crs", "keep_properties", "round_digits", "coord_digits",
    "workers", "gdal_cache_mb", "raster_drivers",
)


def run_elevation(
    input_geojson: str | None = None,
    dtm_path: str | None = None,
    dsm_path: str | None = None,
    output_geojson: str | None = None,
    *,
    id_field: str | None = None,
    height_diff_threshold_m: float | None = None,
    min_subregion_area_m2: float | None = None,
    min_building_height_m: float | None = None,
    base_elevation_stat: str | None = None,
    ground_source_type: str | None = None,
    vertical_datum: str | None = None,
    max_height_classes: int | None = None,
    min_footprint_change_ratio: float | None = None,
    morph_closing_iters: int | None = None,
    max_fill_hole_area_m2: float | None = None,
    parent_min_containment_ratio: float | None = None,
    regularize: bool | None = None,
    simplify_tolerance_m: float | None = None,
    rectangular_ratio: float | None = None,
    circularity_threshold: float | None = None,
    working_crs: str | None = None,
    output_crs: str | None = None,
    keep_properties: list | None = None,
    round_digits: int | None = None,
    coord_digits: int | None = None,
    workers: int | None = None,
    gdal_cache_mb: int | None = None,
    raster_drivers: list[str] | None = None,
    base_cfg: Config | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
) -> dict:
    """
    Run the ATAP elevation pipeline end to end. None-valued parameters use
    `base_cfg`, or the default configuration.

    Optional callbacks:
      progress_cb(current, total, message)  -> total>0 determinate, total==0 indeterminate
      log_cb(message)                       -> one log line (default: print)
      cancel_flag() -> bool                 -> checked between buildings and every ~0.5 s

    `workers` > 1 uses ProcessPoolExecutor with spawn. Callers must use a
    guarded main module or invoke the CLI as a subprocess on Windows.

    Raise AtapInputError or AtapValidationError on contract violations.
    Cancellation writes no partial output.

    Returns: {"output_path", "num_features", "num_parcels", "num_buildings",
              "num_skipped", "cancelled"}
    """
    def _log(msg: str):
        (log_cb or print)(msg)

    def _prog(c: int, t: int, m: str):
        if progress_cb is not None:
            progress_cb(c, t, m)

    def _cancelled() -> bool:
        return bool(cancel_flag()) if cancel_flag is not None else False

    t0 = time.time()
    started = datetime.now(timezone.utc)

    cfg = replace(base_cfg or CONFIG)
    local = locals()
    for k in _OVERRIDABLE:
        v = local.get(k)
        if v is not None:
            setattr(cfg, k, v)

    # Validate configuration before opening large inputs.
    if cfg.base_elevation_stat not in ("min", "mean", "median"):
        raise AtapInputError(f"Unknown base_elevation_stat: {cfg.base_elevation_stat}")
    if cfg.ground_source_type not in ("DTM", "DEM"):
        raise AtapInputError("ground_source_type must be 'DTM' or 'DEM'.")
    if CRS.from_user_input(cfg.output_crs) != CRS.from_epsg(4326):
        raise AtapInputError("Canonical ATAP output must use EPSG:4326.")
    try:
        work_crs = CRS.from_user_input(cfg.working_crs)
    except Exception as e:
        raise AtapInputError(f"Invalid working_crs: {cfg.working_crs}") from e
    if not is_metric_projected(work_crs):
        raise AtapInputError(f"working_crs must be a projected metric CRS: {cfg.working_crs}")
    # Check DTM first so a missing terrain model always fails explicitly.
    if not cfg.dtm_path or not os.path.isfile(cfg.dtm_path):
        raise AtapInputError(
            f"DTM is required for ATAP processing and was not found: {cfg.dtm_path!r}")

    _prog(0, 0, "Loading footprints...")
    fp = load_footprints(cfg, work_crs, _log)
    n_parcels = fp["feature_count"]
    _log(f"[info] Loaded {n_parcels} footprints; IDs from "
         f"{'properties.' + fp['id_source']['field']}")

    _prog(0, 0, "Opening the DSM master grid and aligning the DTM...")
    dsm_src, dsm_reader, dsm_warped = open_dsm_master_grid(cfg, work_crs)
    try:
        grid = align_dtm_to_dsm(cfg, work_crs, dsm_src, dsm_reader, dsm_warped)
    except Exception:
        for h in (dsm_reader, dsm_src):
            try:
                h.close()
            except Exception:
                pass
        raise

    try:
        _log(f"[info] Analysis grid = DSM{' (reprojected)' if dsm_warped else ''}: "
             f"{grid.width}x{grid.height} px, resolution {grid.res_x:.4f} x {grid.res_y:.4f} m; "
             f"DTM resampled with {DTM_RESAMPLING} onto the DSM grid.")

        records = fp["records"]
        keep = (
            sorted({key for _, _, props in records for key in props})
            if cfg.keep_properties is None
            else list(dict.fromkeys(cfg.keep_properties))
        )
        # Persist the resolved keys for workers and reproducible output metadata.
        cfg = replace(cfg, keep_properties=keep)
        pad = max(1, int(cfg.morph_closing_iters) + 2)
        order = spatial_order(records, grid)
        items = [(i, records[i][0], records[i][1], records[i][2]) for i in order]
        n_workers = resolve_workers(cfg.workers, n_parcels)
        chunk_size = None
        results: dict[int, dict] = {}
        cancelled = False

        if n_workers == 1:
            _log(f"[info] Single-process execution; GDAL cache {cfg.gdal_cache_mb} MB.")
            with gdal_cache_env(cfg.gdal_cache_mb):
                for done, (i, oid, geom, props) in enumerate(items, 1):
                    if _cancelled():
                        cancelled = True
                        break
                    _prog(done, n_parcels, f"Processing building {done}/{n_parcels}")
                    results[i] = process_building(oid, geom, props, grid, cfg, pad, keep)
        else:
            chunk_size = max(1, min(16, math.ceil(n_parcels / (n_workers * 8))))
            chunks = [items[k:k + chunk_size] for k in range(0, len(items), chunk_size)]
            cache_per_worker = max(64, int(cfg.gdal_cache_mb) // n_workers)
            _log(f"[info] Parallel execution: {n_workers} workers, {len(chunks)} batches "
                 f"of {chunk_size} buildings; GDAL cache {cache_per_worker} MB/worker.")
            ex = ProcessPoolExecutor(max_workers=n_workers, initializer=_worker_init,
                                     initargs=(cfg, cache_per_worker),
                                     mp_context=mp.get_context("spawn"))
            try:
                pending = {ex.submit(_worker_chunk, c) for c in chunks}
                _prog(0, n_parcels, f"Processing building 0/{n_parcels}")
                while pending:
                    finished, pending = wait(pending, timeout=0.5,
                                             return_when=FIRST_COMPLETED)
                    for f in finished:
                        for i, r in f.result():
                            results[i] = r
                    if finished:
                        _prog(len(results), n_parcels,
                              f"Processing building {len(results)}/{n_parcels}")
                    if pending and _cancelled():
                        cancelled = True
                        for f in pending:
                            f.cancel()
                        break
            except BrokenProcessPool as e:
                raise AtapError(f"Parallel worker stopped unexpectedly: {e}") from e
            except RuntimeError as e:
                raise AtapError(f"Building processing failed: {e}") from e
            finally:
                ex.shutdown(wait=True, cancel_futures=True)

        if cancelled:
            _log("[info] Cancelled by user; output was not written.")

        # Assemble results in input order for determinism across worker counts.
        all_recs: list[dict] = []
        skipped: list[dict] = []
        n_decomposed = 0
        for i in range(n_parcels):
            r = results.get(i)
            if r is None:
                continue
            if r["kind"] == "skipped":
                skipped.append({"object_id": records[i][0], "reason": r["reason"]})
            else:
                all_recs.extend(r["recs"])
                n_decomposed += int(r["decomposed"])

        if cancelled:
            return {"output_path": None, "num_features": 0, "num_parcels": n_parcels,
                    "num_buildings": 0, "num_skipped": len(skipped), "cancelled": True}

        if skipped:
            _log(f"[warn] Skipped {len(skipped)} buildings; see summary.skipped_buildings.")
        if not all_recs:
            raise AtapError("No building could be processed; check DSM and DTM coverage.")

        _prog(n_parcels, n_parcels, "Validating invariants...")
        validate_all(all_recs, cfg)

        # ---- Metadata dataset (spec §17-18) ----
        roots = [r for r in all_recs if r["properties"]["parent_part_id"] is None]
        with rasterio.open(cfg.dtm_path, driver=_raster_driver(cfg)) as dsrc:
            dtm_res = (abs(dsrc.transform.a), abs(dsrc.transform.e))
            dtm_unit = (CRS.from_user_input(dsrc.crs).axis_info[0].unit_name
                        if dsrc.crs else None)
        dsm_unit = CRS.from_user_input(dsm_src.crs).axis_info[0].unit_name
        params = {k: v for k, v in asdict(cfg).items()
                  if k not in ("input_geojson", "dtm_path", "dsm_path", "output_geojson",
                               "working_crs", "output_crs", "workers", "gdal_cache_mb",
                               "id_field", "vertical_datum", "ground_source_type",
                               "base_elevation_stat", "raster_drivers")}
        finished = datetime.now(timezone.utc)
        meta = {
            "atap": {"engine_version": ENGINE_VERSION, "profile_version": PROFILE_VERSION},
            "process": {
                "name": "atap_elevation",
                "implementation": os.path.basename(__file__),
                "started_at_utc": started.isoformat(),
                "finished_at_utc": finished.isoformat(),
                "duration_s": round(time.time() - t0, 2),
                "software": {"python": platform.python_version(), "numpy": np.__version__,
                             "rasterio": rasterio.__version__, "shapely": shapely.__version__},
            },
            "inputs": {
                "footprint": {"file_name": os.path.basename(cfg.input_geojson),
                              "feature_count": n_parcels, "crs": fp["crs"],
                              "id_source": fp["id_source"]},
                "dsm": {"file_name": os.path.basename(cfg.dsm_path),
                        "crs": CRS.from_user_input(dsm_src.crs).to_string(),
                        "resolution_x": abs(dsm_src.transform.a),
                        "resolution_y": abs(dsm_src.transform.e),
                        "resolution_unit": dsm_unit},
                "dtm": {"file_name": os.path.basename(cfg.dtm_path),
                        "crs": CRS.from_user_input(grid.dtm_src.crs).to_string(),
                        "resolution_x": dtm_res[0], "resolution_y": dtm_res[1],
                        "resolution_unit": dtm_unit,
                        "ground_source_type": cfg.ground_source_type},
            },
            "processing": {
                "working_crs": work_crs.to_string(),
                "output_crs": "EPSG:4326",
                "analysis_grid_source": ANALYSIS_GRID_SOURCE,
                "analysis_resolution_x_m": round(grid.res_x, 6),
                "analysis_resolution_y_m": round(grid.res_y, 6),
                "dsm_reprojected": grid.dsm_warped,
                "terrain_normalization": True,
                "dtm_resampling": DTM_RESAMPLING,
                "orientation_convention": "azimuth of the longest MRR edge, clockwise "
                                          "from working_crs grid north, range [0,180)",
                "height_clustering": "kmeans_1d (quantile init, exact 1D Lloyd, "
                                     "sorted prefix-sum)",
                "parameters": params,
                "execution": {"workers": n_workers, "chunk_size": chunk_size,
                              "gdal_cache_mb": int(cfg.gdal_cache_mb),
                              "processing_order": "dsm_tile_row_major",
                              "output_order": "input_order"},
            },
            "vertical_reference": {
                "mode": "terrain_normalized",
                "dtm_used": True,
                "height_surface": "nDSM",
                "ground_source": "DTM",
                "ground_source_type": cfg.ground_source_type,
                "base_elevation_stat": cfg.base_elevation_stat,
                "vertical_datum": cfg.vertical_datum,
            },
            "summary": {
                "building_count": len(roots),
                "decomposed_building_count": n_decomposed,
                "part_count": len(all_recs),
                "max_part_level": max(r["properties"]["part_level"] for r in all_recs),
                "max_top_height_agl_m": max(r["properties"]["top_height_agl_m"] for r in all_recs),
                "total_volume_m3": round(sum(r["properties"]["volume_m3"] for r in all_recs),
                                         cfg.round_digits),
                "skipped_building_count": len(skipped),
                "skipped_buildings": skipped,
                "validation": {"status": "passed", "checked_parts": len(all_recs)},
            },
        }

        _prog(n_parcels, n_parcels, "Writing GeoJSON...")
        fc = build_feature_collection(all_recs, cfg, meta)
        atomic_write_geojson(fc, cfg.output_geojson)
        _log(f"[done] Wrote {len(all_recs)} parts from {len(roots)} buildings to "
             f"{cfg.output_geojson} (EPSG:4326)")
        _prog(n_parcels, n_parcels, f"Complete — {len(all_recs)} parts")

        return {"output_path": cfg.output_geojson, "num_features": len(all_recs),
                "num_parcels": n_parcels, "num_buildings": len(roots),
                "num_skipped": len(skipped), "cancelled": False}
    finally:
        grid.close()
