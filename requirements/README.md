<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Hash-verified CI dependencies

`ci.txt` and `runtime.txt` are exports of the unchanged `uv.lock`, excluding the
local ATAP package; select dev/server extras for CI, server only for the fresh
wheel smoke check. Regenerate with `uv export --locked --no-emit-project` and the
corresponding extras. Retain hashes. CI builds the checked-out local project
without dependency resolution or isolated build downloads.

`build.in` and `cff.in` define isolated build/CFF tools. Compile their txt files
with `uv pip compile --generate-hashes --universal --python-version 3.10`.
CFF's jsonschema 3 environment must not replace the scientific test environment.
`numpy1.txt` resolves Python 3.12 with numpy 1.26.4, scipy 1.17.1 and rasterio 1.4.4;
other pins match the main lock. Review and re-prove goldens for every refresh.

Setup-uv installs uv 0.13.7, newer than the advisory fix 0.13.4. Action SHAs,
requirements hashes and npm's committed integrity lock are separate controls.
Dependabot proposals still require independent review and scientific regression.

Regenerate all Python graphs with `python tools/export_ci_requirements.py --uv uv`.
The command preserves uv.lock and applies requirements/numpy1.in explicitly.
