# ATAP

**ATAP: ATAP Terrain-Aware Architectural Polygonization**

ATAP is an open-source, GIS-native research and engineering framework for
terrain-aware architectural polygonization and hierarchical building-mass
representation.

**Founded and stewarded by Enygma.**  
Legal entity: **PT Enygma Solusi Negeri**

## Overview

ATAP explores whether useful three-dimensional building-mass information can
remain canonical as ordinary GIS geometry plus hierarchy and vertical
semantics, instead of requiring an explicit mesh or BIM object as the primary
representation.

Current research direction:

```text
Authoritative building footprint
+
DSM
+
DTM
↓
Terrain normalization
nDSM = DSM - DTM
↓
Hierarchical building-mass decomposition
↓
GIS-native polygon geometry
+
vertical semantics
+
parent/child relationships
```

The current stable research profile is focused on hierarchical LoD1.x /
LoD1.3-style building-mass representation.

ATAP does not currently claim formal LoD2 conformance, complete roof
reconstruction, BIM equivalence, or stable LAS/LAZ support.

## Why ATAP Exists

ATAP grew from practical digital-twin and geospatial project work where a
3D-object-first representation was often more complex than the actual
operational need.

The project follows a fit-for-purpose principle:

> Use the least complex canonical representation that preserves the information
> required by the intended analysis and downstream use.

ATAP therefore separates:

```text
canonical GIS representation
```

from:

```text
downstream rendering, tiling, streaming, and GPU optimization
```

Read the full rationale in
[`docs/rationale.md`](./docs/rationale.md).

## GIS-Native by Design

ATAP treats GIS-native representation as a first-class architectural principle.

A canonical ATAP building part may remain a Polygon or MultiPolygon while
carrying useful 3D meaning through attributes such as:

```text
object_id
part_id
parent_part_id
part_level
ground_elevation_m
base_height_agl_m
top_height_agl_m
part_height_m
area_m2
volume_m3
```

A downstream renderer may extrude or triangulate those features temporarily
without changing the canonical data model.

ATAP is intended to remain consumable by conventional GIS tooling, spatial
databases, and multiple geospatial rendering engines such as deck.gl,
MapLibre GL, CesiumJS, and other WebGL/WebGPU-based systems.

See [`docs/gis-native-principles.md`](./docs/gis-native-principles.md).

## Editions

### Community Edition

ATAP Community Edition is the canonical public open-source edition.

Covered source code is licensed under:

**GNU Affero General Public License, Version 3 only (`AGPL-3.0-only`)**

The complete license text is in [`LICENSE`](./LICENSE).

### Enterprise Edition

ATAP Enterprise Edition is a separate commercial offering from Enygma for
organizations requiring proprietary integration rights, OEM arrangements,
enterprise support, private extensions, or other separately negotiated terms.

See [`ENTERPRISE.md`](./ENTERPRISE.md).

## Project Identity

| Item | Value |
|---|---|
| Project | ATAP |
| Expanded name | ATAP Terrain-Aware Architectural Polygonization |
| Founding Organization | Enygma |
| Project Steward | Enygma |
| Legal entity | PT Enygma Solusi Negeri |
| Community license | AGPL-3.0-only |

Founding attribution is recorded in
[`FOUNDING_TEAM.md`](./FOUNDING_TEAM.md).

The chronological development history is documented separately in
[`docs/project-history.md`](./docs/project-history.md).

## Research Software

ATAP is being developed as research software, not merely as a utility script.

The repository is intended to maintain:

- public development history;
- reproducible reference cases;
- explicit limitations and failure cases;
- tests and validation;
- tagged releases;
- research-oriented documentation;
- dependency and licensing provenance;
- a publication-ready paper history.

Research documentation is under [`docs/research/`](./docs/research/) and the
working JOSS-oriented paper skeleton is under [`paper/`](./paper/).

## AI-Assisted Development

ATAP uses LLM systems as engineering and research-assistance tools.

The project follows this principle:

> **Human-originated, AI-assisted, human-validated.**

The research problem, architectural direction, methodological decisions,
validation, interpretation, and final acceptance remain human responsibilities.

See [`docs/ai-usage.md`](./docs/ai-usage.md).

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

External contributions are subject to the project contribution policy and,
where required, the ATAP Contributor License Agreement in [`CLA.md`](./CLA.md).

## Third-Party Software

Third-party software remains under its own upstream license terms.

See:

- [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)
- [`third-party/`](./third-party/)

## Status

ATAP is under active development.

Public APIs, schemas, algorithms, parameters, and output semantics may evolve
before a stable 1.0 release.
