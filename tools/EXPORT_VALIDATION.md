<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Optional export validation toolchain

The `export-conformance` workflow is the executable setup recipe. This toolchain
is for engineering/CI, adds no engine runtime dependencies, and does not alter
`pyproject.toml` or its dependency lock. Validator binaries are not bundled with
the ATAP wheel. Fresh-install environments are excluded from CI evidence uploads.

Install `tools/requirements-export-validation.txt` with hash verification. Its
transitive pins preserve the engine lock selections and are QA-only. Direct pins
are in `tools/requirements-export-validation.in`. Regenerate with uv pip compile
using `--universal --python-version 3.10 --generate-hashes` and constraints
exported from the current `uv.lock`; omit the four direct QA pins from those
constraints so they do not conflict with optional format-reader versions.
Review the generated diff and run the complete conformance suite before merge.

Direct upstream tool licenses (retain their own distribution notices):

| Tool | Pin | License / source |
|---|---|---|
| cjval | 0.10.0, commit in the validation lock | MIT, https://github.com/cityjson/cjval |
| val3dity | 2.7.0, commit in the validation lock | GPL-3.0-or-later, https://github.com/tudelft3d/val3dity |
| lxml | 6.1.0 | BSD-3-Clause, https://lxml.de/ |
| pyogrio | 0.11.1 | MIT, https://github.com/geopandas/pyogrio |
| cjio | 0.9.0 | MIT, https://github.com/cityjson/cjio |
| trimesh | 4.11.0 | MIT, https://github.com/mikedh/trimesh |
| Khronos glTF Validator | 2.0.0-dev.3.10 | Apache-2.0, https://github.com/KhronosGroup/glTF-Validator |

These licenses are compatible with this optional validation use alongside
AGPL-3.0-only ATAP. Reader wheels and source builds also retain the original
notices for their bundled/transitive native libraries. This table does not
relicense those libraries or claim to replace their notices.

The unchanged CityJSON root-schema fixture is CC0-1.0. The full downloaded OGC,
OASIS and W3C schema files retain embedded upstream copyright/license notices;
URLs, versions, sizes and exact SHA-256 hashes are in the validation lock.
Downloaded schemas and tool builds live in `.cache/`, not the source distribution.
No validation implementation from these tools is copied into the ATAP engine.

Missing tools or reports are fatal in the required CI job. Ordinary pytest runs
explicitly skip the optional external-tool tests; the dedicated job enables all
of them with `ATAP_CONFORMANCE=1`. See `docs/building-exports.md` for reproducible
commands and the distinction between runtime checks, format validation, 3D
geometric validity and release approval.

The separate `release-metadata` job runs
`python tools/check_release_readiness.py --out .cache/release-readiness`.
It checks installed/source/lock/CFF version alignment, both sample integrity
manifests and formal CFF 1.2.0 schema validation using isolated cffconvert 2.0.0
(Apache-2.0; license/provenance under `third-party/cffconvert/` and the manifest).
Isolation avoids cffconvert's jsonschema 3.x requirement replacing the engine's
development validator. A technical PASS does not verify dataset ownership,
Zenodo integration, publication date or human release approval.
