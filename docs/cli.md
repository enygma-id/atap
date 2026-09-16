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
Building IDs automatically come from `properties.id`. Use `--id-field FIELD` to select another properties key (this overrides `id`). Every feature must have a non-empty, unique value in the selected key. Top-level input `Feature.id` is ignored. The playground selects `id` when present and lists footprint property keys in the **ID attribute** dropdown.

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
| `--keep-properties` | all footprint properties |
| `--working-crs` | `EPSG:32750` |
| `--round-digits` | `2` |

Execution options do not change scientific output. `--workers` defaults to
automatic selection of up to four workers on every platform. Explicit values
are capped at eight workers. An automatically selected pool that stops unexpectedly retries once in a single
process. `--gdal-cache-mb` defaults to 512 and is the total across workers.
`--params-json` loads run options from an object; explicit flags take precedence.
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
GeoTIFF. In the playground, select the three files and run once. Subsequent
runs with the same selected files send only parameters and reuse the uploaded
input. Changing any selected file uploads a new input set. Reuse is scoped to
the current browser session; refreshing the page requires selecting and uploading
files again. If retained input expires or the server restarts, the playground
automatically uploads the selected files again.

Each run has separate output, parameters, log, and cancellation files. Input
is retained while a consuming job is queued or running; its default 24-hour
retention is refreshed on reuse and when that job finishes. Output downloads
are named `atap_YYYYMMDDTHHMMSSZ_<8-character-job-id>.geojson` using the UTC
submission time. The server keeps the fixed internal name `output.geojson`
inside each unique job folder. CLI output names remain controlled by `--output`.
See [HTTP API](api.md) for parameter-only submission.

Use `--work-dir`, `--max-upload-mb`, `--max-concurrent`,
`--job-ttl-hours`, and `--grace-seconds` to set local resource limits.
Binding `--host` beyond localhost exposes an unauthenticated service and emits
a warning. CORS remains disabled unless `--cors-origin URL` is supplied.

### Playground parameter controls

**Ground height from DTM** uses a single-choice button group: min (default),
mean, or median. **Terrain raster type** uses DTM (default) or DEM buttons.

**ID attribute** is a dropdown populated from the footprint properties; `id`
is selected automatically when available. CLI `--id-field` remains available
for explicitly naming another source key.

**Copy attributes** shows one toggle button per detected footprint property.
All start active when a footprint is selected. Turn individual buttons off to
exclude those properties, or turn all off to send an empty copy list. Reset
reactivates all detected properties. When `--keep-properties` is omitted, the engine copies every property key found
in the footprint dataset. Pass a comma-separated list to copy only those keys;
pass an empty value to copy none. For a property name containing a comma, use
`--params-json` with a JSON array. Default discovery sorts the keys; explicit lists are deduplicated while
preserving their first order. The effective list is recorded in output metadata. The playground explicitly sends its active list.
Canonical output fields cannot be overwritten by copied source attributes.
