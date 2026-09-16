# SPDX-License-Identifier: AGPL-3.0-only
"""
Synthetic reference datasets for ATAP elevation (no real/client data).

    python make_synthetic.py --out DIR [--dataset stepped|courtyard|bench|all]

Each dataset directory gets: dsm.tif, dtm.tif, footprints.geojson
(properties.id) and footprints_fid.geojson (the same properties.id plus
ignored top-level Feature identifiers).

stepped   300x300 m, DSM 0.1 m EPSG:32750, DTM ~1 m EPSG:4326 (sloped).
          B1 3-tier tower (12/30/45 m), B2 podium + ring with 16x16 m
          courtyard, B3 uniform 50 m tower, B4 podium + two towers,
          B5_out outside the DSM (must be skipped: OUTSIDE_ANALYSIS_GRID).
courtyard 100x100 m, flat DTM. One building: podium 80x80 m (8 m), upper
          mass 70x70 m (20 m) with holes A 400 m2, B 9 m2, C 2.25 m2,
          D 0.16 m2, slits E 0.4x10 m and F 0.8x10 m.
bench     400x400 m, tiled+DEFLATE DSM, 256 buildings in a grid (half
          stepped) + 4 large 3-tier buildings. For runtime benchmarks.
"""
import argparse
import json
import os

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

X0, Y0, RES = 770000.0, 9432000.0, 0.1
TO_LL = Transformer.from_crs(32750, 4326, always_xy=True)
TO_UTM = Transformer.from_crs(4326, 32750, always_xy=True)


def grid(w, h):
    cols = np.arange(w) * RES + X0 + RES / 2
    rows = Y0 - np.arange(h) * RES - RES / 2
    return np.meshgrid(cols, rows)


def box_mask(XX, YY, x0, y0, x1, y1):
    return (XX >= X0 + x0) & (XX < X0 + x1) & (YY <= Y0 - y0) & (YY > Y0 - y1)


def footprint(x0, y0, x1, y1):
    pts = [(X0 + x0, Y0 - y0), (X0 + x1, Y0 - y0), (X0 + x1, Y0 - y1), (X0 + x0, Y0 - y1), (X0 + x0, Y0 - y0)]
    return {"type": "Polygon", "coordinates": [[list(TO_LL.transform(*p)) for p in pts]]}


def write_dsm(path, arr, tiled=False):
    prof = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1, dtype="float32",
                crs="EPSG:32750", transform=from_origin(X0, Y0, RES, RES), nodata=-9999)
    if tiled:
        prof.update(tiled=True, blockxsize=256, blockysize=256, compress="deflate")
    with rasterio.open(path, "w", **prof) as d:
        d.write(arr.astype("float32"), 1)


def write_dtm_4326(path, extent_m, ground):
    lon0, lat0 = TO_LL.transform(X0 - 20, Y0 + 20)
    lon1, lat1 = TO_LL.transform(X0 + extent_m + 20, Y0 - extent_m - 20)
    dres = 0.000009
    w, h = int((lon1 - lon0) / dres) + 1, int((lat0 - lat1) / dres) + 1
    lons = lon0 + (np.arange(w) + .5) * dres
    lats = lat0 - (np.arange(h) + .5) * dres
    LO, LA = np.meshgrid(lons, lats)
    ux, uy = TO_UTM.transform(LO, LA)
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(lon0, lat0, dres, dres)) as d:
        d.write(ground(ux, uy).astype("float32"), 1)


def write_footprints(out, feats):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": k, "NAMOBJ": f"Gedung {k}"}, "geometry": g} for k, g in feats]}
    json.dump(fc, open(os.path.join(out, "footprints.geojson"), "w"))
    for f in fc["features"]:
        f["id"] = f["properties"]["id"]
    json.dump(fc, open(os.path.join(out, "footprints_fid.geojson"), "w"))


def stepped(out):
    rng = np.random.default_rng(0)
    W = H = 3000
    XX, YY = grid(W, H)
    hgt = np.zeros((H, W))
    def box(x0, y0, x1, y1, h):
        hgt[box_mask(XX, YY, x0, y0, x1, y1)] = h
    box(20, 20, 60, 60, 12); box(30, 30, 50, 50, 30); box(35, 35, 45, 45, 45)          # B1
    box(100, 20, 160, 80, 8); box(105, 25, 155, 75, 20)                               # B2
    box(122, 42, 138, 58, 8); box(110, 30, 110.6, 30.6, 8)                             # courtyard + tiny hole
    box(200, 20, 230, 50, 50)                                                         # B3
    box(20, 120, 90, 150, 6); box(25, 127, 40, 142, 25); box(65, 127, 80, 142, 40)    # B4
    ground = lambda x, y: 10 + 0.02 * (x - X0) + 0.01 * (Y0 - y)
    dsm = ground(XX, YY) + hgt + rng.normal(0, 0.15, hgt.shape)
    dsm[0:5, 0:5] = -9999
    write_dsm(os.path.join(out, "dsm.tif"), dsm)
    write_dtm_4326(os.path.join(out, "dtm.tif"), 300, ground)
    write_footprints(out, [("B1", footprint(20, 20, 60, 60)), ("B2", footprint(100, 20, 160, 80)),
                           ("B3", footprint(200, 20, 230, 50)), ("B4", footprint(20, 120, 90, 150)),
                           ("B5_out", footprint(1000, 1000, 1010, 1010))])


def courtyard(out):
    rng = np.random.default_rng(1)
    W = H = 1000
    XX, YY = grid(W, H)
    hgt = np.zeros((H, W))
    def box(x0, y0, x1, y1, h):
        hgt[box_mask(XX, YY, x0, y0, x1, y1)] = h
    box(10, 10, 90, 90, 8); box(15, 15, 85, 85, 20)
    box(22, 22, 42, 42, 8)          # A 400 m2
    box(55, 25, 58, 28, 8)          # B 9 m2
    box(65, 25, 66.5, 26.5, 8)      # C 2.25 m2
    box(75, 25, 75.4, 25.4, 8)      # D 0.16 m2
    box(55, 50, 55.4, 60, 8)        # E slit 0.4 x 10 m
    box(65, 50, 65.8, 60, 8)        # F slit 0.8 x 10 m
    write_dsm(os.path.join(out, "dsm.tif"), 10 + hgt + rng.normal(0, 0.15, hgt.shape))
    prof = dict(driver="GTiff", width=W, height=H, count=1, dtype="float32", crs="EPSG:32750",
                transform=from_origin(X0, Y0, RES, RES))
    with rasterio.open(os.path.join(out, "dtm.tif"), "w", **prof) as d:
        d.write(np.full((1, H, W), 10, "float32"))
    write_footprints(out, [("G1", footprint(10, 10, 90, 90))])


def bench(out):
    rng = np.random.default_rng(2)
    W = H = 4000
    hgt = np.zeros((H, W), "float32")
    feats, i = [], 0
    for gy in range(0, 400, 25):
        for gx in range(0, 400, 25):
            s = rng.uniform(8, 20); x0, y0 = gx + 2, gy + 2; x1, y1 = x0 + s, y0 + s
            c0, r0, c1, r1 = [int(v / RES) for v in (x0, y0, x1, y1)]
            hgt[r0:r1, c0:c1] = rng.uniform(4, 12)
            if rng.random() < 0.5:
                m = int((c1 - c0) * 0.25); hgt[r0 + m:r1 - m, c0 + m:c1 - m] = rng.uniform(15, 40)
            feats.append((f"B{i}", footprint(x0, y0, x1, y1))); i += 1
    for k, (x0, y0) in enumerate([(5, 5), (105, 105), (205, 205), (305, 305)]):
        x1, y1 = x0 + 60, y0 + 60; c0, r0, c1, r1 = [int(v / RES) for v in (x0, y0, x1, y1)]
        hgt[r0:r1, c0:c1] = 10; hgt[r0 + 100:r1 - 100, c0 + 100:c1 - 100] = 30; hgt[r0 + 200:r1 - 200, c0 + 200:c1 - 200] = 55
        feats.append((f"BIG{k}", footprint(x0, y0, x1, y1)))
    write_dsm(os.path.join(out, "dsm.tif"), 10 + hgt + rng.normal(0, 0.15, hgt.shape).astype("float32"), tiled=True)
    write_dtm_4326(os.path.join(out, "dtm.tif"), 400, lambda x, y: np.full_like(x, 10.0))
    write_footprints(out, feats)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--dataset", default="all", choices=["stepped", "courtyard", "bench", "all"])
    a = ap.parse_args()
    for name, fn in (("stepped", stepped), ("courtyard", courtyard), ("bench", bench)):
        if a.dataset in (name, "all"):
            d = os.path.join(a.out, name); os.makedirs(d, exist_ok=True); fn(d); print("wrote", d)
