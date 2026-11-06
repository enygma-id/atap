# Third-Party Notices

## Release metadata validation

- cffconvert 2.0.0 (Apache-2.0) validates CFF 1.2.0 in an isolated QA environment.
  It is not an ATAP runtime dependency or bundled validator. The upstream
  license copy is in `third-party/cffconvert/LICENSE`; distribution provenance
  and SHA-256 are recorded in `third-party/MANIFEST.json`. Its dependencies
  retain their upstream notices in that isolated installation.

## Building export geometry

- mapbox-earcut (Python bindings by Samuel Kogler, Mapbox earcut.hpp): ISC.
  Used to triangulate polygon caps while preserving holes. License copies are
  in `third-party/mapbox-earcut/`.
- The binary glTF packing and coordinate convention are adapted from the
  Enygma ARCA GLBWriter, AGPL-3.0-only, revision
  `c2db610afacdf9353611af7c9c73b9887dd40495`:
  <https://github.com/enygma-id/arca/blob/c2db610afacdf9353611af7c9c73b9887dd40495/src/arca/engine/glb.py>.
  ATAP does not require ARCA, OpenSKP, or IFC ingestion dependencies.

ATAP Community Edition is licensed under `AGPL-3.0-only` for covered ATAP
project source.

Third-party software remains subject to its respective upstream license and is
not relicensed merely by being used by or distributed alongside ATAP.

The current Python implementation directly imports or materially relies on:

- NumPy;
- GeoPandas;
- Rasterio;
- Shapely;
- SciPy;
- pandas;
- pyproj;
- Hatchling (MIT), used to build distributions;
- FastAPI (MIT), Uvicorn (BSD-3-Clause), and python-multipart (Apache-2.0),
  provided by the optional server extra;
- pytest (MIT), pytest-cov (MIT), Ruff (MIT), Playwright (Apache-2.0), HTTPX (BSD-3-Clause), and jsonschema (MIT),
  provided by the development extra;
- deck.gl (MIT), distributed with the reference playground;
- native geospatial libraries used through that stack, including GDAL, PROJ,
  and GEOS where applicable.

License texts/notices captured from a reference runtime are preserved under
[`third-party/`](./third-party/).

Before an official release, maintainers should reconcile this inventory against
the exact package manifests, lockfiles, wheels, native binaries, containers,
and release artifacts being distributed.

## Security maintenance provenance

- lxml 6.1.0 (BSD-3-Clause) is an existing optional export-validation tool;
  its upstream license notices are retained in `third-party/lxml/LICENSES.txt`.
- certifi 2026.10.23 (MPL-2.0) remains a transitive dependency; its upstream
  license is retained in `third-party/certifi/LICENSE`.
- Source archive hashes and license provenance are recorded in the manifest.
  These upgrades introduce no new ATAP engine dependency. Upstream distributions
  retain their own native/transitive library notices.

## Optional server dependency updates

- opentelemetry-api 1.45.2 (Apache-2.0) is a transitive requirement of FastAPI
  0.162.0 in the optional server/development extras. The license is compatible
  with AGPL-3.0-only and retained in `third-party/opentelemetry-api/LICENSE`.
  The verified upstream wheel URL and SHA-256 are recorded in the manifest.
  ATAP's scientific engine does not import this package directly.

## CI bootstrap

- astral-sh/setup-uv v10.3.3 (MIT), pinned commit in the CI workflow, installs
  uv 0.13.7 for CI only. Its license is retained in third-party/setup-uv/LICENSE.
  uv is MIT/Apache-2.0 and is neither bundled with nor required by the ATAP engine.
