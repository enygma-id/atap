# ATAP Elevation — Decision Log

## ADR-020 Derived building exports

**Status:** Accepted in v0.3.0. **Change class:** E.

A separate post-processing service generates GLB, CityJSON 1.1 and CityGML 2.0
LoD1 solids from validated building results. Canonical GeoJSON and scientific
calculations remain unchanged. CLI/server building runs default to canonical
GeoJSON only; optional derivatives require explicit `--export` or
`export_formats` selection. The Python engine API remains unchanged and a
separate `export_file` helper exposes derivatives.

The playground explicitly starts with GeoJSON only. Compact independent format
buttons select additional GLB, CityJSON and CityGML derivatives, with GeoJSON
always active. Reset restores that selection; tree mode hides building exports.
The UI, CLI and omitted-field server default are all canonical GeoJSON only.

Use one Building per object_id and geometry-bearing parts; retain the original
parent_part_id as an attribute. No duplicate parent geometry or LoD2 claim.
Disconnected CityGML components use child parts, not CompositeSolids. GLB uses
a local origin with explicit CRS metadata. Export failure is reported while
retaining the already persisted canonical output. No renderer state is read.

The mesh adapter removes repeated and exactly collinear boundary vertices with
zero-tolerance, topology-preserving simplification on its derived copy. Caps
and walls use that same boundary: triangulators can otherwise omit vertices
that the walls retain, leaving unmatched edges. Canonical coordinates, holes,
areas and vertical intervals remain unchanged; shell errors include part_id.

The approach adapts Enygma ARCA's writer architecture without its BIM ingestion
dependencies. See [Building exports](building-exports.md).

Decisions taken while turning the original `elevation.py` into the ATAP
engine and packaged reference playground (engine 0.2.0 / profile 0.6).

The normative contract is the ATAP Elevation specification maintained by
the project maintainers; "§" numbers below refer to its sections (its public
form will be `docs/method.md` and `docs/output-schema.md`). This log records
how the prototype fills gaps the specification leaves open and why. A
decision here never overrides the specification; if one appears to, raise it
with the maintainers.

Status values: **Accepted** (implemented in the prototype), **Planned**
(part of the v0.2.0 plan, not implemented yet), **Superseded**.

---

## ADR-001 DTM is mandatory; no fallback ground

**Status:** Accepted. **Spec:** §3.1, §39, Test A.

The engine fails before any processing when the DTM path is empty, missing,
has no CRS, or does not overlap the DSM. The former `no_dtm_ground_elevation_m`
parameter, the "ground = 0" mode and every related code path were removed.
The viewer has no DTM toggle; it offers *Ground elevation ON/OFF* instead
(spec §29).

## ADR-002 DSM is the analysis grid; DTM is resampled onto it

**Status:** Accepted. **Spec:** §3.2, Test B.

- If the DSM is already in `working_crs` and axis-aligned, it is read as-is
  (no resampling).
- Otherwise the DSM is reprojected to `working_crs` with a `WarpedVRT`
  (bilinear, native resolution). This does resample the DSM; recorded as
  `processing.dsm_reprojected = true`. Choose `working_crs` equal to the DSM
  CRS to avoid it; a `working_crs = "auto"` option is proposed (see
  `docs/research/limitations.md`).
- The DTM is always warped with a `WarpedVRT` onto the exact DSM grid
  (same transform, width, height), bilinear, `dtype=float64`.
- Every VRT is created with an explicit `nodata` (source nodata, else NaN).
  Without it GDAL fills areas outside the source with 0, which would turn
  `DSM − 0` into a fake building height.
- Reads use `masked=True` and convert masked pixels to NaN.

## ADR-003 Stable building ID policy

**Status:** Accepted. **Spec:** §13.1.

- The ID source is one properties key for the whole dataset:
  1. an explicit `id_field` selects that properties key;
  2. otherwise automatically select `properties.id`;
  3. fail with counts if the selected key is missing or empty on any feature.
- Top-level input `Feature.id` is ignored. This corrects the earlier input
  interpretation before release; output `Feature.id = part_id` remains valid.
- Duplicate normalized IDs fail (they would produce duplicate `part_id`).
- IDs are normalised to strings: integers and integral floats → `"123"`.
- `id_source` records `{"mode":"property","field":"<selected key>"}`.
- GeoJSON is parsed with `json` to preserve source property values. Other
  vector formats use GeoPandas and follow the same attribute selection rule.
- Footprint CRS: legacy GeoJSON `crs` member if present, else EPSG:4326 per
  RFC 7946. Non-GeoJSON without CRS fails.

## ADR-004 Fail fast; no quarantine; skipped buildings are reported

**Status:** Accepted. **Spec:** §32 (`skipped_or_error`), §39.

- Contract violations (missing inputs, IDs, CRS, alignment, invalid output)
  raise `AtapInputError` / `AtapValidationError` / `AtapError`, and no file
  is written.
- A building that cannot be measured is skipped, not failed, and listed in
  `summary.skipped_buildings` with a reason code:
  `INVALID_OR_EMPTY_FOOTPRINT`, `OUTSIDE_ANALYSIS_GRID`,
  `NO_VALID_DSM_DTM_PIXELS`. Skipped buildings have no parts in the output.
- If no building produces parts, the run fails.
- The older playground's "quarantine / strict" validation mode and the
  `rejected` artifact were dropped: invariants are guaranteed by
  construction, so a validation failure is a bug that must be visible.
- Cancelling a run writes nothing (a partial file is not canonical).

## ADR-005 Hierarchy construction

**Status:** Accepted. **Spec:** §7, §11, §12, §33–36.

For each detected level `L ≥ 1` of one building:

1. `raw = cumulative class mask (classes ≥ level L)`.
2. `m = closing(raw) | raw`, then `fill_small_holes`, then
   `m &= mask of level L−1` (root = footprint raster). This raster nesting
   keeps upper levels inside lower ones before any vector work.
3. Polygonize; drop polygons `< min_subregion_area_m2`; regularize (ADR-006);
   clip to the root footprint; drop if `< min_subregion_area_m2 / 2`.
4. Candidates are processed largest first. Parent = the part at detection
   level `L−1` with the largest `area(child ∩ parent) / area(child)`, valid
   if `≥ parent_min_containment_ratio` (default 0.5). If none qualifies,
   try `L−2`, …, and finally the root (always accepted).
5. `child = child ∩ parent`. If the parent is not at `L−1` (ancestor
   fallback), subtract parts at the intermediate levels so vertical intervals
   cannot overlap. Also subtract parts already accepted at level `L`
   (regularization can make siblings overlap).
6. Each remaining polygon piece `≥ min_subregion_area_m2 / 2` becomes its own
   part with the same parent (spec §35).
7. `part_level = parent.part_level + 1` (hierarchy depth). The detection
   level is internal only, so an ancestor-fallback child may have a
   `part_level` lower than its detection level.
8. `decomposition_reason` = `HEIGHT_AND_FOOTPRINT_CHANGE`, or
   `HEIGHT_AND_FOOTPRINT_CHANGE_ANCESTOR_FALLBACK` for step 4 fallbacks.
9. `parent_containment_ratio` (score before clipping) is written as a QA
   field; null for roots.

Root reason codes: `AUTHORITATIVE_ROOT` (has children),
`SINGLE_MASS_UNIFORM_HEIGHT`, `SINGLE_MASS_SINGLE_HEIGHT_CLASS`,
`SINGLE_MASS_NO_FOOTPRINT_CHANGE`, `SINGLE_MASS_INSUFFICIENT_BUILDING_PIXELS`,
`SINGLE_MASS_DERIVED_PARTS_FILTERED`.

Part IDs: `<object_id>-P<nn>` in creation order (root `P00`, then level by
level, largest first). Topology is carried only by `parent_part_id`.

## ADR-006 Holes, courtyards and regularization

**Status:** Accepted. **Spec:** §14, §15, Test E.

- `binary_fill_holes` is never applied unconditionally. `fill_small_holes`
  labels enclosed background regions (4-connectivity, not touching the
  window edge) and fills only those `≤ max_fill_hole_area_m2`.
- Regularization (`simplify` → circle / minimum rotated rectangle /
  orthogonalize) is applied to the **shell only**. Holes larger than
  `max_fill_hole_area_m2` are simplified with the same tolerance and
  subtracted back, so courtyards survive regularization.
- Areas and volumes use net area (holes excluded).
- The root is the input footprint unchanged: the root only has holes if the
  input footprint has them (known limitation, see `docs/research/limitations.md`).
- The morphology window is padded by `morph_closing_iters + 2` pixels;
  otherwise `binary_closing` erodes true pixels at the window edge.
- Known inconsistency: the hole-size threshold is evaluated before
  simplification, so a narrow hole can end smaller than the threshold
  (known limitation, see `docs/research/limitations.md`).

Reference behaviour (`courtyard` dataset, DSM 0.1 m, level-1 part, hole
areas in m²; "–" = filled):

| Variant | A 400 | B 9 | C 2.25 | D 0.16 | E 0.4 m slit | F 0.8 m slit | Net area | Volume |
|---|---|---|---|---|---|---|---|---|
| defaults | 388.2 | 7.4 | – | – | – | 2.5 | 4501.97 | 54023.64 |
| `max_fill_hole_area_m2=0` | 388.2 | 7.4 | 0.8 | – | – | 2.5 | 4501.21 | 54014.52 |
| `max_fill_hole_area_m2=10` | 388.2 | – | – | – | – | – | 4511.82 | 54141.84 |
| `max_fill_hole_area_m2=500` (≈ legacy) | – | – | – | – | – | – | 4900.00 | 58800.00 |
| `morph_closing_iters=0` | 400.0 | 9.0 | – | – | 2.0 | 4.0 | 4485.00 | 53820.00 |
| `morph_closing_iters=6` | 376.7 | 6.1 | – | – | – | – | 4517.16 | 54205.92 |
| `simplify_tolerance_m=0.2` | 399.8 | 8.8 | – | – | – | 7.8 | 4483.60 | 53803.20 |

Lessons: closing iterations are in **pixels** (≈ 2 × iters × resolution is
sealed regardless of the area threshold); simplification shrinks narrow
holes; regularization does not touch holes.

## ADR-007 Rounding order keeps invariants exact

**Status:** Accepted. **Spec:** §30, §31.

Level heights are rounded first (`round_digits`). Every derived value is
computed from rounded components: `part_height = round(top − base)`,
`base/top_elevation = round(ground + agl)`,
`volume = round(round(area) × part_height)`. Serialized invariants therefore
hold up to float representation, and validators still use the spec
tolerance.

## ADR-008 Output writing

**Status:** Accepted. **Spec:** §17–19, §37, §38, §42.

- The FeatureCollection is built as a plain dict and written with `json`
  (not GeoPandas), so foreign members (`atap`, `process`, `inputs`,
  `processing`, `vertical_reference`, `summary`) are preserved.
- `Feature.id = part_id`. Geometry EPSG:4326, 2D, exterior rings CCW
  (RFC 7946), coordinates rounded to `coord_digits` (8, about 1 mm) only if
  the rounded geometry stays valid.
- Atomic write: temp file in the target directory, `fsync`, `os.replace`.
  `allow_nan=False` so NaN can never be serialized.
- No renderer state in the output (no Z, no explode, no colours).
- Extra QA fields beyond the spec example: `parent_containment_ratio`,
  `interior_ring_count`, `geometry_method`. When `keep_properties` is unset, every source property key in the dataset is
  copied; an explicit empty list copies none. Default-discovered keys are sorted, and explicit
  keys are deduplicated in their first order. The effective list is written to
  output metadata. Source attributes are copied flat; a name that collides with a canonical
  field gets the `src_` prefix.
- `orientation_deg` = azimuth of the longest minimum-rotated-rectangle edge,
  clockwise from grid north of `working_crs`, range [0, 180).

## ADR-009 Exact 1D k-means

**Status:** Accepted. **Spec:** §9.

`kmeans_1d` keeps quantile initialisation and Lloyd iterations but computes
them on sorted data with prefix sums (assignment = cut points at centre
midpoints). Results are identical to the n×k distance-matrix version: centres
agree to about 1e-12 m, and only pixels within about 1 µm of a boundary
between two sub-centres, later merged by `merge_close_centers`, can differ.
Measured speed-up: 12× (20k px) to 51× (4M px).

## ADR-010 Parallel execution and I/O

**Status:** Accepted.

- Buildings run in a `ProcessPoolExecutor` with the **spawn** context on
  every OS (same behaviour as Windows; workers do not inherit GDAL handles).
  Each worker opens its own DSM/DTM in an initializer.
- `workers = 0` means automatic selection of up to four processes on every
  platform, limited by the logical CPU and task counts. Explicit positive
  values are capped at eight processes.
- Results are reassembled in input order, so output is identical for any
  worker count.
- Buildings are processed in DSM-tile row-major order for GDAL block-cache
  reuse.
- `gdal_cache_mb` is the total for the job, split across workers without a
  per-worker minimum that could exceed the configured budget.
  **rasterio passes `GDAL_CACHEMAX` to `GDALSetCacheMax64` in bytes**, so the
  value must be `MB × 1024 × 1024`. Passing 512 once made reads 4× slower.
- If an automatically selected process pool stops unexpectedly, the job logs
  a warning and retries once in a single process. Explicit worker counts fail
  with guidance to retry with one worker.
- Cancellation is checked between buildings and about every 0.5 s in
  parallel mode; running batches finish first.
- Measured on the `bench` dataset (1 core): 8.6 s → 3.2 s with ADR-009 and
  the I/O ordering; multi-core scaling not yet measured (known limitation, see `docs/research/limitations.md`).

## ADR-011 GPU support removed

**Status:** Accepted.

The GPU code path never ran (NumPy was always returned). The hotspots were
algorithmic (ADR-009) and I/O-bound, and most of the pipeline is GDAL/GEOS
code that cannot run on a GPU. `use_gpu` and `gpu_min_pixels` were removed.

## ADR-012 Split the engine into a package

**Status:** Accepted (v0.2.0 packaging).

The spec allows a single file (§41) but recommends logical modules. The
repository splits the code into `atap.engine` (library, no web dependencies),
`atap.cli`, and `atap.server` (optional extra) because:

1. spawn workers re-import the module that defines the worker function; if
   that module also defined the web app, every worker would import it;
2. users of the CLI or notebooks should not need FastAPI (`pip install atap`
   vs `pip install "atap[server]"`);
3. the server runs jobs as CLI subprocesses for crash and cancel isolation;
4. `CONTRIBUTING.md` asks PRs to name affected modules and separate
   scientific from non-scientific changes;
5. unit tests per module, and a small auditable surface for untrusted input;
6. the output profile and the HTTP API are versioned independently.

The split is a pure move, proven with `tools/compare_outputs.py`
against golden outputs frozen from the prototype.

## ADR-013 Server runs jobs through the CLI

**Status:** Accepted (v0.2.0).

`atap serve` launches `python -m atap run … --events jsonl --cancel-file …`
per job. There is one running job at a time by default (queue with
positions), cooperative cancellation through a cancel file, and a process
tree kill after a grace period.

## ADR-014 Reference playground

**Status:** Accepted (v0.2.0).

- Single HTML file, no build step, deck.gl **9.3.11** pinned; loads
  `vendor/deck.gl-9.3.11.min.js` first and falls back to the same version on
  unpkg only when opened outside the server.
- API base defaults to the page origin.
- *Ground elevation* toggle: OFF = LOCAL_PLANE (`base_height_agl_m`,
  default), ON = WORLD_ELEVATION (`base_elevation_m`). Extrusion is always
  `part_height_m` (spec §22). Explode is viewer-only.
- The browser preflights the footprint before upload with the same ID
  priority as the engine (blocks Run on missing or duplicate IDs), suggests
  the UTM zone, and checks the upload limit.
- UI language is English; every parameter has a short plain-language hint.
- The client re-checks spec §30 invariants (minus containment) and rejects
  legacy LOD1 files.

## ADR-015 Legacy compatibility shims

**Status:** Accepted; removed in v0.2.0 packaging.

The prototype accepted `embed_ground_z` as an ignored compatibility option.
The packaged public API removes it because renderer Z state is outside the
canonical engine contract and the repository has no callers that require it.

## ADR-016 Reuse uploaded input and name result downloads

**Status:** Accepted (pre-release v0.2.0).

- `POST /api/jobs` accepts either all three files or `source_job_id` plus params.
  UUID lookup resolves a retained job's original input directory; clients never
  submit paths. Reuse reads the same files without copying rasters.
- Parameters, output, log, and cancellation remain in a new UUID folder per run.
  Cancelling a consumer does not cancel or mutate its source.
- Cleanup and reuse submission share a lock. Active consumers pin their input;
  submission and completion refresh retention. Restart clears reusable references.
- The playground caches the accepted job and exact selected File objects for
  this session. File changes upload a new set; a missing source triggers one
  automatic upload fallback. No cross-session or content-hash deduplication.
- Internal artifact names stay fixed. Output download names use the UTC
  submission timestamp plus eight UUID characters, stable for each job:
  `atap_YYYYMMDDTHHMMSSZ_<id>.geojson`. CLI naming remains explicit.
- This is an execution change: no geometry, hierarchy, numerical output, schema,
  scientific defaults, or dependency changes.

## ADR-017 Playground parameter choices

**Status:** Accepted (pre-release v0.2.0).

- Ground elevation statistic and terrain type use single-choice button groups,
  preserving min and DTM defaults.
- The ID field uses a dropdown of footprint properties, auto-selecting id.
  Explicit property-key entry remains supported by the CLI/API.
- Copy attributes uses independent toggle buttons. Every detected property
  starts active on footprint selection and reset; no active buttons means an
  explicit empty keep_properties array. Keys containing commas remain intact.
- Before a footprint is inspected, the list is empty because there are no detected
  keys. The playground sends its detected/selected list explicitly. Copied source
  attributes can differ intentionally from the obsolete four-field selection.
- Button state uses aria-pressed; keyboard focus is preserved after toggling.

## ADR-018 Default to all source properties

**Status:** Accepted (pre-release v0.2.0). Supersedes the four-name source
property default inherited from the prototype.

- An omitted/null keep_properties discovers the union of property keys across
  the footprint dataset, sorts it for deterministic output, and copies every
  available selected value to each generated part.
- An explicit array selects only those keys; [] copies none. Duplicate explicit
  keys are removed while preserving their first order.
- The resolved list, rather than null, is written to processing.parameters so a
  run remains auditable and reproducible. Canonical-name collisions keep the
  existing src_ prefix rule.
- The playground activates every detected key and sends the explicit array.
  Compact 10 px buttons preserve the minimum text-size accessibility rule.
- This intentionally changes source-property retention and parameter metadata.
  Geometry, hierarchy, CRS, vertical values, numerical algorithms, and profile
  schema remain unchanged.

## ADR-019 Complete output provenance

**Status:** Accepted (pre-release v0.2.0).

- Attribute output to ATAP in the existing `atap` member with generator name,
  source URL, and software license. The license field describes the software,
  not generated data.
- Record all resolved non-path configuration across `processing.parameters`,
  CRS fields, and execution metadata. Include requested workers alongside the
  actual count so sequential fallback remains auditable.
- Keep canonical result statistics in `summary` and timing in `process`.
  Do not duplicate them or include absolute paths or renderer state.
- These are additive metadata fields in profile 0.6. Geometry, hierarchy,
  vertical semantics, and numerical output are unaffected.

## ADR-021 Version-only release provenance comparisons

**Status:** Accepted in v0.3.0.

- Package and engine version 0.3.0 must appear in new output provenance;
  canonical profile remains 0.6. No scientific algorithm, parameter, geometry,
  hierarchy, measurement or tree-output behavior changes with this version bump.
- Preserve the historical engine-0.2.0 golden GeoJSON, summaries and original
  strict benchmark hashes. Default comparisons still include engine version.
- Explicit `--ignore-engine-version` compares copies with only the existing
  `atap.engine_version` normalized. Missing provenance still fails. Require the
  actual new provenance separately with `--expected-engine-version 0.3.0`.
- Store scientific benchmark digests separately, deriving them from outputs
  verified against the strict historical hashes. Do not relax coordinates,
  scientific metadata, array order or relationships. Same-version worker
  comparisons never need this normalization.
- Ordinary building CLI/API runs are canonical-only; explicit derivative
  selection is an execution choice. Release documentation must describe that
  behavior consistently and must not claim publication or certification from a
  technical validation pass alone.

## ADR-022 Immutable CI action references

**Status:** Accepted.

- Pin external GitHub Actions to full commit SHAs with release-tag comments,
  verified against the official upstream repository. Retain existing major
  versions when replacing floating tags so pinning does not introduce a migration.
- Refresh pins through review of upstream provenance, release notes and changes;
  require the full CI matrix before merge and never auto-merge action updates.
- Use Ubuntu 24.04 explicitly for Linux jobs. The moving ubuntu-latest label
  migrated to Ubuntu 26.04 and changed benchmark orientation/dimension results;
  an OS-generation upgrade needs separate scientific equivalence review.
  Hosted image revisions and package installation still follow existing settings.
  Scientific code, canonical profile, golden baselines and runtime dependencies
  remain unchanged. Preserve failed golden JSON diagnostics for investigation.

## ADR-023 Reviewed security maintenance

**Status:** Accepted.

- All main changes use independently approved pull requests, including metadata
  and integration changes. Maintainers apply versioned branch ruleset templates;
  template files themselves do not enforce repository settings.
- Keep the 11 existing core CI names stable. Scorecard is advisory; require CodeQL
  only after its actual checks exist following advanced-workflow integration.
- Dependency automation proposes reviewed updates. Scientific behavior, historical
  goldens and profile 0.6 remain unchanged; failed equivalence blocks an upgrade.
- Use a single CodeQL setup method, read-only workflow defaults and job-scoped
  security-event uploads. Checkouts do not retain credentials for later steps.

## ADR-024 Hash-verified CI installation

**Status:** Accepted.

- Install complete hashed Python graphs before installing local checked-out code
  without dependency resolution/build isolation. Keep the engine lock unchanged;
  retain separate NumPy 1 and isolated CFF environments.
- Pin setup-uv and the uv version independently; install the Khronos validator
  with npm ci from an exact version/integrity lock. Preserve all existing CI names.
- Prove scientific equivalence and independent conformance before updating pins;
  require human review of dependency automation. No scientific baseline changes.

## ADR-025 Synchronize dependency update graphs

**Status:** Accepted.

- Resolve application and development updates in the universal `uv.lock`, keeping
  Python 3.10 supported through version markers. Regenerate all CI, runtime,
  NumPy 1, build and CFF requirements together; shared packages must agree.
- Do not ask the pip updater to modify generated `requirements/*.txt` exports
  independently. Retain uv updates for the application and pip updates for the
  separate export-validation tools, plus Actions and npm updates.
- Check CI/runtime exports against the lock in every existing uv-workflow job.
  A uv update requires regenerated exports before review. Keep every existing
  job name, least-privilege permission and full action SHA unchanged.
- Dependency upgrades must preserve all scientific output and pass independent
  export conformance. Do not force incompatible transitive major versions or
  weaken hashes, Python compatibility or golden checks to accept an update.
