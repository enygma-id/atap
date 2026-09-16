# Output metadata

Every successful ATAP run embeds metadata directly in the output GeoJSON
FeatureCollection. It is available through the Python API, CLI, and server
output download, without a sidecar file.

| Member | Contents |
|---|---|
| `atap` | Engine/profile versions, ATAP name and attribution, source URL, and generator software license. |
| `inputs` | Input basenames, footprint count and ID source, raster CRS and resolution. |
| `processing.parameters` | Resolved non-path run configuration, including source-property selection, ID override, terrain settings, and raster-driver restriction. |
| `processing` | Working/output CRS, analysis grid, resampling and algorithm information. |
| `processing.execution` | Requested and actual worker settings, cache, batching, and processing/output order. |
| `vertical_reference` | Terrain-normalized height semantics and ground reference. |
| `process` | Start/finish times, duration, and software versions. |
| `summary` | Building/part/decomposition/skipped counts, maximum level and height, total volume, skipped reasons, and validation status. |

When `keep_properties` is omitted or null, all footprint property keys are
selected. An explicit list selects a subset; `[]` selects none. The output
records the effective list, so source-property retention can be audited.

Absolute filesystem paths are omitted. The `software_license` field identifies
the ATAP generator license; it does not assign a license to input or output data.
Viewer colors, explode offsets, and selection state are never written to output.
