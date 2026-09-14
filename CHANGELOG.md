# Changelog

All notable public changes to ATAP should be documented here.

## Unreleased

### Packaged engine and CLI

- added the installable `atap` Python package and public API;
- added `atap run`, `atap validate`, version output, JSONL events, parameter
  files, cancellation polling, stable exit codes, and raster-driver restriction;
- moved verification tools to `tools/`, added tests and cross-platform CI;
- translated engine messages and orientation metadata to English without
  changing scientific output;
- recorded licenses for build, server-extra, and development dependencies.

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
