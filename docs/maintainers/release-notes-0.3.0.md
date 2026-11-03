<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# ATAP v0.3.0 — Building interoperability exports

**Status:** release preparation; publication date and release approval pending.
No DOI is assigned by this document. Keep the historical 0.2.0 release notes.

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

## Validation evidence required for publication

Before publishing these notes as a final release, inspect the exact candidate
SHA's `export-conformance-<SHA>` and `release-metadata-<SHA>` CI artifacts.
Required checks include cjval 0.10.0 for CityJSON 1.1, the complete official
CityGML 2.0/GML 3.1.1 XSD graph, independent GDAL/cjio/trimesh read-back and
solid/volume/bounds checks, val3dity 2.7.0, and Khronos glTF validation.
CityGML solids are read independently into a supported validation interchange;
val3dity is not claimed to accept GML directly.

Evidence must include positive courtyard/concave/multipart/contacting-mass
fixtures, negative corruption/overlap/missing-tool tests, canonical source hash
preservation, same-environment repeatability, four goldens, worker determinism,
browser online/offline, Windows/Linux regressions, and a fresh wheel install.
Formal CFF validation and both sample integrity manifests are additional gates.
These checks are not OGC certification or independent scientific peer review.

## Licensing and publication

ATAP source is **AGPL-3.0-only**. Included samples and tree models have separate
**CC BY 4.0** notices where applicable; software licensing does not automatically
license generated datasets. mapbox-earcut remains ISC; isolated cffconvert
metadata validation is Apache-2.0. Their notices/provenance are recorded separately.

Human review of rights, privacy, source contracts and redistribution is required
for every sample. Version/date coherence, exact-commit CI evidence and an
enabled organization-approved Zenodo integration must precede publication.
Publishing a GitHub release, a Zenodo record/DOI and a PyPI package are separate
authorized actions. See the [release checklist](release-checklist.md).
