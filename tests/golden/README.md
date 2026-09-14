# Elevation prototype golden outputs

Frozen on 2026-09-12 from prototype commit `c76fa3c` (engine 0.2.0,
profile 0.6), using synthetic inputs and `workers=1`. No scientific output,
geometry, hierarchy, CRS behavior, schema, or defaults were changed.

The three small cases are complete, unmodified output files. The benchmark
stores its output summary and the SHA-256 of its **entire canonical
FeatureCollection**, including every feature, rather than a summary-only
hash. `summary.json` records all four cases and the original wall timings.
The single-worker benchmark took 5.01 seconds on this machine; it is a
machine-specific reference, not a cross-machine performance target.

## Environment

| Component | Version |
|---|---|
| OS | Windows-11-10.0.26200-SP0 |
| Python | 3.13.2 |
| NumPy | 2.5.3 |
| SciPy | 1.18.1 |
| Rasterio | 1.5.1 |
| GDAL | 3.12.4 |
| Shapely | 2.1.2 |
| GEOS | 3.13.1 |
| pyproj | 3.8.0 |
| PROJ | 9.8.1 |

## Reproduce

From the repository root, create a virtual environment using standalone
Python 3.13 (the recorded run used 3.13.2), activate it, then run:

```sh
python -m pip install numpy==2.5.3 scipy==1.18.1 rasterio==1.5.1 shapely==2.1.2 pyproj==3.8.0
python tools/make_synthetic.py --out .cache/syn
python tools/run_baselines.py --data .cache/syn --out .cache/baseline
python tests/golden/verify.py .cache/baseline
```

Raster inputs and the full benchmark output stay local and are not committed.
The verifier invokes `tools/compare_outputs.py` for the three
complete goldens, checks the benchmark summary and full-output hash, and
compares the four run summaries excluding `seconds_workers_1` only.

Canonicalization removes only top-level `process` and
`processing.execution`. It serializes the remaining object with Python
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False,
allow_nan=False)` and hashes the UTF-8 bytes without a trailing newline.
Array order and all other values remain significant. The filename in the
`.sha256` file denotes this virtual canonical byte stream.

Timings and process metadata vary by run. Do not regenerate goldens just to
accept a discrepancy: investigate it and document intentional output changes.

## Profile 0.6 English metadata migration

Phase 1 translated only `processing.orientation_convention` to English. The
three complete goldens and benchmark canonical hash were updated after all
four pre-migration comparisons were EQUIVALENT when that one value was
excluded. Geometry, hierarchy, measurements, schema, parameters, and defaults
did not change.
