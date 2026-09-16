# SPDX-License-Identifier: AGPL-3.0-only
"""
Produce baseline (golden) outputs from an engine implementation.

    python tools/run_baselines.py --data DIR --out OUTDIR [--engine atap]

Run it against the installed package and compare results with
compare_outputs.py.
Cases are fixed so results are comparable across implementations.
"""
import argparse
import importlib
import importlib.util
import json
import os
import sys
import time

CASES = [
    # name, dataset, footprint file, params
    ("stepped_default", "stepped", "footprints.geojson", {"id_field": "id"}),
    ("stepped_k8_regularize", "stepped", "footprints_fid.geojson", {"max_height_classes": 8, "regularize": True}),
    ("courtyard_default", "courtyard", "footprints_fid.geojson", {}),
    ("bench_default", "bench", "footprints_fid.geojson", {}),
]


def load_engine(path):
    if path == "atap":
        return importlib.import_module("atap")
    spec = importlib.util.spec_from_file_location("atap_engine_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # required by @dataclass during exec
    spec.loader.exec_module(mod)
    return mod


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="directory produced by make_synthetic.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", default="atap",
                    help="'atap' for the installed package, or an engine source file")
    ap.add_argument("--only", nargs="*", help="subset of case names")
    a = ap.parse_args()
    E = load_engine(a.engine)
    os.makedirs(a.out, exist_ok=True)
    summary = {}
    for name, ds, fp, params in CASES:
        if a.only and name not in a.only:
            continue
        d = os.path.join(a.data, ds)
        out = os.path.join(a.out, f"{name}.geojson")
        t = time.time()
        r = E.run_elevation(os.path.join(d, fp), os.path.join(d, "dtm.tif"), os.path.join(d, "dsm.tif"), out,
                            workers=1, log_cb=lambda m: None, **params)
        s = json.load(open(out))["summary"]
        summary[name] = {"parts": r["num_features"], "buildings": r["num_buildings"], "skipped": r["num_skipped"],
                         "decomposed": s["decomposed_building_count"], "max_part_level": s["max_part_level"],
                         "total_volume_m3": s["total_volume_m3"], "seconds_workers_1": round(time.time() - t, 2)}
        print(name, summary[name])
    json.dump(summary, open(os.path.join(a.out, "summary.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
