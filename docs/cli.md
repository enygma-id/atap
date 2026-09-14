# ATAP command-line interface

Install the core package with `pip install .`. Optional footprint formats use
`pip install ".[formats]"`; server dependencies use `pip install ".[server]"`;
contributors use `pip install -e ".[dev]"`.

## Run elevation

```sh
atap run --input-geojson footprints.geojson --dsm dsm.tif --dtm dtm.tif \
  --output buildings.geojson
```

DTM is mandatory, DSM is the analysis grid, and output uses EPSG:4326. Stable
IDs come from every GeoJSON `Feature.id`, or from `--id-field FIELD`.

| Flag | Default |
|---|---|
| `--height-diff-threshold-m` | `3.0` |
| `--min-subregion-area-m2` | `12.0` |
| `--min-building-height-m` | `2.0` |
| `--base-elevation-stat` | `min` |
| `--ground-source-type` | `DTM` |
| `--vertical-datum` | unset |
| `--max-height-classes` | `4` |
| `--min-footprint-change-ratio` | `0.25` |
| `--morph-closing-iters` | `3` pixels |
| `--max-fill-hole-area-m2` | `4.0` |
| `--parent-min-containment-ratio` | `0.5` |
| `--regularize` / `--no-regularize` | disabled |
| `--simplify-tolerance-m` | `0.9` |
| `--rectangular-ratio` | `0.4` |
| `--circularity-threshold` | `0.8` |
| `--keep-properties` | `id,NAMOBJ,REMARK,floor_est` |
| `--working-crs` | `EPSG:32750` |
| `--round-digits` | `2` |

Execution options do not change scientific output. `--workers` defaults to
automatic selection and `--gdal-cache-mb` defaults to 512. `--params-json`
loads run options from an object; explicit flags take precedence.
`--cancel-file PATH` stops when the file appears. Use
`--raster-drivers GTiff` for untrusted raster uploads.

`--events human` writes progress and logs to stderr. `--events jsonl` writes
one object per stdout line with type `progress`, `log`, `result`, or `error`.
`--quiet` suppresses human progress.

## Validate output

```sh
atap validate buildings.geojson
```

Validation checks IDs, hierarchy, vertical equations, coverage, volume,
geometry validity, and metric parent containment. Exit status is 3 when any
problem is found.

Exit statuses are 0 for success, 2 for input or contract errors, 3 for output
validation errors, 4 for unexpected internal errors, and 130 for interruption
or cancellation. `atap --version` prints engine and profile versions. `atap
serve` is reserved for the local server delivered in Phase 2.
