<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Branch ruleset templates

These files are reviewed inputs for a repository administrator, not automation
that changes settings. Before applying, compare existing rulesets and update an
existing matching ruleset instead of creating duplicates.

```sh
gh api repos/enygma-id/atap/rulesets
gh api -X POST repos/enygma-id/atap/rulesets --input docs/security/rulesets/main.json
gh api -X POST repos/enygma-id/atap/rulesets --input docs/security/rulesets/develop.json
```

For an existing ruleset, use `gh api -X PUT repos/enygma-id/atap/rulesets/ID`
with the corresponding `--input` file after verifying its ID.

The main ruleset requires an independent approving code owner, approval of the
latest push, resolved conversations and up-to-date core CI checks. No bypass
actors are configured. Develop only blocks deletion and non-fast-forward pushes.
The 11 CI names were observed on main commit
`625165e51328bf037661569213010c089049e56e`. Scorecard Analysis is advisory and
excluded. Add the actual CodeQL check names after its workflow is merged and
has run successfully; do not require nonexistent checks in advance.

Before merging the security workflow, maintainers must apply these rulesets,
confirm CodeQL default setup is disabled in Settings and obtain an independent
maintainer approval. Never enable default and advanced CodeQL setup together.
