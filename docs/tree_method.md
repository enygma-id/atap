# Tree & Carbon Elevation Method

ATAP in tree mode (`--mode tree`) processes canopy segmentation polygons, a canopy DSM, and a terrain DTM into hierarchical LoD 1.3 canopy volumes, procedural tree trunks, and individual allometric carbon stock estimates.

The DSM provides surface elevations; the DTM provides bare-ground elevations. Intrinsic canopy height is computed from `nDSM = DSM - DTM`.

---

## Processing Pipeline

```
Input Footprints + DSM + DTM
             │
             ▼
[1] Pre-filtering & Zonal Profiling
    ├─ Reject rooftop false positives (P25 ≥ 20m & area < 50m², P50 ≥ 30m)
    ├─ Reject narrow communication towers/BTS (area < 8m² & P90 ≥ 25m)
    ├─ Reject low grass/ground noise (P90 < 0.2m)
    └─ Clean building wall boundary spillover (P50 + 2.5 × IQR)
             │
             ▼
[2] Individual Tree Detection (ITD)
    ├─ Multi-tree clusters (area ≥ 25 m²): Adaptive VWF Local Maxima (r = 2.5–2.8m, 0.32 × H)
    ├─ Saddle Prominence Filter: Merges branches into main stem if saddle drop < 1.2m or < 18% H
    ├─ Marker-controlled Watershed segmentation
    └─ Yields individual tree polygons {oid}_T{k:02d} and apical peaks (X_apex, Y_apex)
             │
             ▼
[3] LoD 1.3 Canopy & Trunk Synthesis
    ├─ Silvicultural Crown Base Height: H_trunk = 0.35 × H_max
    ├─ Organic nDSM vertical slicing: Tier P00 (base), P01 (body), P02 (dome)
    ├─ Canopy tiers elevated above trunk zone: base_height_agl_m = H_trunk
    └─ Trunk pole synthesized at (X_apex, Y_apex, Z_ground)
             │
             ▼
[4] Pantropical Allometry & Carbon Accounting
    ├─ DBH (cm) = 0.55 × (H^0.92) × (D_crown^0.42)
    ├─ AGB (kg) = 0.0673 × (ρ × DBH² × H)^0.976  [ρ = 0.57 g/cm³]
    ├─ Carbon stock (kg C) = AGB × 0.47
    └─ CO2 equivalent (kg CO2e) = Carbon × 3.667
             │
             ▼
[5] Standard Outputs
    ├─ output.geojson (LoD 1.3 floating canopy polygons)
    ├─ output_points.geojson (3D tree trunk base points)
    └─ output_summary.json (Area-level aggregates in Mg C and Mg CO2e)
```

---

## 1. Pre-filtering & Zonal Profiling

2D AI segmentation models applied to aerial orthophotos often detect rooftop garden features, outdoor AC compressor banks, and telecommunication antennas as tree crowns. In addition, legitimate street trees growing adjacent to tall buildings often bleed boundary pixels onto exterior building walls, artificially elevating tree heights to 60–70 metres.

ATAP profiles the raw nDSM pixel distribution under each polygon before decomposition:

1. **Rooftop False Positives:** Rejected if $P_{25} \ge 20.0\text{ m}$ and area $< 50\text{ m}^2$, or $P_{50} \ge 30.0\text{ m}$, or $\min(\text{nDSM}) \ge 20.0\text{ m}$.
2. **Antenna Towers:** Rejected if polygon area $< 8.0\text{ m}^2$ and $P_{90} \ge 25.0\text{ m}$.
3. **Low Ground Noise:** Rejected if $P_{90} < 0.2\text{ m}$.
4. **Wall Boundary Spillover:** For ground trees with $P_{50} < 20.0\text{ m}$ but maximum pixel $\ge 25.0\text{ m}$, pixels exceeding $\min(35.0, P_{50} + 2.5 \times \text{IQR})$ are clipped, restoring the true biological crown apex.

---

## 2. Individual Tree Detection (ITD)

When adjacent trees grow with overlapping crowns, 2D segmentation produces multi-tree clusters. 

For polygons with area $\ge 25\text{ m}^2$ (`cluster_min_area_m2`):
1. **Adaptive Variable Window Filter (VWF):** A dynamic 2D maximum filter with radius $r = \max(2.5\text{ m}, \min(2.8\text{ m}, 0.32 \times H_{\text{clean}}))$ scans the smoothed nDSM surface ($\sigma = 0.85$) for local apical dominance peaks (Popescu & Wynne, 2004).
2. **Saddle Prominence Filter:** Candidate peaks are evaluated along the topographic transect between them. If the intervening saddle elevation drop is shallow ($\Delta H_{\text{saddle}} < 1.2\text{ m}$ or $< 18\% \times \min(H_1, H_2)$), the candidate is classified as a lateral branch of the dominant tree and merged, preventing over-fragmentation of wide tropical crowns.
3. **Marker-controlled Watershed Segmentation:** Selected distinct apical markers seed a morphological watershed transform (Vincent & Soille, 1991) partitioning the cluster into discrete spatial domains $\Omega_k$.
4. **Sub-region Indexing:** Sub-regions are indexed as `{object_id}_T01`, `{object_id}_T02`, etc., each anchored by its true apical peak coordinate $(X_{\text{apex}}, Y_{\text{apex}})$ and clean physical height $H_{\text{apex}}$. Polygons smaller than $25\text{ m}^2$ are retained as single trees without splitting.

### 2.1 Marker Mask (`m_mask`) & Domain Restriction for Apical Apex

Each identified tree $k$ corresponds to a binary spatial territory mask $M_k(p) = [p \in \Omega_k]$. 

In continuous calculus, the true physical apex of tree $k$ is defined as the supremum of physical height $H$ over the intersection of its watershed basin $\Omega_k$ and the valid domain of measurement:

$$\text{Apex}_k = \arg\max_{p \in \Omega_k \cap \operatorname{dom}(H)} H(p)$$

where $\operatorname{dom}(H) = \{p \mid H(p) \in \mathbb{R} \text{ and } H(p) \text{ is finite}\}$.

### 2.2 IEEE 754 NoData / Void Isolation

In remote sensing rasters, point-cloud ground dropouts under dense foliage or flight-boundary clipping create NoData pixels (encoded as $-32767.0$ or IEEE 754 `NaN`). Under standard IEEE 754 floating-point arithmetic:

$$\text{NaN} \times 0.0 = \text{NaN}$$

Naïve array masking ($H \cdot M_k$) propagates `NaN` across the bounding window, causing discrete `argmax` functions to default to index $(0, 0)$ outside the canopy and collapsing physical tree height to the baseline floor ($0.2\text{ m}$).

ATAP rigorously enforces mathematical domain restriction prior to apex extraction:
```python
target = np.where(m_mask & np.isfinite(ndsm), ndsm, 0.0)
m_py, m_px = np.unravel_index(np.argmax(target), target.shape)
m_h = float(target[m_py, m_px])
```
This isolates voids from the optimization domain, guaranteeing that apex coordinates $(X_{\text{apex}}, Y_{\text{apex}})$ and physical height $H_{\text{apex}}$ represent genuine LiDAR canopy maxima.

---

## 3. Silvicultural Trunk Ratio & Floating Canopy LoD 1.3

Airborne LiDAR sensors measure surface canopy tops and ground returns, but cannot directly measure obscured tree trunks underneath dense foliage.

ATAP applies the standard silvicultural Crown Ratio model (USDA Forest Service i-Tree Eco; Pretzsch et al., 2015):
- **Trunk Zone (Crown Base Height):** $H_{\text{trunk}} = 0.35 \times H_{\text{apex}}$ (35% total tree height).
- **Canopy Zone:** $H_{\text{crown}} = 0.65 \times H_{\text{apex}}$ (65% total tree height).

### 3.1 Organic Vertical LoD 1.3 Canopy Slicing
Rather than applying building parcel footprint algorithms, ATAP slices the localized nDSM vertically into multi-tier canopy components ($P00$ base canopy, $P01$ mid-canopy body, $P02$ apical dome):
- **Tier Count:** 3 tiers for $H_{\text{crown}} \ge 2.0\text{ m}$; 2 tiers for $H_{\text{crown}} \ge 0.8\text{ m}$; 1 tier otherwise.
- **Vertical Extent:** Tier step $\Delta h = H_{\text{crown}} / N$. Each tier has thickness $\text{part\_height\_m}$, floating at $\text{base\_height\_agl\_m} = H_{\text{trunk}} + \text{level} \times \Delta h$.
- **Slice Geometry:** Level $0$ retains the outer canopy footprint boundary. Sub-tiers (Level $1+$) extract contours from $\text{nDSM} \ge \text{base\_height\_agl\_m}$ intersected with the crown boundary. When LiDAR returns are sparse or diffuse, concentric morphological inward buffering ($20\%$ and $40\%$ crown radius) serves as an organic fallback.

Trunk poles are positioned at $(X_{\text{apex}}, Y_{\text{apex}}, Z_{\text{ground}})$ extending from bare-ground elevation up to $H_{\text{trunk}}$, where the lowest canopy tier ($P00$) seamlessly rests upon them.

---

## 4. Allometric Carbon Model

Tree biomass and carbon stocks are estimated using standard pantropical allometric equations:

1. **Crown Diameter Allometry ($D_{\text{crown}}$, m):**
   $$D_{\text{geom}} = 2 \times \sqrt{\frac{\text{Area}}{\pi}}$$
   $$D_{\text{crown}} = \min(D_{\text{geom}}, \max(2.5, \min(18.0, 1.5 \times H_{\text{apex}})))$$
   This preserves natural wide canopies ($6 - 15\text{ m}$) from authoritative footprints while bounding unsegmented edge artifacts to realistic biological limits.
2. **Diameter at Breast Height (DBH, cm):**
   $$\text{DBH} = 0.55 \times (H_{\text{apex}}^{0.92}) \times (D_{\text{crown}}^{0.42})$$
3. **Aboveground Biomass (AGB, kg dry matter):**
   $$\text{AGB} = 0.0673 \times (\rho \times \text{DBH}^2 \times H_{\text{apex}})^{0.976}$$
   where $\rho$ is the mean tropical hardwood wood density ($0.57\text{ g/cm}^3$ default).
4. **Pure Carbon Stock ($\text{kg C}$):**
   $$\text{Carbon} = \text{AGB} \times 0.47$$
   per standard tropical vegetative carbon fraction ($47\%$).
5. **Carbon Dioxide Equivalent ($\text{kg } CO_2e$):**
   $$\text{CO2e} = \text{Carbon} \times \frac{44.009}{12.011} \approx \text{Carbon} \times 3.667$$
6. **Aggregate Reporting:**
   Total carbon and $CO_2e$ across survey areas are reported in Megagrams Carbon ($\text{Mg C}$ or metric tonnes C) and $\text{Mg } CO_2e$.

---

## 5. Methodological Disclaimer & Operational Scope

All volumetric, biomass, and carbon outputs produced by ATAP tree mode are **empirical mathematical estimates** derived from remote-sensing canopy surface geometry:

1. **Non-Destructive Allometric Proxy:** Sensor measurements (airborne LiDAR or photogrammetric DSM and DTM) capture only the exposed outer canopy envelope and bare earth. Obscured sub-canopy structures (stem taper, trunk diameter at breast height $1.3\text{ m}$, internal decay, root systems) are modeled via allometric scaling relationships rather than in-situ physical measurements.
2. **Estimated vs. Ground-Truth Metrics:** Fields such as `dbh_cm`, `agb_kg`, `carbon_kg`, and `co2e_kg` represent statistical proxies subject to standard remote-sensing estimation uncertainties (typically $\pm 10\text{--}20\%$). They are designed for landscape-scale assessment, environmental screening, and spatial digital twins, not as a legal replacement for certified terrestrial timber tallies or field-verified destructive harvests.
3. **Species Generalization:** Computations default to pantropical broadleaf averages (mean wood density $\rho = 0.57\text{ g/cm}^3$; carbon fraction $0.47$). Stands with known dominant species should calibrate parameters to match local silvicultural tables.

---

## Scientific References

- **Chave, J., et al. (2014).** *Improved allometric models to estimate the aboveground biomass of tropical trees.* Global Change Biology, 20(10), 3177–3190.
- **Chave, J., et al. (2009).** *Towards a worldwide wood economics spectrum.* Ecology Letters, 12(4), 351–366.
- **IPCC (2006).** *2006 IPCC Guidelines for National Greenhouse Gas Inventories.* Volume 4: AFOLU, Chapter 4 (Forest Land).
- **Nowak, D. J., et al. (2008).** *A Ground-Based Method of Assessing Urban Forest Structure and Ecosystem Services.* Arboriculture & Urban Forestry, 34(6), 347–358.
- **Popescu, S. C., & Wynne, R. H. (2004).** *Seeing the Trees in the Forest: Using Lidar and Multispectral Data for Individual Tree Approach.* Photogrammetric Engineering & Remote Sensing, 70(5), 589–604.
- **Pretzsch, H., et al. (2015).** *Crown size and growing space requirement of common tree species in urban conditions.* Urban Forestry & Urban Greening, 14(3), 466–479.
- **Vincent, L., & Soille, P. (1991).** *Watersheds in digital spaces: an efficient algorithm based on immersion simulations.* IEEE Transactions on Pattern Analysis and Machine Intelligence, 13(6), 583–598.
- **Zanne, A. E., et al. (2009).** *Global wood density database.* Dryad Digital Repository.
