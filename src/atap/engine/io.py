# SPDX-License-Identifier: AGPL-3.0-only
"""Footprint loading, identifiers, serialization, and reprojection."""

import json
import math
import os
from typing import Any

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import shape as shp_shape

from .config import AtapInputError, Config
from .polygon import as_polygonal, polygonal_parts


def reproject_geom(geom, transformer: Transformer):
    def _f(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])
    return shapely.transform(geom, _f)


def is_metric_projected(crs: CRS) -> bool:
    if not crs.is_projected:
        return False
    units = {(a.unit_name or "").lower() for a in crs.axis_info[:2]}
    return bool(units) and all(u in ("metre", "meter", "m") for u in units)


# =============================================================================
#                   INPUT: footprint + stable object ID  (spec Â§7, Â§13)
# =============================================================================
def _normalize_id(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(float(v)):
            return None
        return str(int(v)) if float(v).is_integer() else repr(float(v))
    s = str(v).strip()
    return s or None


def _jsonable(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (str, int, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


def _crs_from_geojson(doc: dict) -> tuple[CRS, str]:
    """Read the legacy GeoJSON CRS member, otherwise use the RFC 7946 WGS84 default."""
    c = doc.get("crs")
    if c:
        name = (c.get("properties") or {}).get("name") if isinstance(c, dict) else None
        if not name:
            raise AtapInputError("The GeoJSON 'crs' member cannot be read.")
        try:
            return CRS.from_user_input(name), name
        except Exception as e:
            raise AtapInputError(f"Unknown footprint CRS '{name}': {e}") from e
    return CRS.from_epsg(4326), "EPSG:4326 (RFC 7946 default)"


def load_footprints(cfg: Config, work_crs: CRS, log) -> dict:
    """
    Read footprints and assign stable object IDs.
    Return records=[(object_id, geom_work, src_props)], id_source, crs, and count.
    """
    path = cfg.input_geojson
    if not path or not os.path.isfile(path):
        raise AtapInputError(f"Footprint file was not found: {path!r}")

    ext = os.path.splitext(path)[1].lower()
    raw: list[tuple[Any, Any, dict]] = []   # (unused, geometry, properties)

    if ext in (".geojson", ".json"):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("type") == "Feature":
            feats = [doc]
        elif doc.get("type") == "FeatureCollection":
            feats = doc.get("features") or []
        else:
            raise AtapInputError("Footprint input must be a GeoJSON Feature or FeatureCollection.")
        src_crs, src_crs_label = _crs_from_geojson(doc)
        for f in feats:
            g = f.get("geometry")
            geom = shp_shape(g) if g else None
            raw.append((None, geom, dict(f.get("properties") or {})))
    else:
        import geopandas as gpd  # Optional formats use the same properties ID policy.
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise AtapInputError(f"Cannot determine footprint CRS: {path}")
        src_crs, src_crs_label = CRS.from_user_input(gdf.crs), gdf.crs.to_string()
        cols = [c for c in gdf.columns if c != "geometry"]
        for row in gdf.itertuples(index=False):
            props = {c: getattr(row, c) for c in cols}
            raw.append((None, row.geometry, props))

    n = len(raw)
    if n == 0:
        raise AtapInputError("Footprint dataset contains no features.")

    # Select one stable ID source for the entire dataset.
    field = cfg.id_field or "id"
    oids = [_normalize_id(p.get(field)) for _, _, p in raw]
    missing = sum(o is None for o in oids)
    if missing:
        raise AtapInputError(
            f"Stable building IDs are unavailable: {missing}/{n} features have no "
            f"valid properties.{field} value. Choose a complete, unique properties "
            "key with --id-field FIELD. Feature-level IDs and row indexes cannot be IDs.")
    id_source = {"mode": "property", "field": field}

    seen: dict[str, int] = {}
    dups = set()
    for o in oids:
        seen[o] = seen.get(o, 0) + 1
        if seen[o] > 1:
            dups.add(o)
    if dups:
        sample = ", ".join(sorted(dups)[:10])
        raise AtapInputError(f"Duplicate object_id values ({len(dups)}): {sample}; part_id values would collide.")

    to_work = Transformer.from_crs(src_crs, work_crs, always_xy=True)
    records, invalid = [], []
    for oid, (_, geom, props) in zip(oids, raw):
        if geom is None or geom.is_empty:
            invalid.append(oid)
            records.append((oid, None, props))
            continue
        g = as_polygonal(polygonal_parts(reproject_geom(geom, to_work)))
        if g is None:
            invalid.append(oid)
        records.append((oid, g, props))
    if invalid:
        log(f"[warn] Skipped {len(invalid)} empty or non-polygon footprints.")

    return {"records": records, "id_source": id_source,
            "crs": src_crs_label, "feature_count": n}
