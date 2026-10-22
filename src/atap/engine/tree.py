# SPDX-License-Identifier: AGPL-3.0-only
"""
Tree canopy extraction, Individual Tree Detection (ITD), LoD 1.3 canopy
decomposition, and pantropical allometric carbon estimation.
"""

from __future__ import annotations

import collections
import json
import math
import os
import time
from typing import Callable

import numpy as np
import rasterio
import rasterio.features
import rasterio.windows
import scipy.ndimage as ndi
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import transform as sh_transform

from .config import AtapInputError, Config
from .io import load_footprints
from .output import atomic_write_geojson
from .raster import AnalysisGrid, align_dtm_to_dsm, open_dsm_master_grid


# =============================================================================
#                            ALLOMETRIC EQUATIONS
# =============================================================================
def compute_tree_allometrics(
    height_m: float,
    crown_diameter_m: float,
    wood_density: float = 0.57,
    carbon_fraction: float = 0.47,
) -> dict[str, float]:
    """
    Compute tree DBH, Above-Ground Biomass (AGB), Carbon stock, and CO2e.

    Formulas:
    1. DBH (cm): Pantropical crown-height allometry (Chave et al., 2014)
       DBH = 0.55 * (H ^ 0.92) * (D_crown ^ 0.42)
    2. AGB (kg): Pantropical AGB model (Chave et al., 2014)
       AGB = 0.0673 * (rho * DBH^2 * H) ^ 0.976
    3. Carbon (kg C): IPCC 2006 AFOLU Table 4.3 default carbon fraction
       Carbon = AGB * carbon_fraction
    4. CO2e (kg CO2e): Stoichiometric molecular weight ratio (44.009 / 12.011)
       CO2e = Carbon * 3.667
    5. Trunk diameter (m): Estimated DBH in meters with silvicultural minimum
       D_trunk = max(0.15, DBH / 100.0)
    """
    h = max(0.5, float(height_m))
    d_crown = max(0.5, float(crown_diameter_m))

    dbh_cm = round(0.55 * (h**0.92) * (d_crown**0.42), 1)
    agb_kg = round(0.0673 * ((wood_density * (dbh_cm**2) * h) ** 0.976), 1)
    carbon_kg = round(agb_kg * carbon_fraction, 1)
    co2e_kg = round(carbon_kg * 3.667, 1)
    trunk_diam_m = round(max(0.15, dbh_cm / 100.0), 2)

    return {
        "dbh_cm": dbh_cm,
        "agb_kg": agb_kg,
        "carbon_kg": carbon_kg,
        "co2e_kg": co2e_kg,
        "trunk_diameter_m": trunk_diam_m,
    }


# =============================================================================
#                       PRE-FILTERING & ZONAL PROFILING
# =============================================================================
def filter_and_profile_canopies(
    records: list[tuple[str, any, dict]],
    grid: AnalysisGrid,
    cfg: Config,
    _log: Callable[[str], None],
) -> tuple[list[dict], list[dict]]:
    """
    Stage 1: nDSM extraction, rooftop & antenna rejection, and wall cleaning.
    """
    valid_canopies: list[dict] = []
    skipped: list[dict] = []

    min_h = getattr(cfg, "min_tree_height", 0.2)
    max_bio_h = getattr(cfg, "max_bio_height_m", 45.0)

    for oid, geom, props in records:
        if geom is None or geom.is_empty or geom.area <= 0:
            skipped.append({"object_id": oid, "reason": "INVALID_OR_EMPTY_FOOTPRINT"})
            continue

        minx, miny, maxx, maxy = geom.bounds
        win = rasterio.windows.from_bounds(minx, miny, maxx, maxy, transform=grid.transform)
        col_off = max(0, int(win.col_off) - 1)
        row_off = max(0, int(win.row_off) - 1)
        width = min(grid.width - col_off, int(win.width) + 3)
        height = min(grid.height - row_off, int(win.height) + 3)

        if width <= 2 or height <= 2:
            skipped.append({"object_id": oid, "reason": "OUTSIDE_ANALYSIS_GRID"})
            continue

        w_adj = rasterio.windows.Window(col_off, row_off, width, height)
        win_trans = rasterio.windows.transform(w_adj, grid.transform)

        sub_dsm = grid.dsm_reader.read(1, window=w_adj, masked=True).astype("float64")
        sub_dtm = grid.dtm_reader.read(1, window=w_adj, masked=True).astype("float64")

        dsm_arr = np.ma.filled(sub_dsm, np.nan)
        dtm_arr = np.ma.filled(sub_dtm, np.nan)

        mask = rasterio.features.rasterize(
            [geom], out_shape=dsm_arr.shape, transform=win_trans, default_value=1, fill=0
        ).astype(bool)

        valid_mask = mask & np.isfinite(dsm_arr) & np.isfinite(dtm_arr)
        if int(np.sum(valid_mask)) < 3:
            skipped.append({"object_id": oid, "reason": "NO_VALID_RASTER_DATA"})
            continue

        raw_ndsm = np.clip(dsm_arr - dtm_arr, 0.0, 150.0)
        vals = raw_ndsm[valid_mask]
        dtm_vals = dtm_arr[valid_mask]

        valid_dtm = dtm_vals[(dtm_vals > -20.0) & (dtm_vals < 2000.0)]
        ground_z = float(np.median(valid_dtm)) if len(valid_dtm) > 0 else 0.0

        p25, p50, p75, p90, p95, pmax = np.percentile(vals, [25, 50, 75, 90, 95, 100])
        min_v = float(np.min(vals))
        area = geom.area

        # 1. Rooftop rejection
        if (
            (p25 >= 20.0 and area < 50.0)
            or (p50 >= 30.0 and area < 100.0)
            or (min_v >= 20.0 and area < 50.0)
        ):
            skipped.append({"object_id": oid, "reason": "ROOFTOP_STRUCTURE"})
            continue

        # 2. Antenna or telecommunication tower
        if area < 8.0 and p90 >= 25.0:
            skipped.append({"object_id": oid, "reason": "ANTENNA_OR_TOWER"})
            continue

        # 3. Ground / grass / sub-sapling
        if p90 < min_h:
            skipped.append({"object_id": oid, "reason": "LOW_VEGETATION_OR_GROUND"})
            continue

        # 4. Building wall boundary spillover cleaning
        clean_apex = p95
        if p50 < 20.0 and pmax >= 25.0:
            iqr = max(2.0, p75 - p25)
            wall_thresh = min(35.0, p50 + 2.5 * iqr)
            wall_mask = valid_mask & (raw_ndsm > wall_thresh)
            clean_vals = raw_ndsm[valid_mask & (~wall_mask) & (raw_ndsm > 0)]
            if len(clean_vals) >= 3:
                clean_apex = float(np.percentile(clean_vals, 95))
            else:
                clean_apex = p50

        clean_apex = min(clean_apex, max_bio_h)

        valid_canopies.append(
            {
                "oid": oid,
                "geom": geom,
                "props": props,
                "area": area,
                "ground_z": ground_z,
                "clean_apex": clean_apex,
                "p50": float(p50),
                "p90": float(p90),
                "win": w_adj,
                "win_trans": win_trans,
            }
        )

    _log(
        f"[tree] Stage 1 (Profiling): {len(valid_canopies)} valid trees, {len(skipped)} filtered out."
    )
    return valid_canopies, skipped


# =============================================================================
#                 INDIVIDUAL TREE DETECTION (ITD) WATERSHED
# =============================================================================
def split_canopy_clusters_itd(
    valid_canopies: list[dict],
    grid: AnalysisGrid,
    cfg: Config,
    _log: Callable[[str], None],
) -> list[dict]:
    """
    Stage 2: Split multi-tree clusters (area >= cluster_min_area_m2) into
    individual trees using Local Maxima and Marker-Controlled Watershed.
    Aliran 1:1 identik dengan pipeline coba yang terverifikasi dan optimal:
    1. Filter Gaussian smoothing sigma = 0.85
    2. Deteksi puncak apikal lokal (Local Maxima) dengan ambang biologis datar min_tree_height
    3. Watershed IFT untuk memotong kluster kanopi multi-pohon (area >= 35 m2)
    4. Ekstraksi koordinat puncak apikal dan tinggi fisik murni pada nDSM asli
    """
    split_clusters = getattr(cfg, "split_clusters", True)
    min_cluster_area = getattr(cfg, "cluster_min_area_m2", 25.0)
    peak_dist_m = getattr(cfg, "itd_min_distance_m", 2.8)
    min_tree_h = getattr(cfg, "min_tree_height", 0.5)

    px_size = (abs(grid.transform.a) + abs(grid.transform.e)) / 2.0
    filter_size = max(3, int(round(peak_dist_m / px_size)))
    if filter_size % 2 == 0:
        filter_size += 1

    individual_trees: list[dict] = []
    n_split_clusters = 0

    for item in valid_canopies:
        oid = item["oid"]
        geom = item["geom"]
        area = item["area"]
        ground_z = item["ground_z"]
        clean_apex = item["clean_apex"]
        w_adj = item["win"]
        win_trans = item["win_trans"]

        # Read sub-raster window
        sub_dsm = grid.dsm_reader.read(1, window=w_adj, masked=True).astype("float64")
        sub_dtm = grid.dtm_reader.read(1, window=w_adj, masked=True).astype("float64")
        dsm_arr = np.ma.filled(sub_dsm, np.nan)
        dtm_arr = np.ma.filled(sub_dtm, np.nan)

        ndsm = np.clip(dsm_arr - dtm_arr, 0.0, 100.0)
        mask = rasterio.features.rasterize(
            [geom], out_shape=ndsm.shape, transform=win_trans, default_value=1, fill=0
        ).astype(bool)

        masked_ndsm = np.where(mask & np.isfinite(ndsm), ndsm, 0.0)
        # Smoothing sigma 0.85 (preservasi mikro-kontur tajuk pada resolusi tinggi)
        smoothed = ndi.gaussian_filter(masked_ndsm, sigma=0.85)

        if not split_clusters or area < min_cluster_area:
            # Single tree without splitting
            target = np.where(mask & np.isfinite(ndsm), ndsm, 0.0)
            py, px = np.unravel_index(
                np.argmax(target if np.any(target > 0) else smoothed), target.shape
            )
            val = float(target[py, px]) if target[py, px] > 0 else float(smoothed[py, px])
            peak_h = val if (val > 0 and np.isfinite(val)) else clean_apex
            peak_h = max(min_tree_h, min(peak_h, clean_apex))
            wx, wy = win_trans * (px + 0.5, py + 0.5)
            pt = Point(wx, wy)
            if not geom.contains(pt):
                pt = geom.representative_point()

            individual_trees.append(
                {
                    "tree_id": oid,
                    "parent_id": oid,
                    "geom": geom,
                    "ground_z": ground_z,
                    "height_apex": round(peak_h, 2),
                    "apex_x": round(pt.x, 7),
                    "apex_y": round(pt.y, 7),
                    "props": item["props"],
                }
            )
            continue

        # Kluster multi-pohon: cari puncak apikal lokal dengan VWF adaptif (min 2.5m)
        adaptive_dist = max(2.5, min(peak_dist_m, 0.32 * clean_apex))
        f_size = max(3, int(round(adaptive_dist / px_size)))
        if f_size % 2 == 0:
            f_size += 1
        local_max = (ndi.maximum_filter(smoothed, size=f_size) == smoothed) & (smoothed > 0)
        # Ambang batas flat biologis (tanpa pemotongan p50 * 0.5 yang membuang pohon bawah)
        peak_mask = local_max & mask & (smoothed >= min_tree_h)
        labeled_peaks, num_peaks = ndi.label(peak_mask)

        raw_candidates = []
        for m_idx in range(1, num_peaks + 1):
            m_mask = labeled_peaks == m_idx
            if np.any(m_mask):
                target = np.where(m_mask & np.isfinite(ndsm), ndsm, 0.0)
                m_py, m_px = np.unravel_index(np.argmax(target), target.shape)
                m_h = float(target[m_py, m_px])
                if m_h <= 0.0 or not np.isfinite(m_h):
                    m_h = float(smoothed[m_py, m_px]) if smoothed[m_py, m_px] > 0 else clean_apex
                if not np.isfinite(m_h):
                    m_h = clean_apex
                m_wx, m_wy = win_trans * (m_px + 0.5, m_py + 0.5)
                raw_candidates.append(
                    {
                        "py": m_py,
                        "px": m_px,
                        "wx": m_wx,
                        "wy": m_wy,
                        "h": max(min_tree_h, min(m_h, clean_apex)),
                    }
                )

        # Urutkan kandidat puncak dari tertinggi ke terendah
        raw_candidates.sort(key=lambda c: c["h"], reverse=True)

        # Filter Lembah / Saddle Prominence: satukan cabang samping ke puncak pohon yang sama
        saddle_min_drop = getattr(cfg, "saddle_min_drop_m", 1.2)
        accepted_peaks = []
        for cand in raw_candidates:
            is_branch = False
            for acc in accepted_peaks:
                dist_px = np.hypot(cand["py"] - acc["py"], cand["px"] - acc["px"])
                dist_m = dist_px * px_size
                if dist_m <= 12.0:
                    n_pts = max(int(dist_px), 2)
                    rr = np.linspace(cand["py"], acc["py"], n_pts).round().astype(int)
                    cc = np.linspace(cand["px"], acc["px"], n_pts).round().astype(int)
                    saddle_val = np.min(smoothed[rr, cc])
                    ref_h = min(cand["h"], acc["h"])
                    drop = ref_h - saddle_val
                    # Jika lembah pelana dangkal (< 1.2m atau < 18% tinggi), ini adalah cabang
                    if drop < saddle_min_drop or drop < (0.18 * ref_h):
                        is_branch = True
                        break
            if not is_branch:
                accepted_peaks.append(cand)

        if len(accepted_peaks) <= 1:
            target = np.where(mask & np.isfinite(ndsm), ndsm, 0.0)
            py, px = np.unravel_index(
                np.argmax(target if np.any(target > 0) else smoothed), target.shape
            )
            val = float(target[py, px]) if target[py, px] > 0 else float(smoothed[py, px])
            peak_h = val if (val > 0 and np.isfinite(val)) else clean_apex
            peak_h = max(min_tree_h, min(peak_h, clean_apex))
            wx, wy = win_trans * (px + 0.5, py + 0.5)
            pt = Point(wx, wy)
            if not geom.contains(pt):
                pt = geom.representative_point()

            individual_trees.append(
                {
                    "tree_id": oid,
                    "parent_id": oid,
                    "geom": geom,
                    "ground_z": ground_z,
                    "height_apex": round(peak_h, 2),
                    "apex_x": round(pt.x, 7),
                    "apex_y": round(pt.y, 7),
                    "props": item["props"],
                }
            )
            continue

        # Watershed segmentation dengan marker terseleksi
        ws_markers = np.zeros_like(smoothed, dtype=np.int32)
        marker_peaks = {}
        for m_idx, pk in enumerate(accepted_peaks, 1):
            ws_markers[pk["py"], pk["px"]] = m_idx
            marker_peaks[m_idx] = {
                "x": round(pk["wx"], 7),
                "y": round(pk["wy"], 7),
                "h": round(pk["h"], 2),
            }

        cost = np.clip((np.max(smoothed) - smoothed) * 1000.0, 0, 65535).astype(np.uint16)
        ws_labels = ndi.watershed_ift(cost, ws_markers)
        ws_labels[~mask] = 0

        # Vectorize sub-polygons
        shapes_gen = rasterio.features.shapes(
            ws_labels.astype(np.int32), mask=mask, transform=win_trans
        )
        sub_geoms: dict[int, list[Polygon]] = collections.defaultdict(list)

        for shp, val in shapes_gen:
            v_int = int(val)
            if v_int > 0:
                s_geom = shape(shp)
                if s_geom.is_valid and not s_geom.is_empty and s_geom.area >= 1.0:
                    sub_geoms[v_int].append(s_geom)

        created_trees = 0
        for p_idx, geoms in sub_geoms.items():
            if not geoms:
                continue
            merged = shapely.ops.unary_union(geoms)
            intersected = geom.intersection(merged)
            if intersected.is_empty or intersected.area < 1.0:
                continue

            if p_idx in marker_peaks:
                pk = marker_peaks[p_idx]
                wx, wy, h_val = pk["x"], pk["y"], pk["h"]
            else:
                c = (
                    intersected.centroid
                    if intersected.contains(intersected.centroid)
                    else intersected.representative_point()
                )
                wx, wy, h_val = c.x, c.y, clean_apex

            apex_pt = Point(wx, wy)
            if not intersected.contains(apex_pt):
                apex_pt = intersected.representative_point()

            t_height = max(min_tree_h, min(h_val, clean_apex))

            created_trees += 1
            individual_trees.append(
                {
                    "tree_id": f"{oid}_T{created_trees:02d}",
                    "parent_id": oid,
                    "geom": intersected,
                    "ground_z": ground_z,
                    "height_apex": round(t_height, 2),
                    "apex_x": round(apex_pt.x, 7),
                    "apex_y": round(apex_pt.y, 7),
                    "props": item["props"],
                }
            )

        if created_trees > 0:
            n_split_clusters += 1
        else:
            # Fallback to single tree
            pt = geom.representative_point()
            individual_trees.append(
                {
                    "tree_id": oid,
                    "parent_id": oid,
                    "geom": geom,
                    "ground_z": ground_z,
                    "height_apex": clean_apex,
                    "apex_x": pt.x,
                    "apex_y": pt.y,
                    "props": item["props"],
                }
            )

    # Pastikan seluruh ID pohon individual 100% unik bebas tabrakan
    seen_ids = set()
    unique_trees = []
    for t in individual_trees:
        cid = str(t["tree_id"])
        if cid in seen_ids:
            k = 1
            new_id = f"{cid}_{k:02d}"
            while new_id in seen_ids:
                k += 1
                new_id = f"{cid}_{k:02d}"
            t["tree_id"] = new_id
            cid = new_id
        seen_ids.add(cid)
        unique_trees.append(t)
    individual_trees = unique_trees

    _log(
        f"[tree] Stage 2 (ITD): {n_split_clusters} clusters decomposed into {len(individual_trees)} individual trees."
    )
    return individual_trees


# =============================================================================
#                   LOD 1.3 CANOPY & 3D POINT GENERATION
# =============================================================================
def decompose_tree_models(
    trees: list[dict],
    grid: AnalysisGrid,
    work_crs: CRS,
    cfg: Config,
    _log: Callable[[str], None],
) -> tuple[dict, dict, dict]:
    """
    Stage 3: Decompose tree canopies into LoD 1.3 elevated polygons using
    in-memory 1D K-Means clustering (matching coba ATAP decomposition),
    synthesize tree trunk points, and compute pantropical allometric carbon stocks.
    """
    to_wgs = Transformer.from_crs(work_crs, CRS.from_epsg(4326), always_xy=True).transform

    trunk_ratio = getattr(cfg, "trunk_ratio", 0.35)
    wood_density = getattr(cfg, "wood_density", 0.57)
    carbon_fraction = getattr(cfg, "carbon_fraction", 0.47)
    coord_digits = getattr(cfg, "coord_digits", 6)

    canopy_features: list[dict] = []
    point_features: list[dict] = []

    total_carbon_kg = 0.0
    total_co2e_kg = 0.0
    heights: list[float] = []

    for t in trees:
        tid = t["tree_id"]
        pid = t["parent_id"]
        t_geom = t["geom"]
        gz = t["ground_z"]
        h_apex = t["height_apex"]
        ax_work, ay_work = t["apex_x"], t["apex_y"]

        c_area = round(t_geom.area, 2)
        c_diam_geom = round(2.0 * math.sqrt(max(0.1, c_area) / math.pi), 2)
        # Crown diameter preserves natural width from polygon footprint, capped only at biological max
        max_bio_diam = max(2.5, min(18.0, 1.5 * h_apex))
        c_diam = round(min(c_diam_geom, max_bio_diam), 2)

        # Silvicultural vertical partitioning (35% trunk : 65% canopy)
        trunk_h = round(h_apex * trunk_ratio, 2)
        crown_h = round(h_apex - trunk_h, 2)

        # Allometrics (Chave et al., 2014)
        allo = compute_tree_allometrics(h_apex, c_diam, wood_density, carbon_fraction)
        total_carbon_kg += allo["carbon_kg"]
        total_co2e_kg += allo["co2e_kg"]
        heights.append(h_apex)

        # WGS84 point coordinates
        lon, lat = to_wgs(ax_work, ay_work)
        lon = round(lon, coord_digits)
        lat = round(lat, coord_digits)

        point_features.append(
            {
                "type": "Feature",
                "id": tid,
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat, round(gz, 2)],
                },
                "properties": {
                    "id": tid,
                    "object_id": tid,
                    "parent_id": pid,
                    "height": round(h_apex, 2),
                    "height_lidar_m": round(h_apex, 2),
                    "crown_diameter": c_diam,
                    "crown_diameter_m": c_diam,
                    "crown_height": crown_h,
                    "trunk_height": trunk_h,
                    "trunk_diameter": allo["trunk_diameter_m"],
                    "dbh_cm": allo["dbh_cm"],
                    "ground_elevation_m": round(gz, 2),
                    "ground_z": round(gz, 2),
                    "agb_kg": allo["agb_kg"],
                    "carbon_kg": allo["carbon_kg"],
                    "co2e_kg": allo["co2e_kg"],
                    "longitude": lon,
                    "latitude": lat,
                },
            }
        )

        # Dekomposisi kanopi bertingkat LoD 1.3 organik (P00 dasar, P01 badan, P02 kubah)
        minx, miny, maxx, maxy = t_geom.bounds
        win = rasterio.windows.from_bounds(minx, miny, maxx, maxy, transform=grid.transform)
        col_off = max(0, int(win.col_off) - 1)
        row_off = max(0, int(win.row_off) - 1)
        width = min(grid.width - col_off, int(win.width) + 3)
        height = min(grid.height - row_off, int(win.height) + 3)

        sub_ndsm = None
        win_trans = None
        mask = None
        if width > 2 and height > 2:
            w_adj = rasterio.windows.Window(col_off, row_off, width, height)
            win_trans = rasterio.windows.transform(w_adj, grid.transform)
            sub_dsm = grid.dsm_reader.read(1, window=w_adj, masked=True).astype("float64")
            sub_dtm = grid.dtm_reader.read(1, window=w_adj, masked=True).astype("float64")
            dsm_arr = np.ma.filled(sub_dsm, np.nan)
            dtm_arr = np.ma.filled(sub_dtm, np.nan)
            sub_ndsm = np.clip(dsm_arr - dtm_arr, 0.0, 100.0)
            mask = rasterio.features.rasterize(
                [t_geom], out_shape=sub_ndsm.shape, transform=win_trans, default_value=1, fill=0
            ).astype(bool)

        n_tiers = 3 if crown_h >= 2.0 else (2 if crown_h >= 0.8 else 1)
        tier_step = crown_h / n_tiers

        parts_info = []
        for lvl in range(n_tiers):
            lvl_base_agl = round(trunk_h + lvl * tier_step, 2)
            lvl_top_agl = (
                round(trunk_h + (lvl + 1) * tier_step, 2) if lvl < n_tiers - 1 else round(h_apex, 2)
            )
            lvl_part_h = round(lvl_top_agl - lvl_base_agl, 2)
            if lvl_part_h <= 0.05:
                continue

            lvl_geom = None
            if lvl == 0:
                lvl_geom = t_geom
            else:
                # Potong nDSM vertikal pada ambang batas ketinggian undakan
                if sub_ndsm is not None and mask is not None:
                    h_thresh = lvl_base_agl
                    s_mask = mask & (sub_ndsm >= h_thresh)
                    if np.count_nonzero(s_mask) >= 3:
                        shapes_gen = rasterio.features.shapes(
                            s_mask.astype(np.int32), mask=s_mask, transform=win_trans
                        )
                        cand_geoms = []
                        for shp, val in shapes_gen:
                            if val == 1:
                                s_g = shape(shp)
                                if s_g.is_valid and not s_g.is_empty and s_g.area >= 0.2:
                                    cand_geoms.append(s_g)
                        if cand_geoms:
                            merged = shapely.ops.unary_union(cand_geoms)
                            inter = t_geom.intersection(merged)
                            if inter.is_valid and not inter.is_empty and inter.area >= 0.2:
                                lvl_geom = inter

                # Fallback ke erosi konsentris tajuk jika potongan nDSM tidak memadai
                if lvl_geom is None or lvl_geom.is_empty or lvl_geom.area < 0.2:
                    erode_frac = 0.20 if lvl == 1 else 0.40
                    buf_dist = -erode_frac * (c_diam / 2.0)
                    eroded = t_geom.buffer(buf_dist)
                    if eroded.is_valid and not eroded.is_empty and eroded.area >= 0.2:
                        lvl_geom = eroded
                    else:
                        apex_pt = Point(ax_work, ay_work)
                        lvl_geom = apex_pt.buffer(max(0.6, 0.3 * c_diam))

            if lvl_geom is not None and not lvl_geom.is_empty:
                parent_idx = lvl - 1 if lvl > 0 else None
                parts_info.append(
                    {
                        "lvl": lvl,
                        "parent_idx": parent_idx,
                        "geom": lvl_geom,
                        "base_agl": lvl_base_agl,
                        "top_agl": lvl_top_agl,
                        "part_h": lvl_part_h,
                    }
                )

        for idx, p in enumerate(parts_info):
            p_geom_wgs = sh_transform(to_wgs, p["geom"])
            p_geom_simp = p_geom_wgs.simplify(0.0000015, preserve_topology=True)
            if not p_geom_simp.is_valid or p_geom_simp.is_empty:
                p_geom_simp = p_geom_wgs

            part_id = f"{tid}-P{idx:02d}"
            parent_part_id = (
                f"{tid}-P{p['parent_idx']:02d}" if p["parent_idx"] is not None else None
            )

            canopy_features.append(
                {
                    "type": "Feature",
                    "id": part_id,
                    "geometry": mapping(p_geom_simp),
                    "properties": {
                        "object_id": tid,
                        "parent_id": pid,
                        "part_id": part_id,
                        "parent_part_id": parent_part_id,
                        "part_level": int(p["lvl"]),
                        "ground_elevation_m": round(gz, 2),
                        "base_height_agl_m": p["base_agl"],
                        "top_height_agl_m": p["top_agl"],
                        "part_height_m": p["part_h"],
                        "base_elevation_m": round(gz + p["base_agl"], 2),
                        "top_elevation_m": round(gz + p["top_agl"], 2),
                        "crown_diameter_m": c_diam,
                        "crown_area_m2": round(p["geom"].area, 2),
                        "total_tree_height_m": round(h_apex, 2),
                        "dbh_cm": allo["dbh_cm"],
                        "agb_kg": allo["agb_kg"],
                        "carbon_kg": allo["carbon_kg"],
                        "co2e_kg": allo["co2e_kg"],
                        "longitude": lon,
                        "latitude": lat,
                    },
                }
            )

    summary = {
        "mode": "tree",
        "total_trees": len(trees),
        "total_canopy_parts": len(canopy_features),
        "mean_height_m": round(float(np.mean(heights)), 2) if heights else 0.0,
        "min_height_m": round(float(np.min(heights)), 2) if heights else 0.0,
        "max_height_m": round(float(np.max(heights)), 2) if heights else 0.0,
        "total_carbon_mg": round(total_carbon_kg / 1000.0, 3),  # Metric Tons (Mg C)
        "total_co2e_mg": round(total_co2e_kg / 1000.0, 3),  # Metric Tons (Mg CO2e)
    }

    canopy_fc = {
        "type": "FeatureCollection",
        "name": "trees_canopy_polygons",
        "features": canopy_features,
    }

    points_fc = {
        "type": "FeatureCollection",
        "name": "trees_model_points",
        "features": point_features,
    }

    return canopy_fc, points_fc, summary


# =============================================================================
#                            MAIN TREE PIPELINE
# =============================================================================
def run_tree_pipeline(
    cfg: Config,
    progress_cb: Callable[[int, int, str], None] | None = None,
    log_cb: Callable[[str], None] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
) -> dict:
    """
    Execute the end-to-end tree canopy extraction and LoD 1.3 pipeline.
    """

    def _log(msg: str):
        (log_cb or print)(msg)

    def _prog(c: int, t: int, m: str):
        if progress_cb is not None:
            progress_cb(c, t, m)

    def _cancelled() -> bool:
        return bool(cancel_flag()) if cancel_flag is not None else False

    t0 = time.time()
    _log("[tree] Starting ATAP Tree Canopy Extraction & Allometrics Pipeline.")

    try:
        work_crs = CRS.from_user_input(cfg.working_crs)
    except Exception as e:
        raise AtapInputError(f"Invalid working_crs: {cfg.working_crs}") from e

    if not cfg.dtm_path or not os.path.isfile(cfg.dtm_path):
        raise AtapInputError(f"DTM raster is required and was not found: {cfg.dtm_path!r}")
    if not cfg.dsm_path or not os.path.isfile(cfg.dsm_path):
        raise AtapInputError(f"DSM raster is required and was not found: {cfg.dsm_path!r}")

    _prog(0, 0, "Loading tree canopy footprints...")
    fp = load_footprints(cfg, work_crs, _log)
    n_footprints = fp["feature_count"]
    _log(f"[tree] Loaded {n_footprints} canopy polygons.")

    if _cancelled():
        return {"cancelled": True}

    _prog(0, 0, "Aligning DTM and DSM analysis grid...")
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
        if _cancelled():
            return {"cancelled": True}

        _prog(1, 4, "Stage 1: Pre-filtering & Zonal Profiling...")
        valid_canopies, skipped = filter_and_profile_canopies(fp["records"], grid, cfg, _log)

        if _cancelled():
            return {"cancelled": True}

        _prog(2, 4, "Stage 2: Individual Tree Detection (ITD)...")
        individual_trees = split_canopy_clusters_itd(valid_canopies, grid, cfg, _log)

        if _cancelled():
            return {"cancelled": True}

        _prog(3, 4, "Stage 3: LoD 1.3 Decomposition & Allometrics...")
        canopy_fc, points_fc, summary = decompose_tree_models(
            individual_trees, grid, work_crs, cfg, _log
        )
        summary["skipped_tree_count"] = len(skipped)
        summary["skipped_trees"] = skipped
        summary["skipped_buildings"] = skipped
        canopy_fc["summary"] = summary

        if _cancelled():
            return {"cancelled": True}

        _prog(4, 4, "Stage 4: Writing output GeoJSON artifacts...")
        # 1. Canopy polygons output
        out_canopy_path = cfg.output_geojson
        atomic_write_geojson(canopy_fc, out_canopy_path)
        _log(
            f"[tree] Canopy parts written to: {out_canopy_path} ({len(canopy_fc['features'])} parts)"
        )

        # 2. Companion points output
        base, ext = os.path.splitext(out_canopy_path)
        points_path = f"{base}_points.geojson"
        atomic_write_geojson(points_fc, points_path)
        _log(
            f"[tree] Tree model points written to: {points_path} ({len(points_fc['features'])} trees)"
        )

        # 3. Summary report
        summary_path = f"{base}_summary.json"
        summary["output_canopy"] = out_canopy_path
        summary["output_points"] = points_path
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        _log(f"[tree] Summary KPI report written to: {summary_path}")

        elapsed = round(time.time() - t0, 2)
        _log(
            f"[tree] Pipeline completed in {elapsed}s: {summary['total_trees']} trees, "
            f"{summary['total_carbon_mg']} Mg C."
        )

        return {
            "output_path": out_canopy_path,
            "points_path": points_path,
            "summary_path": summary_path,
            "num_features": len(canopy_fc["features"]),
            "num_trees": summary["total_trees"],
            "num_skipped": len(skipped),
            "summary": summary,
            "cancelled": False,
        }

    finally:
        for h in (grid.dtm_reader, grid.dtm_src, grid.dsm_reader, grid.dsm_src):
            try:
                h.close()
            except Exception:
                pass
