<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# OpenSSF Best Practices evidence inventory

Assessment date: 2026-11-06. This document maps every current Passing criterion
from the [official criteria](https://www.bestpractices.dev/en/criteria/0) to
repository evidence or an explicit gap. It is preparation for a maintainer's
self-assessment, not a badge application, certification, or a claim that all
criteria are met. Registration is deferred; there is no badge ID and no badge is
added to the README. Do not fabricate historical performance or reviewer data.

`Evidence` means a concrete repository mechanism exists; maintainers must still
check the criterion's full wording. `Confirm`, `Partial`, and `Gap` are unresolved
items. `N/A candidate` requires a written justification and maintainer review.

| Criterion ID | Assessment | Evidence or remaining action |
|---|---|---|
| `description_good` | Evidence | [README](../../README.md) explains terrain-aware building/tree outputs and scope. |
| `interact` | Evidence | [README](../../README.md) and [contribution guide](../../CONTRIBUTING.md) identify downloads, Issues and pull requests. |
| `contribution` | Evidence | [CONTRIBUTING](../../CONTRIBUTING.md) describes review, acceptance and licensing. |
| `contribution_requirements` | Evidence | [Contribution requirements](../../CONTRIBUTING.md) cover scientific impact, tests, attribution, licenses and review. |
| `floss_license` | Evidence | [AGPL-3.0-only license](../../LICENSE) covers project source; third-party notices remain separate. |
| `floss_license_osi` | Evidence | AGPL-3.0 is OSI-approved; confirm the declared license and distribution inventory during release review. |
| `license_location` | Evidence | [LICENSE](../../LICENSE) is at repository root; [third-party notices](../../THIRD_PARTY_NOTICES.md) cover dependencies. |
| `documentation_basics` | Evidence | [README](../../README.md) documents installation and quick-start workflows. |
| `documentation_interface` | Evidence | [CLI](../cli.md), [API](../api.md) and [output schema](../output-schema.md) document interfaces. |
| `sites_https` | Confirm deployment | GitHub repository, release and preview links use HTTPS. Maintainers must verify all production download endpoints and TLS configuration. |
| `discussion` | Evidence | Public GitHub Issues and pull requests provide searchable, URL-addressable discussion through a browser. |
| `english` | Evidence | Repository documentation, Issue templates and contribution policy use English. |
| `maintained` | Evidence | Recent reviewed commits/releases and the public [main history](https://github.com/enygma-id/atap/commits/main/) demonstrate active maintenance; this is distinct from Scorecard repository-age scoring. |
| `repo_public` | Evidence | [Public source repository](https://github.com/enygma-id/atap). |
| `repo_track` | Evidence | Git history records commits, authors, dates and changes. |
| `repo_interim` | Evidence | [Public pull requests](https://github.com/enygma-id/atap/pulls) expose intermediate changes before releases. |
| `repo_distributed` | Evidence | The project uses Git. |
| `version_unique` | Evidence | [Package version](../../pyproject.toml), release tags and [metadata tests](../../tests/test_release_metadata.py) establish release identifiers. |
| `version_semver` | Evidence | Existing v0.2.0/v0.3.0 tags use a semantic-version format; maintainers retain version/compatibility review. |
| `version_tags` | Evidence | [Release tags](https://github.com/enygma-id/atap/tags) identify versioned source. |
| `release_notes` | Evidence | [Changelog](../../CHANGELOG.md) and [release notes](../maintainers/release-notes-0.3.0.md) explain user-facing changes. |
| `release_notes_vulns` | Confirm history | Maintainers must reconcile known public ATAP advisories with each release note; dependency updates alone do not establish this criterion. |
| `report_process` | Evidence | [CONTRIBUTING](../../CONTRIBUTING.md) and [bug template](../../.github/ISSUE_TEMPLATE/bug_report.yml) explain reporting. |
| `report_tracker` | Evidence | [GitHub Issues](https://github.com/enygma-id/atap/issues) tracks reports. |
| `report_responses` | Confirm history | Review acknowledgement rates over the required reporting window; repository policy does not prove actual response performance. |
| `enhancement_responses` | Confirm history | Review enhancement-request response rates over the required window; justify any new-project exception honestly. |
| `report_archive` | Evidence | Public Issue/PR histories provide searchable archives; private vulnerability reports remain private. |
| `vulnerability_report_process` | Evidence | [SECURITY](../../SECURITY.md) publishes the reporting process and supported versions. |
| `vulnerability_report_private` | Evidence | [SECURITY](../../SECURITY.md) links GitHub private vulnerability reporting and describes safe evidence handling. |
| `vulnerability_report_response` | Confirm history | The policy targets three business days for acknowledgement; actual six-month performance must be confirmed by maintainers without disclosing private reports. |
| `build` | Evidence | [Hatchling build configuration](../../pyproject.toml) and [build/update procedure](../../CONTRIBUTING.md) support automated source builds. |
| `build_common_tools` | Evidence | Python, uv, pip and Hatchling are standard ecosystem tools. |
| `build_floss_tools` | Evidence | The local build toolchain is FLOSS; proprietary developer applications are not required. |
| `test` | Evidence | [FLOSS test suite](../../tests/) and CI document pytest execution. |
| `test_invocation` | Evidence | [CONTRIBUTING](../../CONTRIBUTING.md) documents uv run pytest. |
| `test_most` | Gap | No published branch-coverage threshold or complete input/branch coverage claim; add measured evidence before asserting this suggestion. |
| `test_continuous_integration` | Evidence | [CI workflow](../../.github/workflows/ci.yml) tests reviewed changes on Windows/Linux and uv on macOS. |
| `test_policy` | Evidence | [PR requirements](../../CONTRIBUTING.md) require tests and scientific before/after evidence where applicable. |
| `tests_are_added` | Evidence | [Generated invariants](../../tests/test_properties.py) and [export conformance tests](../../tests/test_external_export_validation.py) accompany recent major changes. |
| `tests_documented_added` | Evidence | [CONTRIBUTING](../../CONTRIBUTING.md) documents test and validation requirements. |
| `warnings` | Evidence | [CI](../../.github/workflows/ci.yml) runs Ruff on proposed changes. |
| `warnings_fixed` | Partial | Ruff passes, but runtime/native-library deprecation warnings still require triage; do not equate a green test suite with zero warnings. |
| `warnings_strict` | Partial | Ruff gates selected errors; maximal warning/branch coverage enforcement is not claimed. |
| `know_secure_design` | Maintainer attestation | A primary developer must personally confirm secure-design knowledge; tooling cannot certify an individual's expertise. |
| `know_common_errors` | Maintainer attestation | [Security scope](../../SECURITY.md) covers input handling, paths, command injection and supply chain; a primary developer must confirm knowledge and mitigations. |
| `crypto_published` | Evidence | Integrity code uses standard SHA-256 through Python hashlib; no proprietary cryptographic algorithm is implemented. |
| `crypto_call` | Evidence | Cryptographic primitives are delegated to standard libraries/platform services, not reimplemented by the scientific engine. |
| `crypto_floss` | Evidence | Python/hashlib and the open-source toolchain provide the project's integrity mechanisms; review deployed TLS services separately. |
| `crypto_keylength` | N/A candidate | ATAP does not generate or configure application signing/encryption keys. Maintainers must assess any deployed TLS/signing service before selecting N/A. |
| `crypto_working` | Confirm inventory | Review the runtime, native dependencies and deployment protocols; SHA-256 checksums do not prove the absence of weak cryptography elsewhere. |
| `crypto_weaknesses` | Confirm inventory | Maintainers must review platform TLS/cryptography and native-library dependencies; no blanket cryptographic compliance claim is made. |
| `crypto_pfs` | N/A candidate | The local engine is not a TLS endpoint. Confirm the actual reverse-proxy/deployment boundary and forward-secrecy settings. |
| `crypto_password_storage` | N/A candidate | The local runner stores no external-user password database; reassess if authentication is added. |
| `crypto_random` | N/A candidate | Scientific random sampling is not cryptographic key generation; review any future security-sensitive random use separately. |
| `delivery_mitm` | Evidence | GitHub repository/release URLs use HTTPS; dependency locks and hashes add integrity controls. |
| `delivery_unsigned` | Evidence | Delivery URLs use HTTPS; no trust is derived from hashes fetched over unauthenticated HTTP. |
| `vulnerabilities_fixed_60_days` | Confirm advisories | [SECURITY](../../SECURITY.md) defines support/remediation. Review current public advisories and age; a clean dependency scan alone is insufficient. |
| `vulnerabilities_critical_fixed` | Confirm history | Review real remediation timing for confirmed critical reports; policy targets are not historical evidence. |
| `no_leaked_credentials` | Confirm settings/history | Confirm secret-scanning/push-protection settings and any remediation history with repository administrators. Do not publish credentials as evidence. |
| `static_analysis` | Evidence | [CodeQL workflow](../../.github/workflows/codeql.yml) analyzes Python, JavaScript/TypeScript and Actions; [CI](../../.github/workflows/ci.yml) also runs Ruff. |
| `static_analysis_common_vulnerabilities` | Evidence | CodeQL security analysis is configured; each finding still requires triage. |
| `static_analysis_fixed` | Confirm findings | Maintainers must review current CodeQL alerts and remediation of confirmed exploitable findings; configuration alone is insufficient. |
| `static_analysis_often` | Evidence | CodeQL runs on main/develop pushes, relevant pull requests and its scheduled scan. |
| `dynamic_analysis` | Evidence | [Atheris workflow](../../.github/workflows/fuzz.yml) and [fuzz instructions](../../fuzz/README.md) provide real bounded dynamic checks. |
| `dynamic_analysis_unsafe` | Partial / N/A review | ATAP-maintained source is Python/JavaScript, with third-party native dependencies. Atheris Python coverage is not an AddressSanitizer/Valgrind claim; assess the native-code boundary. |
| `dynamic_analysis_enable_assertions` | Evidence | Normal pytest/property/fuzz execution retains Python assertions; workflows do not use python -O. |
| `dynamic_analysis_fixed` | Confirm findings | Review dynamic findings and their triage privately. Seed checks or clean bounded campaigns do not establish that all inputs are defect-free. |

## Maintainer completion checklist

- Confirm all 67 rows against the current official definitions before submitting.
- Audit response/remediation history, secure-development knowledge and current
  CodeQL/security reports; keep private report contents out of public evidence.
- Confirm live branch rulesets and repository security settings with an admin;
  checked-in templates do not enforce settings by themselves.
- Measure coverage and triage warnings/dynamic findings before claiming the
  corresponding suggestions or requirements are satisfied.
- Revisit N/A candidates against the actual deployed service and native-code
  boundary, including any authentication/TLS components outside the local engine.
- Register and add a genuine badge only if the maintainer later authorizes it.
  A Scorecard result is not a substitute for this criterion-by-criterion review.

No release, tag, provenance backfill, publication metadata, or repository setting
is changed by this inventory. Release provenance tooling is reviewed separately.
