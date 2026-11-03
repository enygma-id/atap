# Release Checklist

Use this checklist for subsequent ATAP releases. Record the exact release
commit, responsible reviewer and evidence locations for each publication.
ATAP v0.3.0 is recorded in `CHANGELOG.md` and `release-notes-0.3.0.md`.

- [ ] align pyproject, installed package, engine, CLI, CFF and editable lock versions;
- [ ] confirm the release date, move its changes from Unreleased to a dated
      changelog section, and set CFF `date-released` to the verified date;
- [ ] run `uv lock` when metadata changes and inspect the resulting diff;
- [ ] run `uv sync --extra dev --locked`;
- [ ] run Ruff and the complete pytest suite;
- [ ] validate all four reference cases and worker determinism;
- [ ] for version-only changes, preserve historical golden files/hashes and run
      `python tests/golden/verify.py .cache/baseline --ignore-engine-version --expected-engine-version "$RELEASE_VERSION"`;
      same-version worker comparisons remain strict;
- [ ] run playground e2e online and offline;
- [ ] validate every complete golden against the profile JSON Schema;
- [ ] review dependency versions and `uv.lock`;
- [ ] review third-party licenses/notices;
- [ ] check source-file SPDX identifiers;
- [ ] confirm no confidential/client data is included;
- [ ] run `python tools/verify_sample_manifests.py` for both shipped samples;
- [ ] obtain an explicit human review of each sample's rights to redistribute,
      provenance, privacy, original survey/source contracts and applicable
      dataset/model licenses; retain reviewer/date/approval records privately;
- [ ] do not infer ownership or privacy clearance merely from license text,
      file metadata, generic sample names or passing checksums;
- [ ] use synthetic fixtures for new automated engine/validator tests; do not
      add private surveys, credentials, contracts or undisclosed client data;
- [ ] inspect sample file sizes and applicable GitHub file/repository limits;
- [ ] review public API/schema changes;
- [ ] verify README commands from a fresh environment;
- [ ] build and inspect wheel/sdist;
- [ ] install the wheel non-editably into a clean environment; check
      `importlib.metadata.version('atap')`, API/engine versions, CLI and real exports;
- [ ] run formal CFF 1.2.0 validation with isolated cffconvert 2.0.0:
      `uv tool run --isolated --from cffconvert==2.0.0 cffconvert --validate`;
- [ ] inspect `release-metadata` reports for actual CFF commands/exit codes,
      installed/source/lock version agreement and sample-integrity JUnit;
- [ ] verify the exact candidate SHA passed Ubuntu/Windows Python 3.10/3.12,
      NumPy 1.x, Playwright online/offline and uv on Ubuntu/Windows/macOS;
- [ ] inspect the same SHA's `export-conformance` artifact: validator pins and
      versions, full XSD results, actual CityJSON/GML/GLB hashes, independent
      solids/volume/bounds, negative and missing-tool tests, fresh wheel results;
      a green label or old commit's report alone is insufficient;
- [ ] run the product-repository guard;
- [ ] prepare release notes;
- [ ] confirm CFF authors/identifiers with the authors; schema validity does not
      independently establish identity or external-identifier ownership;
- [ ] confirm the public GitHub repository and organization-approved Zenodo
      integration: sign in, open GitHub, select **Sync now**, enable
      `enygma-id/atap`, and verify its enabled state before publishing a release;
- [ ] keep CFF as the publication metadata source unless a deliberate,
      separately reviewed `.zenodo.json` is added; Zenodo gives that file precedence;
- [ ] re-freeze the SHA and repeat affected checks/CI after any date/version/
      publication metadata change; keep publication NO-GO until human approval;
- [ ] create tag and publish artifacts only after maintainer approval.

After explicit publication approval, publish the stable GitHub Release (a tag
alone does not establish successful Zenodo ingestion), inspect the actual
Zenodo record/errors, and verify its version, creators, license and archived
release association. Add DOI links only after the record exists: version DOI
for this exact release, concept DOI for ATAP across versions. Never rewrite a
published tag merely to backfill a DOI. PyPI publication requires its own approval.

Authoritative publication and hosting guidance:

- [Enable Zenodo GitHub integration](https://help.zenodo.org/docs/github/enable-repository/)
- [CFF metadata and precedence](https://help.zenodo.org/docs/github/describe-software/citation-file/)
- [Archive a GitHub release](https://help.zenodo.org/docs/github/archive-software/github-upload/)
- [DOI versioning](https://zenodo.org/help/versioning)
- [GitHub file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
