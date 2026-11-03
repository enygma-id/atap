<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# ATAP v0.3.0: Building interoperability exports

**Release date:** 2026-11-03.

Previous versions remain documented in the project changelog and their
respective release notes.

## Building exports

Canonical GeoJSON profile **0.6** remains the source of truth. Building runs
produce canonical GeoJSON by default. Opt-in downstream formats are:

- **GLB 2.0**, local projected origin, Y-up part meshes and georeferencing extras;
- **CityJSON 1.1**, typed BuildingPart attributes and LoD1 Solid geometries;
- **CityGML 2.0**, LoD1 solids and deterministically typed Generics.

Select formats with `atap run ... --export glb,cityjson,citygml`, request
`export_formats` in the HTTP API, or enable playground format buttons before
Run. `atap export result.geojson --formats all` converts saved results without
rerunning rasters. Python users call `atap.export_file` explicitly.

Courtyards, concave outlines, disconnected components, part identity, height
intervals and original hierarchy attributes are retained. Sidecar provenance
records source/artifact hashes, coordinate reference and validation scope.
Serialized results are read back and checked before publishing the manifest;
stale success markers are invalidated on failed nonempty export attempts.

## Compatibility and limits

- CLI/API default selection changes from implicit derivatives to canonical
  GeoJSON only. Clients needing derivatives must select them explicitly.
- CityJSON has no unregistered root `atap`; ordinary typed attributes remain
  on CityObjects and export provenance remains in the sidecar.
- CityGML uses int32/finite doubles where appropriate; larger integers, booleans
  and nested JSON use documented string mappings, and null attributes are omitted.
- Unknown vertical datum stays explicitly unknown with horizontal CRS + Z.
  Supported explicit vertical references are declared without converting heights;
  CityJSON requires a registered compound CRS for an explicit vertical CRS.
- Solids are derived LoD1 extrusions, without automatic roof reconstruction,
  formal LoD2 conformance, BIM equivalence or OGC product certification.
- Canonical geometry, heights, hierarchy, numerical algorithms, scientific
  defaults and tree workflow remain unchanged. Tree mode keeps its canopy,
  points and summary outputs and rejects building derivative selections.
- New provenance reports engine version 0.3.0. Cross-version regression
  normalization is explicit and limited to that member; old goldens/hashes remain.

See [Building exports](../building-exports.md) for units, reference support,
attribute policies, atomicity limits and reproduction commands.

## Validation and conformance scope

The v0.3.0 engineering validation workflow includes independently checked
CityJSON 1.1, CityGML 2.0 and GLB 2.0 exports. It uses pinned validators and
schema checks, plus geometry/solid read-back, volume and bounds comparisons,
negative fixtures, source-hash preservation and regression tests.

The validation tooling includes cjval 0.10.0 for CityJSON 1.1, the official
CityGML 2.0/GML 3.1.1 XSD graph, GDAL/cjio/trimesh and val3dity 2.7.0
for independent geometry checks, and Khronos glTF validation. CityGML solids
are converted to a supported validation interchange for val3dity; the
project does not claim direct GML input support by val3dity.

The repository CI also covers installed-wheel checks, historical golden output
regressions, sample manifest verification, Python and browser environments,
and formal CFF validation. These checks do **not** constitute formal OGC
product certification or independent scientific peer review.

## Licensing and publication

ATAP source is **AGPL-3.0-only**. Included samples and tree models have separate
**CC BY 4.0** notices where applicable; software licensing does not automatically
license generated datasets. mapbox-earcut remains ISC; isolated cffconvert
metadata validation is Apache-2.0. Their notices/provenance are recorded separately.

Sample data rights, privacy, provenance and applicable redistribution terms
remain governed by their respective documented licenses and project review.

Software citation metadata is in [`CITATION.cff`](../../CITATION.cff).
GitHub Release, Zenodo DOI archiving and PyPI publication are distinct actions.
No DOI is asserted here unless the corresponding Zenodo record exists.
See the [release checklist](release-checklist.md) for future releases.
