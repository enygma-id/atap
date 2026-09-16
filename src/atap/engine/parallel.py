# SPDX-License-Identifier: AGPL-3.0-only
"""Deterministic building-level execution using spawn workers."""

import os

from pyproj import CRS

from .config import Config
from .hierarchy import build_part_records, process_parcel
from .raster import (
    AnalysisGrid,
    align_dtm_to_dsm,
    gdal_cache_env,
    open_dsm_master_grid,
    read_building_window,
)

# Automatic mode targets four workers on every platform. Manual selection is
# capped at eight to bound spawned process, raster-handle, and memory pressure.
AUTO_WORKERS = 4
MAX_WORKERS = 8


def resolve_workers(requested: int, n_tasks: int) -> int:
    if requested and requested > 0:
        w = min(MAX_WORKERS, int(requested))
    else:
        w = min(AUTO_WORKERS, os.cpu_count() or 1)
    return max(1, min(w, n_tasks))


def cache_per_worker(total_mb: int, n_workers: int) -> int:
    """Split the configured job cache without exceeding its total budget."""
    return max(1, int(total_mb) // max(1, int(n_workers)))


def spatial_order(records, grid: AnalysisGrid) -> list[int]:
    """Order buildings by DSM tile in row-major order for block-cache reuse."""
    if not grid.dsm_warped and grid.dsm_src.block_shapes:
        bh, bw = grid.dsm_src.block_shapes[0]
    else:
        bh = bw = 256
    inv = ~grid.transform
    keys = []
    for i, (_, geom, _) in enumerate(records):
        if geom is None:
            keys.append((-1, -1, i))
            continue
        minx, miny, maxx, maxy = geom.bounds
        col, row = inv * ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
        keys.append((int(row // bh), int(col // bw), i))
    return [k[2] for k in sorted(keys)]


def process_building(oid: str, geom, props: dict, grid: AnalysisGrid, cfg: Config,
                     pad: int, keep: list[str]) -> dict:
    """Process one building and return records or a stable skipped reason."""
    if geom is None:
        return {"kind": "skipped", "reason": "INVALID_OR_EMPTY_FOOTPRINT"}
    win = read_building_window(geom, grid, pad)
    if win is None:
        return {"kind": "skipped", "reason": "OUTSIDE_ANALYSIS_GRID"}
    dtm, dsm, wt = win
    res = process_parcel(geom, dtm, dsm, wt, cfg)
    if res["status"] != "ok":
        return {"kind": "skipped", "reason": res["reason"]}
    src_props = {k: props[k] for k in keep if k in props}
    return {"kind": "ok", "decomposed": len(res["parts"]) > 1,
            "recs": build_part_records(oid, res, wt, src_props, cfg)}


# Per-process state initialized once in each spawned worker.
_WORKER: dict = {}


def _worker_init(cfg: Config, cache_mb: int):
    env = gdal_cache_env(cache_mb)
    env.__enter__()                      # Active for the worker lifetime.
    work_crs = CRS.from_user_input(cfg.working_crs)
    dsm_src, dsm_reader, dsm_warped = open_dsm_master_grid(cfg, work_crs)
    grid = align_dtm_to_dsm(cfg, work_crs, dsm_src, dsm_reader, dsm_warped)
    _WORKER.update(env=env, cfg=cfg, grid=grid,
                   pad=max(1, int(cfg.morph_closing_iters) + 2),
                   keep=list(cfg.keep_properties or []))


def _worker_chunk(items: list) -> list:
    w = _WORKER
    out = []
    for idx, oid, geom, props in items:
        try:
            out.append((idx, process_building(oid, geom, props, w["grid"], w["cfg"],
                                              w["pad"], w["keep"])))
        except Exception as e:
            raise RuntimeError(f"object_id {oid}: {type(e).__name__}: {e}") from e
    return out
