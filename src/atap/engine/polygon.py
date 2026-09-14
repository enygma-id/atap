# SPDX-License-Identifier: AGPL-3.0-only
"""Mask cleanup, polygonization, regularization, and containment."""

import math
from typing import Any

import numpy as np
import shapely
from rasterio.features import shapes as raster_shapes
from scipy import ndimage as ndi
from shapely.affinity import rotate
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry import shape as shp_shape
from shapely.ops import unary_union

from .config import Config


# =============================================================================
#                          GEOMETRI: helper umum
# =============================================================================
def polygonal_parts(geom) -> list[Polygon]:
    """Repair geometry and return positive-area polygon components."""
    if geom is None or geom.is_empty:
        return []
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    out: list[Polygon] = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if g.is_empty:
            continue
        if isinstance(g, Polygon):
            if g.area > 0:
                out.append(g)
        elif hasattr(g, "geoms"):
            stack.extend(g.geoms)
    return out


def as_polygonal(parts: list[Polygon]):
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts)


# =============================================================================
#               POLYGON: cleanup, hole, polygonize, regularize, containment
# =============================================================================
def circularity(poly: Polygon) -> float:
    p = poly.length
    if p <= 0:
        return 0.0
    return float(4.0 * math.pi * poly.area / (p * p))


def orthogonalize(poly: Polygon, angle_tol_deg: float = 18.0) -> Polygon:
    try:
        mrr = poly.minimum_rotated_rectangle
        mc = list(mrr.exterior.coords)
        edges = [(mc[i], mc[i + 1]) for i in range(len(mc) - 1)]
        longest = max(edges, key=lambda e: (e[1][0] - e[0][0]) ** 2 + (e[1][1] - e[0][1]) ** 2)
        theta = math.degrees(math.atan2(longest[1][1] - longest[0][1],
                                        longest[1][0] - longest[0][0]))
        cen = poly.centroid
        rp = rotate(poly, -theta, origin=cen, use_radians=False)
        coords = list(rp.exterior.coords)[:-1]
        n = len(coords)
        if n < 4:
            return poly

        lines = []
        for i in range(n):
            x0, y0 = coords[i]
            x1, y1 = coords[(i + 1) % n]
            a = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
            dh = min(a, 180.0 - a)
            dv = abs(a - 90.0)
            if dh <= dv:
                lines.append(("h", (y0 + y1) / 2.0))
            else:
                lines.append(("v", (x0 + x1) / 2.0))

        merged = []
        i = 0
        while i < len(lines):
            o, c = lines[i]
            cs = [c]
            j = i + 1
            while j < len(lines) and lines[j][0] == o:
                cs.append(lines[j][1])
                j += 1
            merged.append((o, float(np.mean(cs))))
            i = j
        if len(merged) >= 2 and merged[0][0] == merged[-1][0]:
            o, c0 = merged[0]
            _, c1 = merged.pop()
            merged[0] = (o, (c0 + c1) / 2.0)

        m = len(merged)
        if m < 4 or m % 2 != 0:
            return mrr

        pts = []
        for i in range(m):
            o1, c1 = merged[i]
            o2, c2 = merged[(i + 1) % m]
            if o1 == o2:
                return mrr
            if o1 == "h":
                pts.append((c2, c1))
            else:
                pts.append((c1, c2))
        new = Polygon(pts)
        new = rotate(new, theta, origin=cen, use_radians=False)
        new = new.buffer(0)
        if new.is_empty or not new.is_valid or new.area <= 0:
            return poly
        return new
    except Exception:
        return poly


def cleanup_mask(mask: np.ndarray, iters: int) -> np.ndarray:
    if iters > 0 and mask.any():
        mask = ndi.binary_closing(mask, iterations=iters) | mask
    return mask


def fill_small_holes(mask: np.ndarray, max_area_m2: float, pixel_area_m2: float) -> np.ndarray:
    """Fill holes up to max_area_m2 while preserving larger interior voids."""
    if max_area_m2 <= 0 or not mask.any():
        return mask
    holes = ndi.binary_fill_holes(mask) & ~mask
    if not holes.any():
        return mask
    lbl, n = ndi.label(holes)
    sizes = np.asarray(ndi.sum(holes, lbl, index=np.arange(1, n + 1)), dtype="float64")
    small = np.zeros(n + 1, dtype=bool)
    small[1:] = sizes * pixel_area_m2 <= max_area_m2
    return mask | small[lbl]


def polygonize_mask(mask: np.ndarray, transform) -> list[Polygon]:
    if not mask.any():
        return []
    out: list[Polygon] = []
    for geom, val in raster_shapes(mask.astype("uint8"), mask=mask,
                                   transform=transform, connectivity=8):
        if val != 1:
            continue
        out.extend(polygonal_parts(shp_shape(geom)))
    return out


def regularize_polygon(poly: Polygon, cfg: Config) -> tuple[Any | None, str]:
    """
    Regularize the shell, then subtract meaningful interior holes so
    courtyards survive simplification and shape regularization.
    """
    shell = Polygon(poly.exterior)
    holes = [Polygon(r) for r in poly.interiors]
    holes = [h for h in holes if h.area > cfg.max_fill_hole_area_m2]

    simp = shell.simplify(cfg.simplify_tolerance_m, preserve_topology=True)
    if simp.is_empty or simp.area <= 0:
        simp = shell

    method = "simplified"
    out_shell = simp
    if cfg.regularize:
        if circularity(simp) >= cfg.circularity_threshold:
            try:
                out_shell, method = shapely.minimum_bounding_circle(simp), "minimum_bounding_circle"
            except Exception:
                pass
        else:
            try:
                mrr = simp.minimum_rotated_rectangle
                if mrr.area > 0 and (simp.area / mrr.area) >= cfg.rectangular_ratio:
                    out_shell, method = mrr, "minimum_rotated_rectangle"
                else:
                    out_shell, method = orthogonalize(simp), "orthogonalized"
            except Exception:
                out_shell, method = orthogonalize(simp), "orthogonalized"

    geom = out_shell
    if holes:
        hs = [h.simplify(cfg.simplify_tolerance_m, preserve_topology=True) for h in holes]
        geom = out_shell.difference(unary_union(hs))
    return as_polygonal(polygonal_parts(geom)), method


def enforce_containment(geom, parent_geom):
    """child = child ∩ authoritative parent (spec §7)."""
    return as_polygonal(polygonal_parts(geom.intersection(parent_geom)))
