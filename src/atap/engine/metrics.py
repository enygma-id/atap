# SPDX-License-Identifier: AGPL-3.0-only
"""Geometry measurements and raster evidence."""

import math

import numpy as np
from rasterio.features import geometry_mask
from shapely.geometry import Polygon, mapping

from .polygon import polygonal_parts


# =============================================================================
#                                  METRICS
# =============================================================================
def geometry_metrics(geom) -> dict:
    parts = polygonal_parts(geom)
    rings = sum(len(p.interiors) for p in parts)
    length = width = 0.0
    orientation = 0.0
    mrr = geom.minimum_rotated_rectangle
    if isinstance(mrr, Polygon) and not mrr.is_empty:
        c = list(mrr.exterior.coords)
        e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
        e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
        l0, l1 = math.hypot(*e0), math.hypot(*e1)
        long_edge = e0 if l0 >= l1 else e1
        length, width = max(l0, l1), min(l0, l1)
        # Azimuth of the longest side, clockwise from working-grid north.
        orientation = math.degrees(math.atan2(long_edge[0], long_edge[1])) % 180.0
    return {"area": float(geom.area), "perimeter": float(geom.length),
            "length": length, "width": width, "orientation": orientation,
            "interior_rings": rings}


def raster_evidence(geom, wt, shape, valid: np.ndarray, support: np.ndarray) -> dict:
    m = geometry_mask([mapping(geom)], out_shape=shape, transform=wt, invert=True)
    exp = int(m.sum())
    val = int((m & valid).sum())
    sup = int((m & support).sum())
    return {"expected": exp, "valid": val, "support": sup,
            "coverage": (val / exp) if exp > 0 else 0.0}
