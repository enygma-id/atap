# Validation Plan

Validation should cover:

## Geometry

- valid Polygon/MultiPolygon;
- topology;
- expected holes;
- CRS correctness.

## Vertical Consistency

Check invariants such as:

```text
part_height_m =
top_height_agl_m - base_height_agl_m
```

and:

```text
base_elevation_m =
ground_elevation_m + base_height_agl_m
```

## Hierarchy

- valid parent IDs;
- no orphan parts;
- consistent object grouping.

## Reference Comparison

Compare with:

- higher-fidelity mesh;
- photogrammetry;
- point cloud where available;
- manual interpretation;
- known measurements where available.

## Sensitivity

Test multiple building typologies, terrain conditions, and parameter settings.

## Performance

Measure runtime, memory, raster-resolution sensitivity, and building-count
scaling.

A method should not replace the stable baseline because one building looks
better. Improvements should be evaluated across representative cases.
