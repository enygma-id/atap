# ATAP Sample Tree 01

A compact geospatial and 3D tree model sample dataset prepared by **Enygma** for ATAP Individual Tree Detection (ITD), LoD 1.3 multi-tier canopy reconstruction, and pantropical allometric carbon estimation.

## Data Provenance

| File | Creator | Description |
| --- | --- | --- |
| `data/footprints.geojson` | Enygma | 131 tree canopy cluster outlines in WGS 84. |
| `data/dsm.tif` | Enygma | Clipped from drone-survey Digital Surface Model (EPSG:32750). |
| `data/dtm.tif` | Enygma | Clipped from drone-survey Digital Terrain Model (EPSG:4326). |
| `models/tree_trunk.glb` | Enygma | Normalized unit trunk mesh (1×1×1m Z-up, pivot Z=0). |
| `models/tree_canopy.glb` | Enygma | Normalized unit canopy dome mesh (1×1×1m Z-up, pivot Z=0). |

## Package Layout

```text
atap-sample-tree-01/
├── README.md
├── LICENSE-DATA.md
├── MANIFEST.sha256
├── data/
│   ├── dsm.tif
│   ├── dtm.tif
│   └── footprints.geojson
└── models/
    ├── LICENSE.md
    ├── tree_canopy.glb
    └── tree_trunk.glb
```

## Licensing and Attribution

Released under **Creative Commons Attribution 4.0 International (CC BY 4.0)**. See `LICENSE-DATA.md` and `models/LICENSE.md`.

Suggested attribution:

> ATAP Sample Tree 01, created by Enygma, licensed under CC BY 4.0. https://creativecommons.org/licenses/by/4.0/
