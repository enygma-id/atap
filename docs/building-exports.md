# Building exports

Building runs through the CLI and local server produce canonical GeoJSON by
default. Explicit export selections additionally generate GLB 2.0, CityJSON 1.1
and CityGML 2.0 derived LoD1 solids. These are not BIM geometry, reconstructed
LoD2 roofs, or an OGC certification claim.

## Usage

```sh
atap run --input-geojson footprints.geojson --dsm dsm.tif --dtm dtm.tif \
  --working-crs EPSG:32750 --output results/buildings.geojson --export all
atap export results/buildings.geojson --formats glb,cityjson,citygml
```

`--export` accepts `none` (default, GeoJSON only), `all`, or a
comma-separated subset. Exporting a saved result does not read rasters again.
The explicit `atap export FILE` command defaults to `--formats all`; `none`
is a no-op and does not invalidate an existing bundle. The Python engine API
continues to produce canonical results only; calling `export_file` is opt-in.
Outputs share the source stem: `buildings.glb`, `buildings.city.json`,
`buildings.gml`, and `buildings.exports.json` (hashes, sizes, CRS, datum).
Tree runs retain their own outputs; explicitly requesting building exports in
tree mode is an input error. The source needs a `.geojson` or `.json` extension.

Python callers retain the existing engine API and request derivatives explicitly:

```python
from atap import export_file, run_elevation

result = run_elevation("footprints.geojson", "dtm.tif", "dsm.tif", "buildings.geojson")
if not result["cancelled"]:
    manifest = export_file(result["output_path"], "all")
```

## Geometry and identity

Each part becomes a closed prism between `base_elevation_m` and
`top_elevation_m`. Courtyard holes and MultiPolygon components are preserved.
Upper parts start at their recorded base. No ground toggle, explode offset,
or display height scale is used. Scientific GeoJSON bytes are not changed.
The derived mesh removes repeated and exactly collinear boundary vertices with
zero tolerance before triangulation, so caps and walls share the same edges.
This preserves the footprint shape, courtyard holes and elevation intervals.

One Building container is created per `object_id`, with geometry-bearing
BuildingParts for all parts, including P00. `parent_part_id` remains an
attribute; the stack hierarchy is not assumed to equal semantic decomposition.
Containers have no duplicate aggregate geometry. CityGML represents disconnected
components as child BuildingParts with separate solids; CityJSON uses multiple
Solid geometries at the same LoD on the original BuildingPart (its BuildingPart
schema does not permit MultiSolid).
GLB has a container node per building and one mesh node per part with attributes.

Individual closed solids retain shared contact faces between stacked parts.
They are not labelled as exterior roofs or walls. This profile does not produce
a fused exterior envelope, textures, reconstructed roof detail or inferred floors.

## Coordinates

CityJSON/CityGML use the metric `processing.working_crs` and recorded absolute
elevations. Building exports require an EPSG horizontal working CRS. A horizontal
EPSG code does not establish a vertical datum. When the datum is unknown, the
original horizontal EPSG is retained and the sidecar records `vertical_status`
as `unknown`. Z is retained in metres but is not advertised as a fully referenced
vertical CRS. A free-text datum label is retained as `label_only`, not interpreted
as an EPSG code. Full XSD validation and the GDAL reader accept 2D horizontal CRS
with XYZ coordinates; that interoperability result does not establish a datum.

An explicit `vertical_datum="EPSG:..."` must identify a vertical CRS in metres.
It describes the existing raster elevations; export never converts heights or
performs a geoid transformation. A genuine compound CRS is constructed. CityJSON
1.1 requires a registered compound EPSG identifier: for example RD New (28992)
plus NAP height (5709) is EPSG:7415. Other explicit combinations without a
registered compound EPSG identifier are rejected for CityJSON; CityGML/GLB can
still be selected explicitly. CityGML uses the registered compound CRS or the
OGC compound URN. No vertical identifier is invented for unknown references.

CityJSON uses millimetre quantization with scale/translate. Encoding precision
does not imply source accuracy. An edge collapsed by quantization is an error.
CityGML uses XML escaping for names and source attributes.

CityJSON contains only standard root members. Ordinary ATAP/source attributes
remain typed in BuildingPart `attributes` (including booleans, nulls and nested
JSON); they do not need an extension. Provenance, vertical-reference state and
source hashes are in `*.exports.json`, not an arbitrary root `atap`. ATAP numeric
suffixes `_m`, `_m2` and `_m3` denote metres, square metres and cubic metres;
`part_level` is an integer hierarchy depth, not a CityJSON LoD.

CityGML 2.0 uses standard Generics, in stable name order: strings stay unquoted
strings, int32 values use `gen:intAttribute`, and finite floats use
`gen:doubleAttribute`. Larger integers remain exact strings with a sidecar
warning. Booleans are strings `true`/`false`, null attributes are omitted, and
arrays/objects are deterministic JSON strings. These documented mappings are
not native nullable/boolean/nested CityGML types. A nonempty string `name` uses
`gml:name` and is not duplicated as a generic attribute. No ADE or speculative
measure-unit URI is introduced. Non-finite numeric values and forbidden XML 1.0
characters are rejected.

GLB uses local coordinates near the dataset centre and the Y-up conversion
`(East, North, Up) -> (East, Up, -North)`. Root `extras` contain `working_crs`,
`origin_projected_m` and `vertical_reference`. Reconstruct projected coordinates
from a GLB vertex `(x,y,z)` using:

```text
E = origin[0] + x
N = origin[1] - z
H = origin[2] + y
```

These are ATAP metadata conventions, not a universal geospatial glTF extension.
A GIS consumer must read this metadata to place a local GLB geographically.

## Server and playground

`POST /api/jobs` accepts a separate multipart `export_formats` field: `all`,
`none`, or a comma-separated subset of `glb,cityjson,citygml`. Omission generates
canonical GeoJSON only. It is separate from scientific `params`, also during
`source_job_id` reuse. Completed results include `exports` with names, sizes
and SHA-256 hashes. Artifact kinds are `glb`, `cityjson`, `citygml`, and `exports`
(manifest). Downloads retain UTC timestamp and short job ID names.

The playground uses compact, independent format buttons like Copy attributes.
GeoJSON stays active because it is always generated; GLB, CityJSON and CityGML
start inactive and can be combined freely. Reset restores GeoJSON only. Building
export controls are hidden in tree mode. The playground sends the selection
explicitly, matching the CLI/server canonical-only default. Artifact links show only completed exports. The viewer
continues to render canonical GeoJSON.

## Failure and resource use

Export failure fails the CLI/job explicitly while leaving the canonical result
on disk. Cancellation returns CLI status 130. Writers stage files beside the
source; the manifest is published last after all requested writers succeed.
Each staged artifact is read back for finite coordinates, closed oriented
shells, XYZ bounds and signed volume. The source hash and final published
artifact bytes are checked before the manifest is written. A new nonempty
export attempt invalidates the old manifest; a failure can leave old derivative
files but never a newly successful bundle marker. Changes to the source during
an export are rejected.
Individual replacements are atomic; the bundle is not a multi-file transaction.
Consumers should check source/artifact hashes before using a bundle. Old export
files may remain after a later attempt: the manifest, not file existence, records
the selected formats and source used.

The manifest retains existing artifact names/sizes/hashes and adds target
versions, `canonical_profile`, coordinate-reference details and explicit
warnings. Runtime checks are marked as internal. `external=not_run_at_runtime`
means schema/independent solid validators were not invoked during that job;
the manifest does not assert external conformance. The separate CI reports
identify the exact artifact hashes that passed those independent gates.

Export currently retains derived geometry in memory. Split very large datasets
into jobs. Checks cover closed oriented edges, cap area, courtyard retention,
concavity, component identity, elevation placement, coordinate reconstruction,
redundant boundary vertices, XML escaping, determinism and staged failures.
Shell validation failures identify the affected `part_id`. Format/schema checks
complement these geometry checks; appearance alone is not proof of validity.

Binary glTF packing follows Enygma ARCA, adapted for ATAP solid geometry and
identities. See `THIRD_PARTY_NOTICES.md` for provenance and triangulator licensing.

## Reproduce independent validation

The required `export-conformance` CI job uses Ubuntu 24.04/Python 3.12, cjval
0.10.0, val3dity 2.7.0, the complete official CityGML 2.0/GML 3.1.1 schema graph,
GDAL through pyogrio 0.11.1, cjio 0.9.0, trimesh 4.11.0 and Khronos glTF Validator
2.0.0-dev.3.10. Immutable validator revisions and all 55 schema-file hashes are
in `tools/export-validation-lock.json`; XML validation is offline and fails if
any dependency is absent or has a different hash. QA-only Python packages are
pinned in `tools/requirements-export-validation.txt`, outside engine dependencies.

After installing those validators as shown in the CI job:

```sh
python tools/prepare_export_validation.py --cache .cache/schemas
python tools/make_export_fixtures.py --out .cache/fixtures
python tools/validate_exports.py --fixtures .cache/fixtures --out .cache/conformance \
  --schema-cache .cache/schemas --cjval /path/to/cjval --val3dity /path/to/val3dity \
  --gltf-module /path/to/node_modules/gltf-validator
ATAP_CONFORMANCE=1 ATAP_EXPORT_FIXTURES=.cache/fixtures ATAP_SCHEMA_CACHE=.cache/schemas \
  CJVAL=/path/to/cjval VAL3DITY=/path/to/val3dity \
  python -m pytest tests/test_external_export_validation.py -q
```

The fixture generator uses normal ATAP raster processing, then the actual
writers. Validation checks ordinary/concave/courtyard/multipart/contacting
solids, attributes, unknown/known vertical references and invalid inputs.
Writer hashes are repeated in the same environment, never assumed identical
across operating systems. Volume/XYZ bounds are compared to canonical geometry
using bounds derived from serialization precision and source rounding.

CityGML geometry is independently read by GDAL from unchanged `gml:Solid`
subtrees in a temporary feature wrapper, avoiding GDAL's Building flattening.
Ring order and coordinates must be preserved exactly. `GML_REPORT_COMPD_CS=YES`
retains declared compound CRS metadata; unknown references still have two CRS
axes and three geometry ordinates. The read solids are independently checked
for watertightness/winding/volume and converted at the GML writer's 1e-9 metre
serialization precision into a validation interchange for val3dity. No claim is
made that val3dity directly accepts CityGML. Touching stacked parts must pass;
deliberate interior overlap must fail with error 601, without disabling overlap
checks. A schema-only pass is insufficient (for example xs:double permits NaN,
and CityGML permits missing geometry; the export profile rejects both).

Every command stores stdout, stderr and its actual exit code; reports include
tool versions and hashes. val3dity can exit zero for invalid input, so its JSON
validity/errors and report existence are mandatory gates. CI retains reports
even on failure. Missing validators, missing reports and incomplete catalogs fail
hard. Local runtime validation and independent CI validation are distinct.
