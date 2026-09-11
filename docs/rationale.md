# Rationale

## Why ATAP Exists

ATAP was not conceived as an abstract polygon-processing exercise.

It emerged from practical geospatial and digital-twin work where the founding
team repeatedly encountered a mismatch between the representation being used
and the operational need being solved.

Explicit 3D objects can be valuable, but a 3D-object-first workflow can also
introduce specialized rendering requirements, conversion stages,
renderer-specific assumptions, heavier payloads, and friction with ordinary
GIS analysis.

ATAP begins from a different question:

> What is the simplest canonical representation that preserves the building
> information required by the use case?

For many city-scale, planning, monitoring, taxation, asset, disaster,
environmental, and operational workflows, the answer may remain GIS-native.

## Fit-for-Purpose

ATAP follows a fit-for-purpose principle:

> Use the least complex canonical representation that preserves the information
> required by the intended analysis and downstream use.

ATAP does not reject meshes, BIM, CityGML, CityJSON, or point clouds.

It challenges the assumption that one of those representations must always be
the canonical source of truth.

## The GIS Questions Remain

Even when a building is visualized in 3D, many operational questions remain
ordinary GIS questions:

- Where is it?
- What footprint does it occupy?
- What is its terrain-referenced height?
- How many mass levels can be distinguished?
- Which mass sits above another?
- What is its approximate area and volume?
- How does it intersect other spatial layers?
- Can it be indexed and queried in a spatial database?
- Can it be filtered and styled like ordinary GIS data?
- Can multiple rendering engines consume the same canonical representation?

ATAP exists to keep those questions first-class.

## Simplicity

The project deliberately pursues simplicity.

Simplicity does not mean reducing scientific rigor or ignoring complex
buildings.

It means moving complexity only where it is useful.

ATAP attempts to encode useful building complexity through:

```text
GIS polygon geometry
+
hierarchy
+
vertical semantics
```

without requiring the persistent canonical representation to become an opaque
3D object.

## Openness

ATAP Community Edition is open source under `AGPL-3.0-only`.

Openness is also an interoperability principle.

The canonical representation should remain inspectable, transferable, and
usable without requiring one proprietary renderer or one proprietary data
model.

## Real-World Origin

ATAP evolved through real project work rather than synthetic examples alone.

Government digital-twin work provided practical building data, real delivery
pressure, and a useful environment for testing whether a simpler GIS-native
representation was operationally useful.

That experience informed continued development, but it does not by itself
establish scientific validity or universal accuracy.

Scientific claims still require reproducible validation.

## High-Level Goal

> ATAP exists to make useful three-dimensional building-mass information
> available as a simpler, open, GIS-native canonical representation that can be
> analyzed with ordinary geospatial tools and rendered by multiple downstream
> engines.
