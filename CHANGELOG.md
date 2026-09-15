# Changelog

All notable public changes to ATAP should be documented here.

## Unreleased

### Changed (scientific)

- corrected input building ID selection to use an explicit properties key or
  automatically `properties.id`; top-level input Feature identifiers are ignored;
- aligned playground ID selection and provenance with this rule. Synthetic
  geometry, hierarchy, heights, areas, volumes, and part identifiers are unchanged.

### Local server

- reuse uploaded playground input across parameter-only runs without raster
  copies, with retention protection and automatic reupload after expiration;
- name output downloads with a UTC timestamp and short job identifier;

- added `atap serve` with the API v1 job queue, SSE progress, fixed artifacts,
  streamed upload limits, cooperative cancellation and process-tree cleanup;
- isolated engine execution in CLI subprocesses and kept the server process
  free of engine-pipeline imports;
- packaged the reference playground and pinned deck.gl bundle for offline use;
- added a pinned, collapsible building hierarchy tree with part-level metrics
  and keyboard-accessible highlighting, then removed the transitional prototype;
- added HTTP, security, TTL, subprocess and browser integration tests.

### Packaged engine and CLI

- added the installable `atap` Python package and public API;
- added `atap run`, `atap validate`, version output, JSONL events, parameter
  files, cancellation polling, stable exit codes, and raster-driver restriction;
- moved verification tools to `tools/`, added tests and cross-platform CI;
- translated engine messages and orientation metadata to English without
  changing scientific output;
- recorded licenses for build, server-extra, and development dependencies,
  including HTTPX and the packaged deck.gl bundle.

### Elevation prototype

- froze three complete synthetic golden outputs and a benchmark summary with
  a full-output canonical SHA-256, reproduction commands, and runtime provenance;
- added golden verification and Windows/Linux baseline CI.

- imported the reference elevation engine 0.2.0 / profile 0.6, playground,
  and synthetic verification tools without changing their behavior;
- documented implementation decisions and eight known elevation limitations;
- normalized product text line endings with `.gitattributes`.

### Repository foundation

- established ATAP project identity;
- established AGPL-3.0-only Community Edition licensing;
- documented Enterprise Edition model;
- documented Enygma stewardship;
- added governance and contribution policy;
- added GIS-native design rationale;
- added research and publication scaffolding;
- added third-party license provenance.
