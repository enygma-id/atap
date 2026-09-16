# SPDX-License-Identifier: AGPL-3.0-only
"""Hierarchical part construction and vertical interval assignment."""

from dataclasses import dataclass
from typing import Any

import numpy as np
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from shapely.ops import unary_union

from .config import CANONICAL_KEYS, Config
from .height import (
    compute_ndsm,
    configured_ground_stat,
    footprint_aware_level_merge,
    kmeans_1d,
    merge_close_centers,
)
from .io import _jsonable
from .metrics import geometry_metrics, raster_evidence
from .polygon import (
    as_polygonal,
    cleanup_mask,
    enforce_containment,
    fill_small_holes,
    polygonal_parts,
    polygonize_mask,
    regularize_polygon,
)


# =============================================================================
#                   PER BUILDING: hierarchical decomposition
# =============================================================================
@dataclass
class _Part:
    geom: Any
    det_level: int                 # Detected level index (0 is the root).
    part_level: int                # Hierarchy depth = parent.part_level + 1.
    parent: int | None             # Parent _Part index (None for the root).
    top_agl: float                 # Rounded height.
    reason: str
    method: str
    containment: float | None = None
    support: np.ndarray | None = None


def process_parcel(root_geom, dtm, dsm, wt, cfg: Config) -> dict:
    rd = cfg.round_digits
    shape = dsm.shape
    inside = geometry_mask([mapping(root_geom)], out_shape=shape, transform=wt, invert=True)
    valid = inside & np.isfinite(dsm) & np.isfinite(dtm)
    if int(valid.sum()) < 1:
        return {"status": "skipped", "reason": "NO_VALID_DSM_DTM_PIXELS"}

    ndsm = compute_ndsm(dsm, dtm)
    ground = round(configured_ground_stat(dtm[valid], cfg.base_elevation_stat), rd)

    bld = valid & (ndsm >= cfg.min_building_height_m)
    heights = ndsm[bld]
    pixel_area = abs(wt.a * wt.e)

    def single(h: float, reason: str) -> dict:
        root = _Part(geom=root_geom, det_level=0, part_level=0, parent=None,
                     top_agl=round(max(h, 0.0), rd), reason=reason,
                     method="authoritative_footprint", support=bld)
        return {"status": "ok", "ground": ground, "parts": [root],
                "valid": valid, "shape": shape}

    if heights.size < 3:
        return single(float(np.nanmean(ndsm[valid])), "SINGLE_MASS_INSUFFICIENT_BUILDING_PIXELS")

    p_lo, p_hi = np.nanpercentile(heights, [5, 95])
    if float(p_hi - p_lo) < cfg.height_diff_threshold_m:
        return single(float(np.nanmean(heights)), "SINGLE_MASS_UNIFORM_HEIGHT")

    labels, centers = kmeans_1d(heights, cfg.max_height_classes)
    if labels is None:
        return single(float(np.nanmean(heights)), "SINGLE_MASS_UNIFORM_HEIGHT")

    labels, mcenters = merge_close_centers(heights, labels, centers, cfg.height_diff_threshold_m)
    if mcenters.size <= 1:
        return single(float(mcenters[0]), "SINGLE_MASS_SINGLE_HEIGHT_CLASS")

    full_lbl = np.full(shape, -1, dtype="int64")
    full_lbl[bld] = labels
    sorted_idx = np.argsort(mcenters)
    sorted_centers = mcenters[sorted_idx]

    level_classes, level_heights = footprint_aware_level_merge(
        full_lbl, sorted_idx, sorted_centers, cfg.min_footprint_change_ratio)
    level_h = [round(h, rd) for h in level_heights]

    if len(level_classes) == 1:
        return single(level_heights[0], "SINGLE_MASS_NO_FOOTPRINT_CHANGE")

    # ---- Root = footprint authoritative ----
    parts: list[_Part] = [_Part(geom=root_geom, det_level=0, part_level=0, parent=None,
                                top_agl=level_h[0], reason="AUTHORITATIVE_ROOT",
                                method="authoritative_footprint", support=bld)]
    min_keep = cfg.min_subregion_area_m2 * 0.5
    prev_mask = inside

    for lvl in range(1, len(level_classes)):
        raw_mask = np.isin(full_lbl, sorted_idx[level_classes[lvl]:])   # cumulative
        m = cleanup_mask(raw_mask, cfg.morph_closing_iters)
        m = fill_small_holes(m, cfg.max_fill_hole_area_m2, pixel_area)
        m &= prev_mask                    # Raster nesting: upper level is inside lower.
        prev_mask = m

        cands = []
        for poly in polygonize_mask(m, wt):
            if poly.area < cfg.min_subregion_area_m2:
                continue
            reg, method = regularize_polygon(poly, cfg)
            if reg is None or reg.area < min_keep:
                continue
            reg = enforce_containment(reg, root_geom)
            if reg is None or reg.area < min_keep:
                continue
            cands.append((reg, method))
        cands.sort(key=lambda t: t[0].area, reverse=True)

        accepted_this_level: list[Any] = []
        for geom, method in cands:
            # Prefer an explicit parent at level - 1, then ancestors, then the root.
            chosen, score = 0, 1.0
            for lv in range(lvl - 1, -1, -1):
                best_i, best_s = None, 0.0
                for i, p in enumerate(parts):
                    if p.det_level != lv:
                        continue
                    s = geom.intersection(p.geom).area / geom.area if geom.area > 0 else 0.0
                    if s > best_s or (s == best_s and best_i is not None
                                      and p.geom.area > parts[best_i].geom.area):
                        best_i, best_s = i, s
                need = cfg.parent_min_containment_ratio if lv > 0 else 0.0
                if best_i is not None and best_s >= need and best_s > 0:
                    chosen, score = best_i, best_s
                    break
            parent = parts[chosen]

            g = enforce_containment(geom, parent.geom)
            if g is None:
                continue
            # Ancestor fallback removes intermediate-level overlap so vertical
            # intervals remain non-overlapping.
            between = [p.geom for p in parts if parent.det_level < p.det_level < lvl]
            # Remove same-level sibling overlap introduced by regularization.
            blockers = between + accepted_this_level
            if blockers:
                g = as_polygonal(polygonal_parts(g.difference(unary_union(blockers))))
                if g is None:
                    continue

            if level_h[lvl] - parent.top_agl <= 0:
                continue
            reason = ("HEIGHT_AND_FOOTPRINT_CHANGE" if parent.det_level == lvl - 1
                      else "HEIGHT_AND_FOOTPRINT_CHANGE_ANCESTOR_FALLBACK")
            for piece in polygonal_parts(g):
                if piece.area < min_keep:
                    continue
                parts.append(_Part(geom=piece, det_level=lvl,
                                   part_level=parent.part_level + 1, parent=chosen,
                                   top_agl=level_h[lvl], reason=reason, method=method,
                                   containment=round(float(score), 4), support=raw_mask))
                accepted_this_level.append(piece)

    if len(parts) == 1:
        parts[0].reason = "SINGLE_MASS_DERIVED_PARTS_FILTERED"

    return {"status": "ok", "ground": ground, "parts": parts, "valid": valid, "shape": shape}


# =============================================================================
#            HIERARCHY: ID, interval vertikal, properti  (spec §13, §33-34)
# =============================================================================
def build_part_records(object_id: str, result: dict, wt, src_props: dict, cfg: Config) -> list[dict]:
    rd = cfg.round_digits
    parts: list[_Part] = result["parts"]
    ground = result["ground"]
    ids = [f"{object_id}-P{i:02d}" for i in range(len(parts))]   # root = P00

    recs = []
    for i, p in enumerate(parts):
        parent = parts[p.parent] if p.parent is not None else None
        base = parent.top_agl if parent is not None else 0.0
        top = p.top_agl
        height = round(top - base, rd)
        met = geometry_metrics(p.geom)
        ev = raster_evidence(p.geom, wt, result["shape"], result["valid"], p.support)
        area = round(met["area"], rd)

        props = {
            "object_id": object_id,
            "part_id": ids[i],
            "parent_part_id": ids[p.parent] if p.parent is not None else None,
            "part_level": int(p.part_level),

            "ground_elevation_m": ground,

            "base_height_agl_m": round(base, rd),
            "top_height_agl_m": round(top, rd),
            "part_height_m": height,

            "base_elevation_m": round(ground + base, rd),
            "top_elevation_m": round(ground + top, rd),

            "area_m2": area,
            "perimeter_m": round(met["perimeter"], rd),
            "oriented_length_m": round(met["length"], rd),
            "oriented_width_m": round(met["width"], rd),
            "dimension_method": "minimum_rotated_rectangle",
            "orientation_deg": round(met["orientation"], rd),

            "volume_m3": round(area * height, rd),   # net area (hole dikurangi)

            "delta_z_m": height,

            "expected_pixel_count": ev["expected"],
            "valid_pixel_count": ev["valid"],
            "support_pixel_count": ev["support"],
            "valid_coverage_ratio": round(ev["coverage"], 4),

            "decomposition_reason": p.reason,
            "parent_containment_ratio": p.containment,
            "interior_ring_count": met["interior_rings"],
            "geometry_method": p.method,
        }
        for k, v in src_props.items():
            key = f"src_{k}" if k in CANONICAL_KEYS else k
            props[key] = _jsonable(v)
        recs.append({"id": ids[i], "properties": props, "geom_work": p.geom})
    return recs
