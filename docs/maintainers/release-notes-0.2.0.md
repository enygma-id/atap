# ATAP 0.2.0 release notes

ATAP 0.2.0 introduces the packaged terrain-aware elevation engine, CLI,
local HTTP job server, and reference deck.gl playground.

Highlights:

- mandatory DSM/DTM terrain normalization with authoritative footprint roots;
- hierarchical building parts with explicit vertical intervals and topology;
- deterministic GeoJSON profile 0.6 with validation, provenance, attribution,
  resolved configuration, and result statistics;
- reusable playground uploads, parameter controls, hierarchy inspection, and
  six level colors;
- cross-platform `uv` development workflow using `.venv`, while retaining pip
  installation for end users;
- synthetic golden cases, JSON Schema, Windows/Linux CI, and browser e2e tests.

Known limitations are documented in `docs/research/limitations.md`. Release
artifacts contain synthetic data only. The Community Edition is
AGPL-3.0-only.
