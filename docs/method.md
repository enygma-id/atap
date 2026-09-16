# Elevation method

ATAP converts authoritative footprints, a DSM, and a mandatory DTM into hierarchical GIS polygons. The DSM defines the analysis grid; the DTM is resampled to it and intrinsic height is `nDSM = DSM - DTM`.

ATAP clusters valid roof heights, merges nearby classes, requires meaningful footprint change for upper masses, preserves significant holes, polygonizes cumulative levels, and clips every child to its parent. The input footprint remains the authoritative root.

Each part records explicit hierarchy, a height interval above ground, DTM placement, geometry metrics, volume, and raster evidence. A child begins at its parent's top height. Output is EPSG:4326; measurements use the configured projected metric CRS.

See [CLI reference](cli.md), [output schema](output-schema.md), and [known limitations](research/limitations.md).
