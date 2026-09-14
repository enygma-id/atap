# SPDX-License-Identifier: AGPL-3.0-only
"""Canonical output invariant validation."""

from .config import AtapValidationError, Config


# =============================================================================
#                          VALIDATION  (spec §30-31)
# =============================================================================
def _tol(cfg: Config) -> float:
    return max(10.0 ** (-cfg.round_digits), 1e-6) * 1.0001


def validate_ids(recs, problems):
    seen = set()
    for r in recs:
        p = r["properties"]
        if not p.get("object_id"):
            problems.append(f"{r['id']}: object_id is empty")
        if p["part_id"] in seen:
            problems.append(f"duplicate part_id: {p['part_id']}")
        seen.add(p["part_id"])
        if r["id"] != p["part_id"]:
            problems.append(f"{p['part_id']}: Feature.id != part_id")


def validate_hierarchy(recs, by_id, problems, tol):
    roots_per_obj: dict[str, int] = {}
    for r in recs:
        p = r["properties"]
        if p["parent_part_id"] is None:
            roots_per_obj[p["object_id"]] = roots_per_obj.get(p["object_id"], 0) + 1
            if p["part_level"] != 0:
                problems.append(f"{p['part_id']}: root has part_level {p['part_level']}")
            continue
        par = by_id.get(p["parent_part_id"])
        if par is None:
            problems.append(f"{p['part_id']}: parent {p['parent_part_id']} does not exist (orphan)")
            continue
        pp = par["properties"]
        if pp["object_id"] != p["object_id"]:
            problems.append(f"{p['part_id']}: parent has a different object_id")
        if p["part_level"] != pp["part_level"] + 1:
            problems.append(f"{p['part_id']}: part_level != parent.part_level + 1")
        if abs(p["base_height_agl_m"] - pp["top_height_agl_m"]) > tol:
            problems.append(f"{p['part_id']}: base_height_agl_m != parent.top_height_agl_m")
    for oid, n in roots_per_obj.items():
        if n != 1:
            problems.append(f"object_id {oid}: root count = {n}")


def validate_vertical(recs, problems, tol):
    for r in recs:
        p = r["properties"]
        pid = p["part_id"]
        if abs((p["top_height_agl_m"] - p["base_height_agl_m"]) - p["part_height_m"]) > tol:
            problems.append(f"{pid}: top-base != part_height_m")
        if abs(p["ground_elevation_m"] + p["base_height_agl_m"] - p["base_elevation_m"]) > tol:
            problems.append(f"{pid}: ground+base_agl != base_elevation_m")
        if abs(p["ground_elevation_m"] + p["top_height_agl_m"] - p["top_elevation_m"]) > tol:
            problems.append(f"{pid}: ground+top_agl != top_elevation_m")
        if p["part_height_m"] < 0 or (p["parent_part_id"] is not None and p["part_height_m"] <= 0):
            problems.append(f"{pid}: invalid part_height_m ({p['part_height_m']})")
        if not (0.0 <= p["valid_coverage_ratio"] <= 1.0):
            problems.append(f"{pid}: valid_coverage_ratio is outside [0,1]")


def validate_geometry(recs, by_id, root_of, problems):
    for r in recs:
        g = r["geom_work"]
        pid = r["id"]
        if g is None or g.is_empty or not g.is_valid or g.area <= 0:
            problems.append(f"{pid}: geometry is invalid, empty, or has zero area")
            continue
        par_id = r["properties"]["parent_part_id"]
        if par_id is None:
            continue
        for label, ref in (("parent", by_id[par_id]["geom_work"]),
                           ("root footprint", by_id[root_of[r["properties"]["object_id"]]]["geom_work"])):
            outside = g.difference(ref).area
            if outside > max(1e-6 * g.area, 1e-4):
                problems.append(f"{pid}: lies outside {label} by {outside:.4f} m²")


def validate_volume(recs, problems, tol):
    for r in recs:
        p = r["properties"]
        expect = p["area_m2"] * p["part_height_m"]
        vt = max(0.1, tol * max(p["volume_m3"], 1.0))
        if abs(p["volume_m3"] - expect) > vt:
            problems.append(f"{p['part_id']}: volume_m3 != area_m2 * part_height_m")


def validate_all(recs, cfg: Config):
    tol = _tol(cfg)
    by_id = {r["id"]: r for r in recs}
    root_of = {r["properties"]["object_id"]: r["id"] for r in recs
               if r["properties"]["parent_part_id"] is None}
    problems: list[str] = []
    validate_ids(recs, problems)
    validate_hierarchy(recs, by_id, problems, tol)
    validate_vertical(recs, problems, tol)
    if not any("orphan" in s for s in problems):
        validate_geometry(recs, by_id, root_of, problems)
    validate_volume(recs, problems, tol)
    if problems:
        raise AtapValidationError(problems)
