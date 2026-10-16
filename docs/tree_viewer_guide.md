# ATAP Deck.gl 3D Tree Viewer Guide

This technical guide provides the data specifications and ready-to-run JavaScript / HTML code for implementing 3D tree visualizations in **deck.gl** using artifacts produced by ATAP Tree Mode.

---

## 1. Canopy Tiers GeoJSON (LoD 1.3 Polygons)

* **Artifact**: `output.geojson` (or `trees_canopy_polygons.geojson`)
* **Geometry**: `Polygon` / `MultiPolygon` (WGS84 EPSG:4326)
* **Target Layer**: `deck.GeoJsonLayer`

### A. Data Schema & Core Attributes

Each feature represents an elevated canopy tier floating above the trunk zone ($H_{\text{trunk}} = 0.35 \times H_{\text{apex}}$):

```json
{
  "type": "Feature",
  "id": "T001-P00",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[119.4829, -5.1192], [119.4831, -5.1192], ...]]
  },
  "properties": {
    "object_id": "T001",
    "part_id": "T001-P00",
    "parent_part_id": null,
    "part_level": 0,
    "ground_elevation_m": 2.30,
    "base_height_agl_m": 4.20,
    "top_height_agl_m": 8.50,
    "part_height_m": 4.30,
    "base_elevation_m": 6.50,
    "top_elevation_m": 10.80,
    "crown_diameter_m": 6.40,
    "total_tree_height_m": 12.00,
    "carbon_kg": 182.4,
    "co2e_kg": 668.9
  }
}
```

| Property | Type | Unit | Description |
|---|---|---|---|
| `part_height_m` | float | m | Vertical thickness of the canopy tier to extrude. |
| `base_height_agl_m` | float | m | Height above ground level where this tier begins ($H_{\text{trunk}}$ for $P00$). |
| `base_elevation_m` | float | m | Absolute base elevation ($Z_{\text{ground}} + \text{base\_height\_agl\_m}$). |
| `ground_elevation_m` | float | m | Ground terrain elevation ($Z_{\text{ground}}$ from DTM). |
| `part_level` | int | 0, 1, 2 | Tier rank ($0$ is base canopy, $1+$ are ascending sub-tiers). |

### B. Implementation in Deck.gl

To render elevated floating canopy tiers in Deck.gl, translate polygon vertex Z coordinates to `base_elevation_m` (or `base_height_agl_m`), and extrude by `part_height_m`:

```javascript
// Helper: Elevate 2D polygon rings to 3D base elevation
function elevateFeature(feature, useDtm = true) {
  const p = feature.properties;
  const baseZ = useDtm ? (p.base_elevation_m || p.base_height_agl_m || 0) : (p.base_height_agl_m || 0);
  const geom = JSON.parse(JSON.stringify(feature.geometry));
  
  const elevateRing = ring => ring.map(c => [c[0], c[1], baseZ]);
  if (geom.type === 'Polygon') {
    geom.coordinates = geom.coordinates.map(elevateRing);
  } else if (geom.type === 'MultiPolygon') {
    geom.coordinates = geom.coordinates.map(poly => poly.map(elevateRing));
  }
  return { ...feature, geometry: geom };
}

// 1. Deck.gl GeoJsonLayer for LoD 1.3 Canopy Tiers
const canopyTiersLayer = new deck.GeoJsonLayer({
  id: 'atap-canopy-tiers',
  data: rawCanopyGeojson.features.map(f => elevateFeature(f, true)),
  extruded: true,
  wireframe: true,
  filled: true,
  getElevation: f => f.properties.part_height_m,
  getFillColor: f => {
    const lvl = f.properties.part_level || 0;
    // Layered foliage green gradient
    if (lvl === 0) return [45, 106, 50, 230];  // Base crown
    if (lvl === 1) return [60, 130, 65, 235];  // Mid tier
    return [85, 160, 75, 240];                 // Apex dome
  },
  getLineColor: [20, 60, 20, 180],
  lineWidthMinPixels: 1,
  pickable: true
});
```

---

## 2. GLB Viewer (ScenegraphLayer & ColumnLayer)

* **Artifacts**:
  1. `output_points.geojson` (companion 3D tree coordinates)
  2. `tree_trunk.glb` (normalized $1\times 1\times 1\text{m}$ bark mesh, pivot at $Z=0$)
  3. `tree_canopy.glb` (normalized $1\times 1\times 1\text{m}$ foliage dome, pivot at $Z=0$)
* **Target Layers**: `deck.ScenegraphLayer` and `deck.ColumnLayer`

### A. Data Schema & Core Attributes

Each point feature represents one detected tree centered at its apical peak $(X_{\text{apex}}, Y_{\text{apex}}, Z_{\text{ground}})$:

```json
{
  "type": "Feature",
  "id": "T001",
  "geometry": {
    "type": "Point",
    "coordinates": [119.482914, -5.119283, 2.30]
  },
  "properties": {
    "object_id": "T001",
    "height": 12.00,
    "trunk_height": 4.20,
    "trunk_diameter": 0.35,
    "crown_height": 7.80,
    "crown_diameter": 6.40,
    "ground_elevation_m": 2.30,
    "carbon_kg": 182.4,
    "co2e_kg": 668.9
  }
}
```

| Property | Unit | Description | Deck.gl Usage |
|---|---|---|---|
| `coordinates` | `[lon, lat, z]` | Geo-coordinates and ground DTM elevation. | `getPosition` anchor point. |
| `trunk_height` | m | Silvicultural Crown Base Height ($0.35 \times H$). | Trunk height scale & canopy base lift. |
| `trunk_diameter` | m | Allometric DBH trunk diameter. | Trunk horizontal scale (`getScale[0, 1]`). |
| `crown_height` | m | Canopy dome thickness ($0.65 \times H$). | Canopy vertical scale (`getScale[2]`). |
| `crown_diameter` | m | Canopy crown spread diameter. | Canopy horizontal scale (`getScale[0, 1]`). |

### B. Implementation in Deck.gl

Both models are normalized to unit dimension $[1\times 1\times 1\text{m}]$ with Z-up coordinates. Scale factors directly translate to physical meters:

```javascript
// 1. Procedural Trunk (ColumnLayer or ScenegraphLayer)
const trunkLayer = new deck.ScenegraphLayer({
  id: 'tree-trunks-glb',
  data: treePointsGeojson.features,
  scenegraph: '/models/tree_trunk.glb',
  _lighting: 'pbr',
  getPosition: f => [
    f.geometry.coordinates[0],
    f.geometry.coordinates[1],
    f.properties.ground_elevation_m || 0
  ],
  getScale: f => {
    const td = f.properties.trunk_diameter || 0.35;
    return [td, td, f.properties.trunk_height || 2.0];
  },
  pickable: true
});

// 2. Organic Foliage Dome (ScenegraphLayer)
const canopyGlbLayer = new deck.ScenegraphLayer({
  id: 'tree-canopy-glb',
  data: treePointsGeojson.features,
  scenegraph: '/models/tree_canopy.glb',
  _lighting: 'pbr',
  getPosition: f => [
    f.geometry.coordinates[0],
    f.geometry.coordinates[1],
    (f.properties.ground_elevation_m || 0) + (f.properties.trunk_height || 0)
  ],
  getScale: f => {
    const cd = f.properties.crown_diameter || 4.0;
    const ch = f.properties.crown_height || 6.0;
    return [cd, cd, ch];
  },
  pickable: true
});
```

---

## 3. Mode B: OGC 3D Tiles 1.1 (`Tile3DLayer` for City-Scale Streaming)

* **Artifacts**:
  1. `tileset.json` (Hierarchical spatial index & ENU-to-ECEF transforms)
  2. `tiles/tile_{gx}_{gy}.glb` (Spatial chunked 250m × 250m merged GLB with `EXT_mesh_gpu_instancing`)
* **Target Layer**: `deck.Tile3DLayer` with `@loaders.gl/3d-tiles`
* **Use Case**: Massive datasets (> 2,000 trees up to 100,000+ trees / 1,000 Ha pilot areas) requiring GPU instancing and frustum culling.

### A. Data Schema & Chunking Concept

1. **Spatial Grid Partitioning**: Area partitioned into 250m × 250m cells based on UTM coordinates (`x_utm`, `y_utm`).
2. **Relative-To-Center (RTC)**: Vertex coordinates normalized to local center to prevent 32-bit floating-point jitter in WebGL.
3. **Vertex Normalization**: Unit meshes transformed to glTF 2.0 Y-up (`[X, Y, Z] -> [X, Z, -Y]`).
4. **Instancing & Feature IDs**: Trunk and Canopy instances bound to identical `_FEATURE_ID_0` and attached to individual nodes.

### B. Implementation in Deck.gl

```javascript
import { Tile3DLayer } from '@deck.gl/geo-layers';
import { Tiles3DLoader } from '@loaders.gl/3d-tiles';

const tree3DTilesLayer = new Tile3DLayer({
  id: 'atap-tree-3dtiles',
  data: '/tiles/{job_id}/tileset.json',
  loader: Tiles3DLoader,
  pickable: true,
  autoHighlight: true,
  highlightColor: [255, 255, 255, 180],
  loadOptions: {
    tiles3d: {
      loadGLTF: true
    }
  },
  _subLayerProps: {
    scenegraph: {
      _lighting: 'pbr'
    }
  },
  onTileLoad: (tileHeader) => {
    console.log(`Loaded tree tile: ${tileHeader.content.uri}`);
  }
});
```

---

## 4. Summary & Audit Report

* **Artifact**: `output_summary.json`
* **Format**: Standard JSON

```json
{
  "mode": "tree",
  "total_trees": 222,
  "total_canopy_parts": 436,
  "mean_height_m": 8.75,
  "min_height_m": 2.10,
  "max_height_m": 24.80,
  "total_carbon_mg": 18.420,
  "total_co2e_mg": 67.546,
  "skipped_tree_count": 15,
  "skipped_trees": [...]
}
```

Use `total_carbon_mg` for aggregate environmental dashboard KPIs (1 Megagram = 1 Metric Ton).

---

## 5. Minimal Standalone HTML + Deck.gl Template

Copy and save the snippet below as `viewer.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>ATAP Tree 3D Viewer</title>
  <script src="https://unpkg.com/deck.gl@9.3.11/dist.min.js"></script>
  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
  <style>
    body { margin: 0; padding: 0; overflow: hidden; background: #0b0f14; }
    #deck-canvas { width: 100vw; height: 100vh; }
  </style>
</head>
<body>
  <div id="deck-canvas"></div>
  <script>
    const deckgl = new deck.DeckGL({
      container: 'deck-canvas',
      mapStyle: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      initialViewState: { longitude: 119.4829, latitude: -5.1192, zoom: 17, pitch: 55, bearing: -20 },
      controller: true,
      layers: [] // Add canopyTiersLayer, trunkLayer, and canopyGlbLayer here
    });
  </script>
</body>
</html>
```
