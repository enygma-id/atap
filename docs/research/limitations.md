# Known Limitations

Current known limitations include:

- stable ATAP is currently DSM/DTM-driven;
- upstream footprint and elevation quality materially affect output;
- DSM is a 2.5D surface and cannot reveal every hidden architectural cavity;
- complex courtyards and lower-level voids remain challenging;
- roof-plane reconstruction is not yet a stable capability;
- LAS/LAZ input is not yet part of the stable profile;
- ATAP does not itself define a production tiling protocol;
- large-scale rendering depends on downstream engineering;
- standards conformance must be evaluated separately from conceptual or visual
  similarity.

Failure cases should be documented rather than removed from research history.

## Known limitations of the elevation engine

These limitations describe engine 0.2.0 / output profile 0.6. They are
preserved in the reference implementation; changing them requires separate
scientific validation.

| ID | Limitation | Practical implication |
|---|---|---|
| KI-1 | Hole area is checked before simplification. Narrow holes can shrink below `max_fill_hole_area_m2`; one synthetic slit shrinks from 8 to 2.5 m². | Inspect narrow voids and test a smaller simplification tolerance. The threshold does not guarantee a minimum final hole area. |
| KI-2 | Four height classes can merge upper tiers when a large podium dominates clustering. Synthetic tiers at 30 and 45 m merge at 33.75 m. | Evaluate sensitivity to `max_height_classes` before interpreting tier counts. Defaults remain unchanged. |
| KI-3 | The authoritative root retains the input footprint. A ground-level courtyard remains solid in the root if the input has no hole. | Supply courtyard holes in the footprint when the root must exclude them. |
| KI-4 | A DSM with a CRS different from `working_crs` is resampled during reprojection. | Select the DSM CRS as the working CRS when it is projected and metric. Automatic selection is a future proposal. |
| KI-5 | Multi-core speed-up has not been measured. | Single-worker benchmark timings do not establish parallel scaling. |
| KI-6 | A terrain overlay toggle is not implemented in the reference viewer. | Ground elevation placement can be inspected, but it does not display a terrain surface. |
| KI-7 | Non-GeoJSON footprint formats require an explicit `id_field`. | Provide a stable, non-empty, unique source ID field; row positions are not identifiers. |
| KI-8 | Parts with `valid_coverage_ratio < 0.5` are flagged only in the viewer tooltip. | Inspect coverage before interpreting results; no separate low-coverage review workflow is provided. |
