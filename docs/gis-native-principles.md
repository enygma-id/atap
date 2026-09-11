# GIS-Native Design Principles

## Canonical Geometry Remains Spatial

The canonical ATAP representation should remain expressible using ordinary GIS
geometry and attributes wherever possible.

Current direction:

```text
Polygon / MultiPolygon
+
vertical semantics
+
hierarchy
```

## 3D Meaning Without a Canonical Mesh

ATAP separates spatial semantics from render-time surface construction.

A polygon carrying:

```text
base_height_agl_m
top_height_agl_m
part_height_m
```

can carry useful 3D meaning without requiring the persistent source to be a
mesh.

## Terrain and Intrinsic Geometry Are Separate

ATAP distinguishes intrinsic building mass from world placement.

Intrinsic:

```text
base_height_agl_m
top_height_agl_m
part_height_m
```

Placement:

```text
ground_elevation_m
base_elevation_m
top_elevation_m
```

Terrain placement should not cause intrinsic building mass to grow or shrink.

## Hierarchy Is Data

Complex buildings may be represented through relationships such as:

```text
object_id
part_id
parent_part_id
part_level
```

Hierarchy should remain queryable rather than being hidden inside one opaque
render object.

## Renderer Independence

ATAP does not define one mandatory rendering engine.

Potential consumers include deck.gl, MapLibre GL, CesiumJS, desktop GIS,
spatial databases, and other WebGL/WebGPU geospatial systems.

## Analysis Matters as Much as Visualization

A useful canonical representation should participate naturally in:

- spatial indexing;
- filtering;
- intersection;
- containment;
- spatial joins;
- database queries;
- GIS analysis.

## Fit-for-Purpose Detail

More detail is justified when the use case needs it.

ATAP may evolve toward richer surface and roof semantics without requiring
every workflow to adopt the highest available complexity.

## GIS-Native Is a Research Direction

ATAP does not claim that GIS-native representation already solves every
3D-building problem.

The project asserts a research direction:

> GIS-native building representation still has significant room to evolve.
