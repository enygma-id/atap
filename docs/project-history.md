# Project History

## Origin

ATAP originated within **Enygma** from practical geospatial and digital-twin
work.

The project began with a recurring engineering concern: explicit 3D-object-first
workflows could become more complex, renderer-dependent, and less directly
compatible with ordinary GIS operations than the use case actually required.

The initial question was therefore not:

> How can we create another 3D object format?

It was:

> Can useful building-mass complexity remain canonical as GIS geometry and
> attributes?

That question became the foundation of ATAP.

## Founding Sequence

ATAP was initiated by **Erick Karya**, CEO of Enygma, who defined the original
problem, project direction, and fit-for-purpose objective.

**Galang Mahendra**, Supervisor Tech at Enygma, then produced the first working
implementation. That implementation established that the core elevation and
polygonization workflow could operate on real project data and produce useful
geometry.

After the first executable prototype, the project entered an iterative research
phase led by Erick. This included technical review, comparison of alternative
methods, and LLM-assisted exploration of code, mathematical formulation, and
representation strategy.

The most important conceptual refinement from this phase was the decision to
treat the output as a **GIS-native canonical representation**, using
hierarchical nested decomposition and terrain-referenced vertical semantics
rather than treating an explicit mesh or BIM-style object as the persistent
source of truth.

The project then returned to implementation refinement. Galang was asked to
continue the software engineering work so that the prototype could evolve into a
more reproducible package that other users and researchers could clone,
install, run, test, and extend.

## Real-World Project Context

ATAP evolved through real government digital-twin work rather than synthetic
examples alone.

That context provided:

- practical building data;
- real delivery constraints;
- realistic validation pressure;
- a direct comparison between high-complexity 3D workflows and simpler
  fit-for-purpose GIS representations.

Operational acceptance in project work helped demonstrate practical usefulness,
but ATAP does not treat project acceptance alone as scientific validation.

Formal research claims still require reproducible evaluation.

## GIS-Native Direction

The founding development process converged on a high-level principle:

```text
authoritative footprint
+
DSM
+
DTM
↓
terrain normalization
↓
hierarchical building-mass decomposition
↓
GIS-native polygon geometry
+
vertical semantics
+
parent/child relationships
```

Rendering, triangulation, tiling, streaming, viewport loading, and GPU
optimization are treated as downstream engineering concerns.

The canonical ATAP representation is intended to remain independent of any one
renderer or delivery strategy.

## LLM-Assisted Development

LLM systems were used as research and engineering-assistance tools during parts
of the founding process.

They assisted with coding, debugging, technical comparison, mathematical and
physical formulation exploration, documentation, and iterative design
discussion.

Human contributors remained responsible for the problem definition, research
direction, architecture, validation, acceptance or rejection of methods,
scientific claims, licensing, and final software decisions.

See [`ai-usage.md`](./ai-usage.md).

## Founding Attribution

The project's founding initiators and founding roles are recorded permanently
in [`../FOUNDING_TEAM.md`](../FOUNDING_TEAM.md).
