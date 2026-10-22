# Tree Mode Data & Model Requirements

ATAP tree mode processes canopy polygons and raster elevation data into 3D GIS volumes and optional 3D GLB assets.

---

## 1. Input Data Requirements

| Input | Format | Description & Constraints |
|---|---|---|
| **Canopy Footprints** | GeoJSON (`.geojson`, `.json`) | Authoritative 2D tree crown polygons. Polygons may be single crowns or overlapping clusters. CRS: EPSG:4326 (WGS84) or projected metric (e.g. UTM). |
| **DSM (Surface)** | GeoTIFF (`.tif`, `.tiff`) | Canopy surface elevation (highest return). Defines the spatial resolution and analysis bounding box. |
| **DTM (Terrain)** | GeoTIFF (`.tif`, `.tiff`) | Bare-ground terrain model. Mandatory for normalized height extraction (`nDSM = DSM - DTM`). Bilinearly resampled onto the DSM grid. |

---

## 2. Output Data Schema

### A. Primary Canopy GeoJSON (`output.geojson`)
RFC 7946 GeoJSON FeatureCollection containing 3D LoD 1.3 canopy polygons. Each feature represents an elevated canopy tier floating above the trunk zone:

```json
{
  "type": "Feature",
  "id": "T001-P00",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "properties": {
    "part_id": "T001-P00",
    "object_id": "T001",
    "parent_part_id": null,
    "part_level": 0,
    "base_height_agl_m": 4.20,
    "top_height_agl_m": 8.50,
    "part_height_m": 4.30,
    "ground_elevation_m": 2.30,
    "base_elevation_m": 6.50,
    "top_elevation_m": 10.80,
    "height_lidar_m": 12.00,
    "crown_diameter_m": 6.40,
    "dbh_cm": 28.5,
    "agb_kg": 412.3,
    "carbon_kg": 193.8,
    "co2e_kg": 710.6,
    "part_area_m2": 32.2,
    "part_volume_m3": 138.5
  }
}
```

### B. Companion 3D Points GeoJSON (`output_points.geojson`)
RFC 7946 GeoJSON FeatureCollection containing point features located at the apical trunk base of each tree:

```json
{
  "type": "Feature",
  "id": "T001",
  "geometry": { "type": "Point", "coordinates": [119.407125, -5.126430, 2.30] },
  "properties": {
    "object_id": "T001",
    "ground_z": 2.30,
    "trunk_height": 4.20,
    "trunk_diameter": 0.285,
    "crown_height": 7.80,
    "crown_diameter": 6.40,
    "height_lidar_m": 12.00,
    "dbh_cm": 28.5,
    "agb_kg": 412.3,
    "carbon_kg": 193.8,
    "co2e_kg": 710.6
  }
}
```

### C. Aggregate Summary JSON (`output_summary.json`)
High-level KPIs for reporting and carbon auditing:

```json
{
  "total_trees": 45029,
  "mean_height_m": 10.58,
  "max_height_m": 32.72,
  "total_carbon_mg": 4125.8,
  "total_co2e_mg": 15129.3,
  "trees_rejected_roof": 56,
  "trees_rejected_antenna": 4,
  "trees_rejected_low": 213
}
```
*Note: $1\text{ Mg} = 1\text{ Megagram} = 1\text{ Metric Tonne} = 1,000\text{ kg}$.*

> **Methodological Disclaimer:** Attributes `dbh_cm`, `agb_kg`, `carbon_kg`, and `co2e_kg` represent empirical allometric estimates derived from remote-sensing canopy surface dimensions ($H_{\text{apex}}$, $D_{\text{crown}}$). They serve as landscape-scale proxies with typical $\pm 10\text{--}20\%$ uncertainty, not direct terrestrial caliper or destructive field measurements.

---

## 3. 3D GLB Model Specifications

ATAP renders trees natively in WebGL using Deck.gl (`ColumnLayer` for trunks and `GeoJsonLayer` for elevated canopy tiers). 

If custom 3D organic meshes (`.glb`) are loaded or uploaded:

### Geometry & Coordinate Alignment
- **Format:** glTF 2.0 Binary (`.glb`).
- **Unit Scale:** Normalized bounding box $1\text{ m} \times 1\text{ m} \times 1\text{ m}$.
  - Trunk: Pivot at base $(0, 0, 0)$, height $Z \in [0.0, 1.0]$, base diameter $1.0\text{ m}$.
  - Canopy: Pivot at base $(0, 0, 0)$, height $Z \in [0.0, 1.0]$, horizontal footprint $X, Y \in [-0.5, 0.5]$ (diameter $1.0\text{ m}$).
- **Up-Axis:** Z-up (standard geospatial alignment).

### Asset Budget & Performance
- **File Size:** $< 50\text{ KB}$ ideal, maximum recommended $< 250\text{ KB}$ per template.
- **Polygon Budget:**
  - Trunk mesh: $< 500$ triangles (tapered cylinder frustum).
  - Canopy mesh: $< 2,500$ triangles (smooth organic ellipsoid foliage clusters).
- **Materials:** PBR Metallic-Roughness with vertex colors or low-resolution texture atlas ($\le 512 \times 512\text{ px}$).
- **GPU Instancing:** Rendered via Deck.gl `ScenegraphLayer` with dynamic per-instance scaling:
  - Trunk scale: `[trunk_diameter, trunk_diameter, trunk_height]`.
  - Canopy scale: `[crown_diameter, crown_diameter, crown_height]`.

---

## 4. Sample Models Provided

ATAP provides pre-built lightweight normalized templates in `samples/models/` and `src/atap/server/static/models/`:
- `tree_trunk.glb` (~1.7 KB): Procedural tapered bark trunk.
- `tree_canopy.glb` (~17.6 KB): 5-cluster organic ellipsoid foliage dome with smooth vertex normals.
