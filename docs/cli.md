# ATAP command-line interface

Install the core package with `pip install .`. Optional footprint formats use
`pip install ".[formats]"`; server dependencies use `pip install ".[server]"`;
contributors use `pip install -e ".[dev,server]"`.

## Run elevation

```sh
atap run --input-geojson footprints.geojson --dsm dsm.tif --dtm dtm.tif \
  --output buildings.geojson
```

DTM is mandatory, DSM is the analysis grid, and output uses EPSG:4326. Stable
Building IDs automatically come from `properties.id`. Use `--id-field FIELD` to select another properties key (this overrides `id`). Every feature must have a non-empty, unique value in the selected key. Top-level input `Feature.id` is ignored. The playground selects `id` when present and offers other property keys, including manual entry, in **ID attribute**.

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
or cancellation. `atap --version` prints engine and profile versions.

## Serve the local playground

Install the server extra, then start the API and playground on localhost:

```sh
pip install ".[server]"
atap serve
```

Open `http://127.0.0.1:8000/`. Jobs run through isolated `atap run`
subprocesses and wait in a FIFO queue. Uploaded rasters are restricted to
GeoTIFF, and job files expire after 24 hours by default.

Use `--work-dir`, `--max-upload-mb`, `--max-concurrent`,
`--job-ttl-hours`, and `--grace-seconds` to set local resource limits.
Binding `--host` beyond localhost exposes an unauthenticated service and emits
a warning. CORS remains disabled unless `--cors-origin URL` is supplied.
