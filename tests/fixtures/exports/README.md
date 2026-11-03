<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Export conformance fixtures

`cityjson-1.1.3.schema.json` is the unchanged CC0-1.0 root schema from
https://raw.githubusercontent.com/cityjson/specs/1.1.3/schemas/cityjson.schema.json.
Its SHA-256 and the full dependency graph are recorded in
`tools/export-validation-lock.json`. It defines the allowed root members used
by the fast regression suite; no permissive handwritten list is substituted.

`tools/make_export_fixtures.py` creates synthetic raster/footprint inputs and
uses the normal ATAP API and actual derivative writers. Generated geospatial
files and reports belong in `.cache/`, not this directory. Fixtures include
simple, stepped/contacting, courtyard, concave, multipart, typed Unicode
attributes, unknown/explicit vertical reference and negative CRS/quantization.
