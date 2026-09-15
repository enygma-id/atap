# Local HTTP API

The playground and API are served by `atap serve` on localhost by default.
The API does not accept client filesystem paths.

## Submit a job

`POST /api/jobs` accepts multipart form fields:

| Field | Description |
|---|---|
| `footprint`, `dsm`, `dtm` | All three files for a new input set: GeoJSON and two GeoTIFFs. |
| `source_job_id` | An existing job UUID to reuse its uploaded input instead of sending files. |
| `params` | JSON object of supported run options; defaults to `{}`. |

Send all three files **or** `source_job_id`. Mixing sources or omitting a file
returns 422. An unknown, expired, or unavailable source returns 404. Uploads
over the configured limit return 413. Unknown or invalid parameters return 422.

When `params.keep_properties` is omitted or null, the engine copies every
property key found in the footprint dataset. An explicit JSON array copies only
those keys; an empty array copies none. The resolved deterministic list is
written to `processing.parameters.keep_properties`.

A successful submission returns 200 with `job_id`, `footprint_count`, and
`queue_position` (zero if not waiting). A reused job can itself be a source:
all descendants read the original input files directly, without raster copies.
The source can be queued, running, completed, failed, or cancelled.

Each new job has independent parameters, output, log, and cancellation state.
Shared input is protected while a consuming job is active. Reuse refreshes
its retention on submission and completion; default retention is 24 hours.
References are in-memory and are unavailable after server restart.

## Monitor and cancel

- `GET /api/health`: version, source URL, job counts, and resource limits.
- `GET /api/jobs/{id}`: status, queue position, result counts, or error.
- `GET /api/jobs/{id}/events`: SSE with backlog replay; types include queued,
  started, progress, log, cancelling, completed, cancelled, failed, and close.
- `POST /api/jobs/{id}/cancel`: cancel this job without affecting its input source
  or other consumers. Cancelled runs write no output.

## Download artifacts

`GET /api/jobs/{id}/artifacts/output` returns GeoJSON with a download name such as
`atap_20260915T143052Z_a1b2c3d4.geojson`. Timestamp is the job submission time
in UTC and the suffix is the first eight UUID characters. Each job's download
name remains stable across requests.

`GET /api/jobs/{id}/artifacts/log` returns `run.log`. Unknown or expired artifacts
return 404. The server stores fixed `output.geojson` and `run.log` filenames
inside its UUID job directories; clients cannot choose server paths.
