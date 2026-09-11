# Downstream Engineering

ATAP defines a canonical GIS-native building representation.

It does not prescribe one production rendering or delivery stack.

## Downstream Concerns

Large-scale deployment may require:

- spatial tiling;
- vector/feature partitioning;
- viewport-based loading;
- feature culling;
- streaming;
- caching;
- GPU batching;
- temporary triangulation;
- worker strategies;
- client memory management.

These are important engineering problems, but they are downstream of the
canonical representation.

For example:

```text
current viewport
↓
spatial query / tile selection
↓
load only intersecting ATAP features
↓
temporary extrusion / triangulation
↓
GPU rendering
```

The use of tiling or temporary triangles does not require the canonical ATAP
source to become a mesh.

Different downstream systems should be able to choose different optimization
strategies while consuming the same conceptual ATAP model.
