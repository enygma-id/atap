# prototype/

Working prototype of the ATAP elevation engine 0.2.0 (output profile 0.6)
and its reference playground. It is the **reference behaviour** until the
engine is packaged under `src/atap/`; after that the tools move to `tools/`
and this directory is removed.

Do not improve the algorithm here. Scientific changes are made in the
package, with before/after evidence as required by `CONTRIBUTING.md`.

| Path | What it is |
|---|---|
| `elevation.py` | Engine + CLI in one file. `run_elevation()` is the library entry point |
| `playground/index.html` | Single-file deck.gl viewer + job runner (API v1). Expects `vendor/deck.gl-9.3.11.min.js`; falls back to the same version on unpkg |
| `tools/make_synthetic.py` | Builds the `stepped`, `courtyard` and `bench` synthetic datasets |
| `tools/run_baselines.py` | Runs the four fixed baseline cases against any engine file |
| `tools/compare_outputs.py` | Scientific equivalence check (ignores `process`, `processing.execution`) |
| `tools/hole_sensitivity.py` | Hole/courtyard parameter table (see `docs/decisions.md`, ADR-006) |
| `tools/mock_server.py` | Test double implementing API v1 with this engine (workers forced to 1) |
| `tools/e2e_playground.py` | Playwright end-to-end suite for the playground (mock server or `--url`) |

## Verification status

Checked on Linux, Python 3.12, NumPy 1.26, rasterio 1.4 and shapely 2.1,
with synthetic data only:

- the baseline cases reproduce;
- `e2e_playground.py` passes all scenarios against the mock server.

Not verified yet: Windows, NumPy 2.x, multi-core speed-up, the live BIG
basemap.

## Quick start

```bash
pip install numpy scipy rasterio shapely pyproj
python tools/make_synthetic.py --out ../.cache/syn
python elevation.py --input-geojson ../.cache/syn/stepped/footprints_fid.geojson \
  --dsm ../.cache/syn/stepped/dsm.tif --dtm ../.cache/syn/stepped/dtm.tif --output ../.cache/out.geojson
python tools/mock_server.py 8765     # then open http://127.0.0.1:8765/
```
