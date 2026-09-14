# prototype/

Reference playground retained during the packaged engine transition. The
engine is now implemented under `src/atap/`, and development tools live in
the top-level `tools/` directory.

Scientific changes are made in the package, with before/after evidence as
required by `CONTRIBUTING.md`. The playground remains here until its Phase 3
replacement is complete.

| Path | What it is |
|---|---|
| `playground/index.html` | Single-file deck.gl viewer + job runner (API v1). Expects `vendor/deck.gl-9.3.11.min.js`; falls back to the same version on unpkg |

## Quick start

```bash
pip install -e ".[dev]"
python tools/make_synthetic.py --out .cache/syn
atap run --input-geojson .cache/syn/stepped/footprints_fid.geojson \
  --dsm .cache/syn/stepped/dsm.tif --dtm .cache/syn/stepped/dtm.tif \
  --output .cache/out.geojson
```
