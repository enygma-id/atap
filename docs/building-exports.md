# Building exports

Building runs through the CLI and local server now generate GLB, CityJSON 1.1
and CityGML 2.0 alongside the canonical GeoJSON. These are derived LoD1 solids,
not BIM geometry or a claim of LoD2 roof reconstruction.

## Usage

```sh
atap run --input-geojson footprints.geojson --dsm dsm.tif --dtm dtm.tif \
  --working-crs EPSG:32750 --output results/buildings.geojson --export all
atap export results/buildings.geojson --formats glb,cityjson,citygml
```

`--export` accepts `all` (building default), `none` (GeoJSON only), or a
comma-separated subset. Exporting a saved result does not read rasters again.
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
elevations. A horizontal EPSG code does not establish a vertical datum. Unknown
vertical reference remains unknown and is carried in metadata.

CityJSON uses millimetre quantization with scale/translate. Encoding precision
does not imply source accuracy. An edge collapsed by quantization is an error.
CityGML uses XML escaping for names and source attributes.

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
all building formats. It is separate from scientific `params`, also during
`source_job_id` reuse. Completed results include `exports` with names, sizes
and SHA-256 hashes. Artifact kinds are `glb`, `cityjson`, `citygml`, and `exports`
(manifest). Downloads retain UTC timestamp and short job ID names.

The playground uses compact, independent format buttons like Copy attributes.
GeoJSON stays active because it is always generated; GLB, CityJSON and CityGML
start inactive and can be combined freely. Reset restores GeoJSON only. Building
export controls are hidden in tree mode. The playground sends the selection
explicitly, while CLI/server requests without a selection still default to all
building formats. Artifact links show only completed exports. The viewer
continues to render canonical GeoJSON.

## Failure and resource use

Export failure fails the CLI/job explicitly while leaving the canonical result
on disk. Cancellation returns CLI status 130. Writers stage files beside the
source; the manifest is published last after all requested writers succeed.
Individual replacements are atomic; the bundle is not a multi-file transaction.
Consumers should check source/artifact hashes before using a bundle. Old export
files may remain after a later attempt: the manifest, not file existence, records
the selected formats and source used.

Export currently retains derived geometry in memory. Split very large datasets
into jobs. Checks cover closed oriented edges, cap area, courtyard retention,
concavity, component identity, elevation placement, coordinate reconstruction,
redundant boundary vertices, XML escaping, determinism and staged failures.
Shell validation failures identify the affected `part_id`. Format/schema checks
complement these geometry checks; appearance alone is not proof of validity.

Binary glTF packing follows Enygma ARCA, adapted for ATAP solid geometry and
identities. See `THIRD_PARTY_NOTICES.md` for provenance and triangulator licensing.
