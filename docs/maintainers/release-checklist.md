# Release Checklist

Before an official release:

- [ ] verify version and dated changelog;
- [ ] run `uv sync --extra dev --locked`;
- [ ] run Ruff and the complete pytest suite;
- [ ] validate all four reference cases and worker determinism;
- [ ] run playground e2e online and offline;
- [ ] validate every complete golden against the profile JSON Schema;
- [ ] review dependency versions and `uv.lock`;
- [ ] review third-party licenses/notices;
- [ ] check source-file SPDX identifiers;
- [ ] confirm no confidential/client data is included;
- [ ] confirm sample-data redistribution rights: synthetic only;
- [ ] review public API/schema changes;
- [ ] verify README commands from a fresh environment;
- [ ] build and inspect wheel/sdist;
- [ ] run the product-repository guard;
- [ ] prepare release notes;
- [ ] create tag and publish artifacts only after maintainer approval.
