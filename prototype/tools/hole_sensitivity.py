# SPDX-License-Identifier: AGPL-3.0-only
"""
Hole / courtyard parameter sensitivity on the `courtyard` synthetic dataset.

    python hole_sensitivity.py --data DIR/courtyard [--engine ../elevation.py]

Prints, per parameter variant, which holes (A..F) survive in the level-1
part and the net area/volume. Reference numbers (prototype, DSM 0.1 m) are
in docs/decisions.md (ADR-006).
"""
import argparse
import importlib.util
import sys
import json
import os
import tempfile

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, shape

X0, Y0 = 770000.0, 9432000.0
HOLES = {"A": (32, 32), "B": (56.5, 26.5), "C": (65.75, 25.75), "D": (75.2, 25.2), "E": (55.2, 55), "F": (65.4, 55)}
VARIANTS = [
    ("default", {}),
    ("max_fill_hole_area_m2=0", {"max_fill_hole_area_m2": 0.0}),
    ("max_fill_hole_area_m2=10", {"max_fill_hole_area_m2": 10.0}),
    ("max_fill_hole_area_m2=500 (~legacy)", {"max_fill_hole_area_m2": 500.0}),
    ("morph_closing_iters=0", {"morph_closing_iters": 0}),
    ("morph_closing_iters=6", {"morph_closing_iters": 6}),
    ("simplify_tolerance_m=0.2", {"simplify_tolerance_m": 0.2}),
    ("closing=0 fill=0 simplify=0.2 (raw)", {"morph_closing_iters": 0, "max_fill_hole_area_m2": 0.0, "simplify_tolerance_m": 0.2}),
    ("regularize=True", {"regularize": True}),
]


def load_engine(path):
    spec = importlib.util.spec_from_file_location("atap_engine_proto", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # required by @dataclass during exec
    spec.loader.exec_module(mod)
    return mod


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--engine", default=os.path.join(here, "..", "elevation.py"))
    a = ap.parse_args()
    E = load_engine(a.engine)
    tr = Transformer.from_crs(4326, 32750, always_xy=True)
    out = os.path.join(tempfile.mkdtemp(), "o.geojson")
    for label, kw in VARIANTS:
        E.run_elevation(os.path.join(a.data, "footprints_fid.geojson"), os.path.join(a.data, "dtm.tif"),
                        os.path.join(a.data, "dsm.tif"), out, workers=1, log_cb=lambda m: None, **kw)
        f = [x for x in json.load(open(out))["features"] if x["properties"]["part_level"] == 1][0]
        g = shapely.transform(shape(f["geometry"]), lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
        found = {}
        for ring in g.interiors:
            p = Polygon(ring)
            x, y = p.centroid.x - X0, Y0 - p.centroid.y
            k = min(HOLES, key=lambda h: (HOLES[h][0] - x) ** 2 + (HOLES[h][1] - y) ** 2)
            found[k] = round(p.area, 1)
        cells = "  ".join(f"{k}:{found.get(k, '-'):>6}" for k in HOLES)
        print(f"{label:<38} {cells}  area={f['properties']['area_m2']}  vol={f['properties']['volume_m3']}")


if __name__ == "__main__":
    main()
