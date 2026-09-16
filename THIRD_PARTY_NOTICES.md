# Third-Party Notices

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
