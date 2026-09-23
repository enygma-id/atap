# ATAP Sample Area 01

A compact geospatial sample dataset created and prepared by **Enygma** for ATAP research, reproducibility, and GIS-native building-mass experiments.

## Data provenance

According to Enygma, the three inputs in this package were produced as follows:

| File | Creator | Production method |
| --- | --- | --- |
| `data/footprints.geojson` | Enygma | Manual delineation of 37 building footprints by Enygma. |
| `data/dsm.tif` | Enygma | Clipped from Enygma's own drone-survey Digital Surface Model. |
| `data/dtm.tif` | Enygma | Clipped from Enygma's own drone-survey Digital Terrain Model. |

The GeoJSON carries explicit dataset-level provenance metadata and `creator` / `creation_method` feature properties. The original feature geometry, coordinates, identifiers, and other original feature properties were retained. DSM and DTM raster bytes were not altered.

These creation and ownership declarations are provided by Enygma. GeoJSON metadata documents authorship; it does not independently prove legal ownership or replace underlying drone survey records and production logs.

## ATAP workflow

```text
Digital Terrain Model (DTM)
+
Manually delineated building footprints
+
Digital Surface Model (DSM)
    |
Terrain normalization (nDSM = DSM - DTM)
    |
Hierarchical decomposition
    |
GIS-native representation
```

The package is intended as a research and demonstration sample. It is not asserted to be a cadastral dataset, a surveyed accuracy reference, or a validated roof-geometry benchmark.

## Package layout

```text
atap-sample-area-01/
├── README.md
├── LICENSE-DATA.md
├── MANIFEST.sha256
└── data/
    ├── dsm.tif
    ├── dtm.tif
    └── footprints.geojson
```

## Format and coordinate reference systems

| File | Format / CRS | Description |
| --- | --- | --- |
| `data/dsm.tif` | GeoTIFF, EPSG:32750 | Drone-survey DSM sample. |
| `data/dtm.tif` | GeoTIFF, EPSG:4326 | Drone-survey DTM sample. |
| `data/footprints.geojson` | GeoJSON, WGS 84 lon/lat | 37 manually delineated building footprints. |

**Important:** Align the DSM and DTM into a shared CRS, grid, resolution, and extent before calculating nDSM. Do not subtract their pixel arrays as stored.

The sample uses the generic name **ATAP Sample Area 01** and contains no city or project name in its documentation. The geospatial coordinates remain original and can identify the real-world location; this dataset is **not geographically anonymized**.

## Licensing and attribution

Enygma releases the three sample data files under **Creative Commons Attribution 4.0 International (CC BY 4.0)**. Attribution is required for copies and adaptations; modified versions must indicate changes. See `LICENSE-DATA.md` and the [official license](https://creativecommons.org/licenses/by/4.0/).

Suggested attribution:

> ATAP Sample Area 01, created by Enygma, licensed under CC BY 4.0. https://creativecommons.org/licenses/by/4.0/

This data license is distinct from ATAP's software license and does not license third-party software, basemaps, logos, or trademarks.

## Integrity verification

The manifest covers the three data inputs, including the updated GeoJSON.

```bash
# macOS (run from this directory)
shasum -a 256 -c MANIFEST.sha256

# Linux
sha256sum -c MANIFEST.sha256
```
