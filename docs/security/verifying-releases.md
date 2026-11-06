<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Release provenance and verification

ATAP's release workflow prepares Python wheels and source distributions from an
existing stable tag, then uses GitHub Artifact Attestations to sign SLSA v1 build
provenance. The tag must resolve to reviewed `main` history. The workflow never
creates, moves or deletes a tag, creates a release, or publishes to PyPI.

This mechanism uses the maintained [actions/attest](https://github.com/actions/attest)
action; its upstream predecessor, slsa-github-generator, is no longer maintained.
All actions are pinned to reviewed full commit SHAs. The read-only prepare/build
jobs cannot sign or upload. The provenance job has OIDC and attestations write
permissions; only the upload job has contents write. Checkout never persists
credentials. No long-lived signing key or package-registry credential is needed.

## Files and trust boundaries

A normal release contains the wheel, sdist, `atap-vVERSION.build.json`,
`atap-vVERSION.SHA256SUMS` and `atap-vVERSION.intoto.jsonl`. The JSONL file is a
genuine GitHub/Sigstore bundle serialized as one JSON record, not an unsigned
statement or a detached checksum called a signature. Its signed in-toto payload
has predicate type `https://slsa.dev/provenance/v1`. The checksum file enumerates
the complete subject set, including the build manifest. GitHub CLI accepts both
single JSON bundles and JSON Lines bundles.

The manifest records the exact source tag/commit, package version, build graph
hash, workflow-event ref/SHA, run identity and distribution digests. A rebuild
adds a run-specific ZIP containing the newly built wheel and sdist under their
original valid package filenames. The ZIP and outer build manifest are attested.
Original published assets remain untouched; rebuilt bytes are not claimed to
match previous builds byte for byte.

For a tag push the workflow-event commit is the tagged source commit. For a
historical `workflow_dispatch`, automatic SLSA provenance identifies the reviewed
`main` workflow execution. It does **not** claim that the workflow ran from the
old tag. Verify that workflow identity, then verify the signed manifest's source
commit against the selected immutable tag. This distinction is essential when
backfilling provenance for tags that predate the workflow.

## Verify a downloaded release

Use [GitHub CLI](https://cli.github.com/manual/gh_attestation_verify) 2.103.3 or
newer. Release checks validate the hosted verifier version before deployment;
the upload guard also fails closed if its verifier is older.
Download the assets and independently obtain the expected source commit and
workflow-event ref/SHA from the reviewed tag and successful release workflow run.
Do not take expected identities only from an unverified manifest.

```sh
gh release download v0.3.1 --repo enygma-id/atap --dir release-download
cd release-download
gh attestation verify atap-0.3.1-py3-none-any.whl \
  --repo enygma-id/atap --bundle atap-v0.3.1.intoto.jsonl \
  --signer-workflow enygma-id/atap/.github/workflows/release.yml \
  --source-ref refs/tags/v0.3.1 --source-digest EXPECTED_SOURCE_COMMIT \
  --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners
```

Repeat verification for **every** attested subject, especially the `.build.json`
manifest. A wheel-only verification does not authenticate a separate manifest.
Check checksums and manifest identity using the reviewed helper:

```sh
python /path/to/reviewed-atap/tools/release_artifacts.py verify \
  --directory . --tag v0.3.1 --source-sha EXPECTED_SOURCE_COMMIT \
  --workflow-ref refs/tags/v0.3.1 --workflow-sha EXPECTED_SOURCE_COMMIT
```

For a historical rebuild, substitute `refs/heads/main` and the expected workflow
commit for the last two flags; keep the old tag's source commit in `--source-sha`.
Download one rebuild asset set into an empty directory, for example with
`gh release download v0.2.0 --repo enygma-id/atap --pattern 'atap-v0.2.0-rebuild-RUN-ATTEMPT*'`.
Use its actual run/attempt values; do not mix original assets or several rebuilds
in the verification directory. The helper rejects unexpected files or multiple
build manifests rather than guessing which set to trust.
The helper verifies all subject signatures, hashes, filenames and metadata,
including distributions inside the rebuild ZIP. Signature verification uses
Sigstore trust material and the transparency evidence through `gh`; JSON parsing
and SHA-256 checks alone are not cryptographic provenance verification.

Successful verification authenticates the workflow and bytes. It does not prove
the absence of software defects or establish SLSA Build Level 3 certification.

## Maintainer procedure for the next release

These are manual commands, not authorization to execute them. The next intended
version is `v0.3.1`; first prepare a separately reviewed metadata/release-notes
change so the tag, wheel and sdist versions match. This workflow change leaves
the current package/version and publication metadata unchanged.

1. Review and merge the release tooling, then the version/release-notes change.
   Require the full CI matrix and scientific golden equivalence.
2. Create the tag only at the reviewed release commit, then create the draft
   release before the workflow reaches its upload job:

   ```sh
   git tag -a v0.3.1 REVIEWED_RELEASE_COMMIT -m "ATAP v0.3.1"
   git push origin refs/tags/v0.3.1
   gh release create v0.3.1 --repo enygma-id/atap --verify-tag --draft \
     --title "ATAP v0.3.1" --notes-file REVIEWED_RELEASE_NOTES.md
   ```

3. Review the workflow run and verify every artifact/manifest as above. If the
   release does not exist, upload fails rather than creating it. Create the draft
   and rerun the failed upload job. Identical existing bytes are skipped; any
   differing name collision fails without replacing assets.
4. Publish the reviewed draft manually when its release gates are satisfied.
   Check the next public Scorecard scan: Token-Permissions must remain 10.
   Signed-Releases can improve only after real signed assets exist on releases.

## Historical rebuilds of v0.2.0 and v0.3.0

The maintainer has chosen to prepare backfills for both existing releases. Run
these only after explicit authorization to upload their new rebuild assets:

```sh
gh workflow run release.yml --repo enygma-id/atap --ref main \
  -f tag=v0.2.0 -f rebuild=true
gh workflow run release.yml --repo enygma-id/atap --ref main \
  -f tag=v0.3.0 -f rebuild=true
```

Do not retag or overwrite their historical wheel, sdist or checksum files. Review
the signed rebuild ZIP/manifest, compare source commits, and append a factual
note to each existing release explaining the rebuild date, workflow run and
new asset names. Keep original notes and artifacts. Immutable published releases
cannot accept new assets; a maintainer must resolve that limitation explicitly,
not move tags or silently replace releases. No historical dispatch is run as
part of implementation or ordinary CI.

## What CI proves

`Release build checks` builds the real existing `v0.2.0` and `v0.3.0` sources with
the same hash-verified build tools and packages them as clearly labelled unsigned
rehearsals. Normal pytest covers source/workflow mismatch, corruption, unexpected
files, path injection, moved tags, duplicate/conflicting assets and idempotency.
Rehearsals have read-only permissions and cannot pass the release upload guard.

Signing, OIDC, repository attestation storage and release upload are deliberately
not exercised on pull requests. The first maintainer-run release/backfill remains
the required end-to-end acceptance test. Do not claim that signed ATAP releases
exist based on successful build rehearsals or unit tests alone.
