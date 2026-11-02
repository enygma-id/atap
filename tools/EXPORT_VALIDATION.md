<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Optional export validation toolchain

The `export-conformance` workflow is the executable setup recipe. This toolchain
is for engineering/CI, adds no engine runtime dependencies, and does not alter
`pyproject.toml` or its dependency lock. Validator binaries are not bundled with
the ATAP wheel. Fresh-install environments are excluded from CI evidence uploads.

Direct upstream tool licenses (retain their own distribution notices):

| Tool | Pin | License / source |
|---|---|---|
| cjval | 0.10.0, commit in the validation lock | MIT, https://github.com/cityjson/cjval |
| val3dity | 2.7.0, commit in the validation lock | GPL-3.0-or-later, https://github.com/tudelft3d/val3dity |
| lxml | 6.0.2 | BSD-3-Clause, https://lxml.de/ |
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
