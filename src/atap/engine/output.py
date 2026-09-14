# SPDX-License-Identifier: AGPL-3.0-only
"""Canonical FeatureCollection construction and atomic output writing."""

import json
import os
import tempfile

import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping
from shapely.geometry.polygon import orient

from .config import AtapError, Config
from .io import reproject_geom
from .polygon import as_polygonal, polygonal_parts


# =============================================================================
#                                  OUTPUT
# =============================================================================
def _to_output_geojson(geom_work, to_out: Transformer, digits: int) -> dict:
    g = reproject_geom(geom_work, to_out)
    if not g.is_valid:
        g = as_polygonal(polygonal_parts(g))
    if g is None or g.is_empty:
        raise AtapError("Output geometry cannot be repaired after reprojection.")
    r = shapely.set_precision(g, 10.0 ** (-digits), mode="pointwise")
    if r.is_valid and not r.is_empty:
        g = r
    polys = [orient(p, sign=1.0) for p in polygonal_parts(g)]   # RFC 7946: exterior CCW
    if not polys:
        raise AtapError("Output geometry is empty after reprojection.")
    return mapping(as_polygonal(polys))


def build_feature_collection(recs, cfg: Config, meta: dict) -> dict:
    to_out = Transformer.from_crs(CRS.from_user_input(cfg.working_crs),
                                  CRS.from_epsg(4326), always_xy=True)
    feats = []
    for r in recs:
        feats.append({"type": "Feature", "id": r["id"], "properties": r["properties"],
                      "geometry": _to_output_geojson(r["geom_work"], to_out, cfg.coord_digits)})
    fc = {"type": "FeatureCollection",
          "name": os.path.splitext(os.path.basename(cfg.output_geojson))[0]}
    fc.update(meta)
    fc["features"] = feats
    return fc


def atomic_write_geojson(obj: dict, path: str):
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".atap_", suffix=".geojson.tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
