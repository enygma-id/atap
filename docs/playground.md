# Playground

Install the server extra and run `atap serve`, then open the printed localhost URL. Upload a footprint GeoJSON, DSM GeoTIFF, and mandatory DTM GeoTIFF. Parameter-only reruns reuse accepted input without uploading it again.

Building IDs default to `properties.id`; choose another property when needed. **Copy attributes** starts with every detected property active. The viewer uses six colors for levels 0 through 5; higher levels reuse the sixth color.

Ground elevation changes placement only. Explode, colors, hover, selection, and hierarchy state are never written into canonical output. Downloads embed ATAP provenance, effective configuration, and result statistics.
