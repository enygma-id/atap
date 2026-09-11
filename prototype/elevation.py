# SPDX-License-Identifier: AGPL-3.0-only
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "rasterio>=1.3",
#   "geopandas>=0.14",
#   "shapely>=2.0",
#   "numpy>=1.24",
#   "scipy>=1.10",
#   "pyproj>=3.5",
# ]
# ///
# -----------------------------------------------------------------------------
# elevation.py — ATAP Elevation (hierarchical GIS-native building mass)
#
# Acuan: spesifikasi ATAP Elevation (kontrak implementasi; nomor § merujuk ke sana).
#
#   footprint (authoritative) + DSM + DTM (WAJIB)
#     -> DSM = master analysis grid, DTM di-warp/resample ke grid DSM
#     -> nDSM = DSM - DTM
#     -> 1D height clustering + merge center berdekatan          (logika asli)
#     -> footprint-aware level merging (min_footprint_change_ratio) (logika asli)
#     -> cumulative mask per level
#     -> morphology + pengisian HANYA hole kecil (courtyard dipertahankan)
#     -> polygonize -> regularize -> containment guard
#     -> hirarki eksplisit (object_id, part_id, parent_part_id, part_level)
#     -> interval vertikal non-overlap (base/top/part_height AGL)
#     -> ground placement (ground/base/top elevation)
#     -> metrik + evidence raster + validasi invariant
#     -> GeoJSON FeatureCollection EPSG:4326 + metadata (atomic write)
#
# CHANGES from the preceding elevation prototype:
#   - DTM WAJIB. Input tanpa DTM gagal eksplisit (spec §3.1).
#   - DSM menjadi grid analisis utama (sebelumnya DTM). DTM yang di-resample
#     (bilinear) ke grid DSM, sehingga detail DSM tidak hilang.
#   - ID bangunan stabil: GeoJSON Feature.id, atau properti via --id-field.
#     Tidak ada lagi `parent_id` dari row index. Bila tidak ada -> gagal.
#   - Output per part: object_id, part_id, parent_part_id, part_level,
#     base/top/part_height AGL (interval non-overlap, child tidak diekstrusi
#     dari 0), ground/base/top elevation, area, perimeter, dimensi, orientasi,
#     volume, evidence raster, decomposition_reason.
#   - Field lama building_height_m / roof_elevation_m / value / parent_id /
#     source / is_round dihapus (lihat CATATAN MIGRASI di bawah).
#   - binary_fill_holes tanpa syarat diganti pengisian hole berbatas luas
#     (max_fill_hole_area_m2); courtyard/atrium tetap jadi interior ring, juga
#     setelah regularisasi.
#   - Containment guard: part turunan selalu di-intersect dengan parent-nya.
#   - embed_ground_z dihapus (Z renderer tidak boleh masuk canonical geometry).
#   - Validasi invariant sebelum menulis + atomic write.
#   - Logika inti (kmeans_1d, merge_close_centers, footprint-aware merge,
#     orthogonalize, circularity) dipertahankan.
#
# PERFORMA / RESOURCE:
#   - kmeans_1d memakai Lloyd 1D eksak berbasis data terurut + prefix sum
#     (inisialisasi quantile & hasil sama dengan versi matriks jarak n×k,
#     ~12-50x lebih cepat pada fungsi ini).
#   - Bangunan diproses paralel lintas core (ProcessPoolExecutor, parameter
#     `workers`); tiap worker membuka DSM/DTM sendiri. Output tetap
#     deterministik (urutan input).
#   - Bangunan diurutkan per tile DSM agar block cache GDAL terpakai ulang;
#     GDAL_CACHEMAX diatur lewat `gdal_cache_mb` (dibagi rata ke worker).
#   - Parameter GPU (use_gpu, gpu_min_pixels) dihapus: tidak pernah aktif dan
#     hotspot yang ada lebih efektif dioptimasi di CPU.
#
# CATATAN MIGRASI viewer (deck.gl / pydeck):
#   posisi dasar render : base_height_agl_m (local plane) atau base_elevation_m
#   tebal ekstrusi      : part_height_m   (JANGAN top_elevation_m)
#   grouping bangunan   : object_id
#
# Dipakai dua cara:
#   1. CLI:     python elevation.py --input-geojson p.geojson --dtm dtm.tif \
#                      --dsm dsm.tif --output out.geojson [--id-field id] --regularize
#   2. Library: from elevation import run_elevation  (dipanggil GUI / service)
# -----------------------------------------------------------------------------

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import platform
import sys
import tempfile
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field, replace, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform
from rasterio.features import geometry_mask, shapes as raster_shapes
from rasterio.enums import Resampling
from rasterio.errors import WindowError
from rasterio.warp import transform_bounds

import shapely
from shapely.geometry import shape as shp_shape, mapping, Polygon, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.affinity import rotate
from shapely.ops import unary_union
from pyproj import CRS, Transformer
from scipy import ndimage as ndi

warnings.filterwarnings("ignore", category=RuntimeWarning)

ENGINE_VERSION = "0.2.0"
PROFILE_VERSION = "0.6"
ANALYSIS_GRID_SOURCE = "DSM"
DTM_RESAMPLING = "bilinear"


# =============================================================================
#                                   ERRORS
# =============================================================================
class AtapError(RuntimeError):
    """Kegagalan eksplisit (fail-fast) sesuai spec §39."""


class AtapInputError(AtapError):
    """Input tidak memenuhi kontrak (DTM/DSM/footprint/ID/CRS)."""


class AtapValidationError(AtapError):
    """Output melanggar invariant spec §30. File tidak ditulis."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        head = "\n  - ".join(problems[:25])
        more = f"\n  ... dan {len(problems) - 25} masalah lain" if len(problems) > 25 else ""
        super().__init__(f"Validasi output ATAP gagal ({len(problems)} masalah):\n  - {head}{more}")


# =============================================================================
#                                  CONFIG  (DEFAULT)
# =============================================================================
@dataclass
class Config:
    # ---- Path input / output ----
    input_geojson: str = "../data/persil_bangunan.geojson"
    dtm_path: str = "../data/dtm_warped.tif"      # WAJIB
    dsm_path: str = "../data/dsm_warped.tif"      # WAJIB, master analysis grid
    output_geojson: str = "../output/LOD1.geojson"

    # ---- ID bangunan (spec §13.1) ----
    # Prioritas: 1) GeoJSON Feature.id  2) properti ini  3) gagal.
    id_field: Optional[str] = None

    # ---- CRS ----
    working_crs: str = "EPSG:32750"   # CRS kerja metrik (UTM 50S)
    output_crs: str = "EPSG:4326"     # canonical output WAJIB EPSG:4326

    # ---- Threshold tinggi & luas ----
    height_diff_threshold_m: float = 3.0
    min_subregion_area_m2: float = 12.0
    min_building_height_m: float = 2.0

    # ---- Ground (placement reference) dari DTM ----
    base_elevation_stat: str = "min"       # 'min' | 'mean' | 'median'
    ground_source_type: str = "DTM"        # 'DTM' | 'DEM' (kualitas referensi terrain)
    vertical_datum: Optional[str] = None   # mis. "EGM2008" bila diketahui

    # ---- Segmentasi tinggi ----
    max_height_classes: int = 4
    # Level lebih tinggi jadi massa baru HANYA jika footprint kumulatifnya
    # menyusut >= rasio ini dibanding level di bawahnya (spec §10).
    min_footprint_change_ratio: float = 0.25

    # ---- Mask / hole / hirarki ----
    morph_closing_iters: int = 3
    # Hole <= luas ini diisi (noise raster); hole lebih besar dipertahankan
    # sebagai interior ring (courtyard/atrium/void) — spec §14.
    max_fill_hole_area_m2: float = 4.0
    # Skor containment minimum (luas irisan child∩parent / luas child) agar
    # sebuah part di level bawah sah jadi parent — spec §12, §36.
    parent_min_containment_ratio: float = 0.5

    # ---- Regularisasi bentuk ----
    regularize: bool = False
    simplify_tolerance_m: float = 0.9
    rectangular_ratio: float = 0.4
    circularity_threshold: float = 0.8

    # ---- Properti original yang ikut dibawa (atribut sumber) ----
    keep_properties: list[str] = field(
        default_factory=lambda: ["id", "NAMOBJ", "REMARK", "floor_est"])

    # ---- Eksekusi / resource ----
    # Jumlah proses paralel (per bangunan). 0 = otomatis (jumlah core - 1).
    # 1 = tanpa paralel (satu proses; cocok untuk debugging / dataset kecil).
    workers: int = 0
    # Total cache blok GDAL (MB) untuk seluruh job, dibagi rata ke worker.
    gdal_cache_mb: int = 512

    # ---- Pembulatan ----
    round_digits: int = 2
    coord_digits: int = 8   # desimal koordinat lon/lat output (~1 mm)


CONFIG = Config()

# Field canonical — atribut sumber yang bentrok diberi prefix "src_".
CANONICAL_KEYS = (
    "object_id", "part_id", "parent_part_id", "part_level",
    "ground_elevation_m", "base_height_agl_m", "top_height_agl_m", "part_height_m",
    "base_elevation_m", "top_elevation_m", "area_m2", "perimeter_m",
    "oriented_length_m", "oriented_width_m", "dimension_method", "orientation_deg",
    "volume_m3", "delta_z_m", "expected_pixel_count", "valid_pixel_count",
    "support_pixel_count", "valid_coverage_ratio", "decomposition_reason",
    "parent_containment_ratio", "interior_ring_count", "geometry_method",
)


# =============================================================================
#                          GEOMETRI: helper umum
# =============================================================================
def polygonal_parts(geom) -> list[Polygon]:
    """Perbaiki geometri & ambil hanya komponen Polygon dengan luas > 0."""
    if geom is None or geom.is_empty:
        return []
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    out: list[Polygon] = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if g.is_empty:
            continue
        if isinstance(g, Polygon):
            if g.area > 0:
                out.append(g)
        elif hasattr(g, "geoms"):
            stack.extend(g.geoms)
    return out


def as_polygonal(parts: list[Polygon]):
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts)


def reproject_geom(geom, transformer: Transformer):
    def _f(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])
    return shapely.transform(geom, _f)


def is_metric_projected(crs: CRS) -> bool:
    if not crs.is_projected:
        return False
    units = {(a.unit_name or "").lower() for a in crs.axis_info[:2]}
    return bool(units) and all(u in ("metre", "meter", "m") for u in units)


# =============================================================================
#                   INPUT: footprint + stable object ID  (spec §7, §13)
# =============================================================================
def _normalize_id(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        if not math.isfinite(float(v)):
            return None
        return str(int(v)) if float(v).is_integer() else repr(float(v))
    s = str(v).strip()
    return s or None


def _jsonable(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (str, int, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


def _crs_from_geojson(doc: dict) -> tuple[CRS, str]:
    """CRS GeoJSON: member legacy "crs" bila ada, selain itu RFC 7946 = WGS84."""
    c = doc.get("crs")
    if c:
        name = (c.get("properties") or {}).get("name") if isinstance(c, dict) else None
        if not name:
            raise AtapInputError("Member 'crs' GeoJSON ada tetapi tidak bisa dibaca.")
        try:
            return CRS.from_user_input(name), name
        except Exception as e:
            raise AtapInputError(f"CRS footprint '{name}' tidak dikenali: {e}") from e
    return CRS.from_epsg(4326), "EPSG:4326 (RFC 7946 default)"


def load_footprints(cfg: Config, work_crs: CRS, log) -> dict:
    """
    Baca footprint + tentukan object_id stabil.
    Return dict: records=[(object_id, geom_work, src_props)], id_source, crs, count.
    """
    path = cfg.input_geojson
    if not path or not os.path.isfile(path):
        raise AtapInputError(f"File footprint tidak ditemukan: {path!r}")

    ext = os.path.splitext(path)[1].lower()
    raw: list[tuple[Any, Any, dict]] = []   # (feature_id, geometry, properties)

    if ext in (".geojson", ".json"):
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("type") == "Feature":
            feats = [doc]
        elif doc.get("type") == "FeatureCollection":
            feats = doc.get("features") or []
        else:
            raise AtapInputError("Footprint harus GeoJSON Feature/FeatureCollection.")
        src_crs, src_crs_label = _crs_from_geojson(doc)
        for f in feats:
            g = f.get("geometry")
            geom = shp_shape(g) if g else None
            raw.append((f.get("id"), geom, dict(f.get("properties") or {})))
    else:
        import geopandas as gpd   # format lain (GPKG/SHP) — hanya via --id-field
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise AtapInputError(f"CRS footprint tidak dapat ditentukan: {path}")
        src_crs, src_crs_label = CRS.from_user_input(gdf.crs), gdf.crs.to_string()
        cols = [c for c in gdf.columns if c != "geometry"]
        for row in gdf.itertuples(index=False):
            props = {c: getattr(row, c) for c in cols}
            raw.append((None, row.geometry, props))

    n = len(raw)
    if n == 0:
        raise AtapInputError("Footprint kosong (0 feature).")

    # ---- Pilih sumber ID (level dataset) ----
    fids = [_normalize_id(fid) for fid, _, _ in raw]
    if all(fid is not None for fid in fids):
        id_source = {"mode": "feature_id", "field": None}
        oids = fids
    elif cfg.id_field:
        oids = [_normalize_id(p.get(cfg.id_field)) for _, _, p in raw]
        missing = sum(1 for o in oids if o is None)
        if missing:
            raise AtapInputError(
                f"{missing}/{n} feature tidak punya nilai properti '{cfg.id_field}' "
                f"(dan tidak semua punya Feature.id). ID stabil wajib (spec §13.1).")
        id_source = {"mode": "property", "field": cfg.id_field}
    else:
        n_fid = sum(1 for f in fids if f is not None)
        raise AtapInputError(
            f"Stable building ID tidak tersedia: hanya {n_fid}/{n} feature punya "
            f"GeoJSON Feature.id dan --id-field tidak diberikan. Row index tidak "
            f"boleh dipakai sebagai ID (spec §13.1).")

    seen: dict[str, int] = {}
    dups = set()
    for o in oids:
        seen[o] = seen.get(o, 0) + 1
        if seen[o] > 1:
            dups.add(o)
    if dups:
        sample = ", ".join(sorted(dups)[:10])
        raise AtapInputError(f"object_id duplikat ({len(dups)}): {sample} — part_id akan bentrok.")

    to_work = Transformer.from_crs(src_crs, work_crs, always_xy=True)
    records, invalid = [], []
    for oid, (_, geom, props) in zip(oids, raw):
        if geom is None or geom.is_empty:
            invalid.append(oid)
            records.append((oid, None, props))
            continue
        g = as_polygonal(polygonal_parts(reproject_geom(geom, to_work)))
        if g is None:
            invalid.append(oid)
        records.append((oid, g, props))
    if invalid:
        log(f"[warn] {len(invalid)} footprint kosong/non-polygon -> dilewati.")

    return {"records": records, "id_source": id_source,
            "crs": src_crs_label, "feature_count": n}


# =============================================================================
#                 RASTER: DSM master grid + DTM aligned  (spec §3.2)
# =============================================================================
def _vrt_nodata(src) -> float:
    return float(src.nodata) if src.nodata is not None else float("nan")


@dataclass
class AnalysisGrid:
    dsm_src: Any
    dtm_src: Any
    dsm_reader: Any          # dsm_src langsung (tanpa resample) atau WarpedVRT
    dtm_reader: Any          # WarpedVRT DTM -> grid DSM
    transform: Any
    width: int
    height: int
    res_x: float
    res_y: float
    dsm_warped: bool

    def close(self):
        for h in (self.dtm_reader, self.dsm_reader, self.dtm_src, self.dsm_src):
            try:
                if h is not None:
                    h.close()
            except Exception:
                pass


def open_dsm_master_grid(cfg: Config, work_crs: CRS):
    if not cfg.dsm_path or not os.path.isfile(cfg.dsm_path):
        raise AtapInputError(f"DSM wajib dan tidak ditemukan: {cfg.dsm_path!r}")
    dsm_src = rasterio.open(cfg.dsm_path)
    if dsm_src.crs is None:
        dsm_src.close()
        raise AtapInputError(f"CRS DSM tidak dapat ditentukan: {cfg.dsm_path}")

    tf = dsm_src.transform
    same_crs = CRS.from_user_input(dsm_src.crs) == work_crs
    axis_aligned = tf.b == 0 and tf.d == 0
    if same_crs and axis_aligned:
        # DSM sudah di CRS kerja -> dipakai apa adanya (tanpa resample).
        reader, warped = dsm_src, False
    else:
        # Reproyeksi ke CRS kerja dengan resolusi default dari DSM itu sendiri.
        reader = WarpedVRT(dsm_src, crs=work_crs, resampling=Resampling.bilinear,
                           nodata=_vrt_nodata(dsm_src), dtype="float64")
        warped = True
    return dsm_src, reader, warped


def align_dtm_to_dsm(cfg: Config, work_crs: CRS, dsm_src, dsm_reader, dsm_warped) -> AnalysisGrid:
    if not cfg.dtm_path:
        raise AtapInputError("DTM wajib untuk produksi ATAP (spec §3.1) — --dtm tidak diberikan.")
    if not os.path.isfile(cfg.dtm_path):
        raise AtapInputError(f"DTM wajib dan tidak ditemukan: {cfg.dtm_path}")
    dtm_src = rasterio.open(cfg.dtm_path)
    if dtm_src.crs is None:
        dtm_src.close()
        raise AtapInputError(f"CRS DTM tidak dapat ditentukan: {cfg.dtm_path}")

    tf = dsm_reader.transform
    w, h = dsm_reader.width, dsm_reader.height

    # Cek overlap DTM vs DSM (di CRS kerja) sebelum warp.
    dl, db, dr, dt = transform_bounds(dtm_src.crs, work_crs, *dtm_src.bounds, densify_pts=21)
    xs = (tf.c, tf.c + tf.a * w)
    ys = (tf.f, tf.f + tf.e * h)
    gl, gr = min(xs), max(xs)
    gb, gt = min(ys), max(ys)
    if dr <= gl or dl >= gr or dt <= gb or db >= gt:
        dtm_src.close()
        raise AtapInputError("DTM dan DSM tidak beririsan — tidak dapat di-align.")

    try:
        dtm_reader = WarpedVRT(dtm_src, crs=work_crs, transform=tf, width=w, height=h,
                               resampling=Resampling.bilinear,
                               nodata=_vrt_nodata(dtm_src), dtype="float64")
    except Exception as e:
        dtm_src.close()
        raise AtapInputError(f"DTM tidak dapat di-warp ke grid DSM: {e}") from e

    return AnalysisGrid(dsm_src=dsm_src, dtm_src=dtm_src, dsm_reader=dsm_reader,
                        dtm_reader=dtm_reader, transform=tf, width=w, height=h,
                        res_x=abs(tf.a), res_y=abs(tf.e), dsm_warped=dsm_warped)


def _read_float(reader, window) -> np.ndarray:
    a = reader.read(1, window=window, masked=True).astype("float64")
    arr = np.ma.filled(a, np.nan)
    nd = reader.nodata
    if nd is not None and math.isfinite(nd):
        arr[arr == nd] = np.nan
    return arr


def read_building_window(geom, grid: AnalysisGrid, pad_px: int):
    minx, miny, maxx, maxy = geom.bounds
    win = from_bounds(minx, miny, maxx, maxy, transform=grid.transform)
    win = win.round_offsets().round_lengths()
    win = Window(win.col_off - pad_px, win.row_off - pad_px,
                 win.width + 2 * pad_px, win.height + 2 * pad_px)
    try:
        win = win.intersection(Window(0, 0, grid.width, grid.height))
    except WindowError:
        return None
    if win.width <= 0 or win.height <= 0:
        return None
    dsm = _read_float(grid.dsm_reader, win)
    dtm = _read_float(grid.dtm_reader, win)
    return dtm, dsm, window_transform(win, grid.transform)


# =============================================================================
#                 HEIGHT: nDSM, clustering 1D, merge  (logika asli)
# =============================================================================
def compute_ndsm(dsm: np.ndarray, dtm: np.ndarray) -> np.ndarray:
    return dsm - dtm


def kmeans_1d(values: np.ndarray, k: int, iters: int = 60):
    """
    K-means 1D (Lloyd) dengan inisialisasi quantile — deterministik.

    Versi eksak untuk data 1 dimensi: penugasan ke center terdekat sama dengan
    memotong data terurut di titik tengah antar-center, sehingga rata-rata tiap
    cluster dihitung dari prefix sum. Kompleksitas O(n log n) sekali (sorting)
    + O(k log n) per iterasi, tanpa matriks jarak n×k.
    Return (labels, centers) — labels mengindeks `centers` (urut naik).
    """
    raw = np.asarray(values, dtype="float64").reshape(-1)
    n = int(raw.size)
    if n == 0:
        return None, None
    v = np.sort(raw)
    uniq = int(np.count_nonzero(np.diff(v))) + 1
    k = max(1, min(int(k), uniq))
    centers = np.unique(np.quantile(v, np.linspace(0.0, 1.0, k)))
    csum = np.concatenate(([0.0], np.cumsum(v)))
    for _ in range(iters):
        mids = (centers[:-1] + centers[1:]) / 2.0
        bounds = np.concatenate(([0], np.searchsorted(v, mids, side="right"), [n]))
        cnt = np.diff(bounds)
        sums = csum[bounds[1:]] - csum[bounds[:-1]]
        new = np.where(cnt > 0, sums / np.maximum(cnt, 1), centers)
        converged = bool(np.all(np.abs(new - centers) < 1e-6))
        centers = np.sort(new)
        if converged:
            break
    mids = (centers[:-1] + centers[1:]) / 2.0
    labels = np.searchsorted(mids, raw, side="left").astype("int64")
    return labels, centers


def merge_close_centers(values: np.ndarray, labels: np.ndarray, centers: np.ndarray,
                        threshold: float):
    order = np.argsort(centers)
    sorted_c = centers[order]
    merged = [[sorted_c[0]]]
    for c in sorted_c[1:]:
        prev = merged[-1][-1]
        if c - prev < threshold:
            merged[-1].append(c)
        else:
            merged.append([c])
    merged_centers = np.array([np.mean(g) for g in merged], dtype="float64")
    d = np.abs(values[:, None] - merged_centers[None, :])
    new_labels = np.argmin(d, axis=1)
    return new_labels, merged_centers


def footprint_aware_level_merge(full_lbl: np.ndarray, sorted_idx: np.ndarray,
                                sorted_centers: np.ndarray, min_change: float):
    """
    Logika asli: level atas jadi massa baru hanya bila footprint kumulatif-nya
    menyusut >= min_change dibanding level sebelumnya. Bila tidak, tinggi level
    berjalan dinaikkan ke center kelas berikutnya.
    Return (level_classes, level_heights) — level_heights = tinggi kumulatif.
    """
    cls_px = np.array([int((full_lbl == c).sum()) for c in sorted_idx], dtype="float64")
    cum_px = np.cumsum(cls_px[::-1])[::-1]
    level_classes = [0]
    level_heights = [float(sorted_centers[0])]
    ref_px = cum_px[0]
    for j in range(1, sorted_centers.size):
        shrink = 1.0 - (cum_px[j] / ref_px) if ref_px > 0 else 1.0
        if shrink >= min_change:
            level_classes.append(j)
            level_heights.append(float(sorted_centers[j]))
            ref_px = cum_px[j]
        else:
            level_heights[-1] = float(sorted_centers[j])
    return level_classes, level_heights


# =============================================================================
#               POLYGON: cleanup, hole, polygonize, regularize, containment
# =============================================================================
def circularity(poly: Polygon) -> float:
    p = poly.length
    if p <= 0:
        return 0.0
    return float(4.0 * math.pi * poly.area / (p * p))


def orthogonalize(poly: Polygon, angle_tol_deg: float = 18.0) -> Polygon:
    try:
        mrr = poly.minimum_rotated_rectangle
        mc = list(mrr.exterior.coords)
        edges = [(mc[i], mc[i + 1]) for i in range(len(mc) - 1)]
        longest = max(edges, key=lambda e: (e[1][0] - e[0][0]) ** 2 + (e[1][1] - e[0][1]) ** 2)
        theta = math.degrees(math.atan2(longest[1][1] - longest[0][1],
                                        longest[1][0] - longest[0][0]))
        cen = poly.centroid
        rp = rotate(poly, -theta, origin=cen, use_radians=False)
        coords = list(rp.exterior.coords)[:-1]
        n = len(coords)
        if n < 4:
            return poly

        lines = []
        for i in range(n):
            x0, y0 = coords[i]
            x1, y1 = coords[(i + 1) % n]
            a = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
            dh = min(a, 180.0 - a)
            dv = abs(a - 90.0)
            if dh <= dv:
                lines.append(("h", (y0 + y1) / 2.0))
            else:
                lines.append(("v", (x0 + x1) / 2.0))

        merged = []
        i = 0
        while i < len(lines):
            o, c = lines[i]
            cs = [c]
            j = i + 1
            while j < len(lines) and lines[j][0] == o:
                cs.append(lines[j][1]); j += 1
            merged.append((o, float(np.mean(cs))))
            i = j
        if len(merged) >= 2 and merged[0][0] == merged[-1][0]:
            o, c0 = merged[0]
            _, c1 = merged.pop()
            merged[0] = (o, (c0 + c1) / 2.0)

        m = len(merged)
        if m < 4 or m % 2 != 0:
            return mrr

        pts = []
        for i in range(m):
            o1, c1 = merged[i]
            o2, c2 = merged[(i + 1) % m]
            if o1 == o2:
                return mrr
            if o1 == "h":
                pts.append((c2, c1))
            else:
                pts.append((c1, c2))
        new = Polygon(pts)
        new = rotate(new, theta, origin=cen, use_radians=False)
        new = new.buffer(0)
        if new.is_empty or not new.is_valid or new.area <= 0:
            return poly
        return new
    except Exception:
        return poly


def cleanup_mask(mask: np.ndarray, iters: int) -> np.ndarray:
    if iters > 0 and mask.any():
        mask = ndi.binary_closing(mask, iterations=iters) | mask
    return mask


def fill_small_holes(mask: np.ndarray, max_area_m2: float, pixel_area_m2: float) -> np.ndarray:
    """Isi hanya hole dengan luas <= max_area_m2; hole besar dipertahankan (spec §14)."""
    if max_area_m2 <= 0 or not mask.any():
        return mask
    holes = ndi.binary_fill_holes(mask) & ~mask
    if not holes.any():
        return mask
    lbl, n = ndi.label(holes)
    sizes = np.asarray(ndi.sum(holes, lbl, index=np.arange(1, n + 1)), dtype="float64")
    small = np.zeros(n + 1, dtype=bool)
    small[1:] = sizes * pixel_area_m2 <= max_area_m2
    return mask | small[lbl]


def polygonize_mask(mask: np.ndarray, transform) -> list[Polygon]:
    if not mask.any():
        return []
    out: list[Polygon] = []
    for geom, val in raster_shapes(mask.astype("uint8"), mask=mask,
                                   transform=transform, connectivity=8):
        if val != 1:
            continue
        out.extend(polygonal_parts(shp_shape(geom)))
    return out


def regularize_polygon(poly: Polygon, cfg: Config) -> tuple[Optional[Any], str]:
    """
    Regularisasi shell (logika asli) lalu kurangi kembali interior hole yang
    bermakna (> max_fill_hole_area_m2) agar courtyard tidak hilang (spec §15).
    """
    shell = Polygon(poly.exterior)
    holes = [Polygon(r) for r in poly.interiors]
    holes = [h for h in holes if h.area > cfg.max_fill_hole_area_m2]

    simp = shell.simplify(cfg.simplify_tolerance_m, preserve_topology=True)
    if simp.is_empty or simp.area <= 0:
        simp = shell

    method = "simplified"
    out_shell = simp
    if cfg.regularize:
        if circularity(simp) >= cfg.circularity_threshold:
            try:
                out_shell, method = shapely.minimum_bounding_circle(simp), "minimum_bounding_circle"
            except Exception:
                pass
        else:
            try:
                mrr = simp.minimum_rotated_rectangle
                if mrr.area > 0 and (simp.area / mrr.area) >= cfg.rectangular_ratio:
                    out_shell, method = mrr, "minimum_rotated_rectangle"
                else:
                    out_shell, method = orthogonalize(simp), "orthogonalized"
            except Exception:
                out_shell, method = orthogonalize(simp), "orthogonalized"

    geom = out_shell
    if holes:
        hs = [h.simplify(cfg.simplify_tolerance_m, preserve_topology=True) for h in holes]
        geom = out_shell.difference(unary_union(hs))
    return as_polygonal(polygonal_parts(geom)), method


def enforce_containment(geom, parent_geom):
    """child = child ∩ authoritative parent (spec §7)."""
    return as_polygonal(polygonal_parts(geom.intersection(parent_geom)))


# =============================================================================
#                                  METRICS
# =============================================================================
def geometry_metrics(geom) -> dict:
    parts = polygonal_parts(geom)
    rings = sum(len(p.interiors) for p in parts)
    length = width = 0.0
    orientation = 0.0
    mrr = geom.minimum_rotated_rectangle
    if isinstance(mrr, Polygon) and not mrr.is_empty:
        c = list(mrr.exterior.coords)
        e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
        e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
        l0, l1 = math.hypot(*e0), math.hypot(*e1)
        long_edge = e0 if l0 >= l1 else e1
        length, width = max(l0, l1), min(l0, l1)
        # azimut sisi terpanjang, searah jarum jam dari grid-north CRS kerja, [0,180)
        orientation = math.degrees(math.atan2(long_edge[0], long_edge[1])) % 180.0
    return {"area": float(geom.area), "perimeter": float(geom.length),
            "length": length, "width": width, "orientation": orientation,
            "interior_rings": rings}


def raster_evidence(geom, wt, shape, valid: np.ndarray, support: np.ndarray) -> dict:
    m = geometry_mask([mapping(geom)], out_shape=shape, transform=wt, invert=True)
    exp = int(m.sum())
    val = int((m & valid).sum())
    sup = int((m & support).sum())
    return {"expected": exp, "valid": val, "support": sup,
            "coverage": (val / exp) if exp > 0 else 0.0}


def configured_ground_stat(arr: np.ndarray, how: str) -> float:
    if how == "mean":
        return float(np.nanmean(arr))
    if how == "median":
        return float(np.nanmedian(arr))
    return float(np.nanmin(arr))


# =============================================================================
#                   PER BANGUNAN: dekomposisi hirarkis  (spec §32)
# =============================================================================
@dataclass
class _Part:
    geom: Any
    det_level: int                 # indeks level hasil deteksi (0 = root)
    part_level: int                # kedalaman hirarki = parent.part_level + 1
    parent: Optional[int]          # indeks _Part parent (None untuk root)
    top_agl: float                 # sudah dibulatkan
    reason: str
    method: str
    containment: Optional[float] = None
    support: Optional[np.ndarray] = None


def process_parcel(root_geom, dtm, dsm, wt, cfg: Config) -> dict:
    rd = cfg.round_digits
    shape = dsm.shape
    inside = geometry_mask([mapping(root_geom)], out_shape=shape, transform=wt, invert=True)
    valid = inside & np.isfinite(dsm) & np.isfinite(dtm)
    if int(valid.sum()) < 1:
        return {"status": "skipped", "reason": "NO_VALID_DSM_DTM_PIXELS"}

    ndsm = compute_ndsm(dsm, dtm)
    ground = round(configured_ground_stat(dtm[valid], cfg.base_elevation_stat), rd)

    bld = valid & (ndsm >= cfg.min_building_height_m)
    heights = ndsm[bld]
    pixel_area = abs(wt.a * wt.e)

    def single(h: float, reason: str) -> dict:
        root = _Part(geom=root_geom, det_level=0, part_level=0, parent=None,
                     top_agl=round(max(h, 0.0), rd), reason=reason,
                     method="authoritative_footprint", support=bld)
        return {"status": "ok", "ground": ground, "parts": [root],
                "valid": valid, "shape": shape}

    if heights.size < 3:
        return single(float(np.nanmean(ndsm[valid])), "SINGLE_MASS_INSUFFICIENT_BUILDING_PIXELS")

    p_lo, p_hi = np.nanpercentile(heights, [5, 95])
    if float(p_hi - p_lo) < cfg.height_diff_threshold_m:
        return single(float(np.nanmean(heights)), "SINGLE_MASS_UNIFORM_HEIGHT")

    labels, centers = kmeans_1d(heights, cfg.max_height_classes)
    if labels is None:
        return single(float(np.nanmean(heights)), "SINGLE_MASS_UNIFORM_HEIGHT")

    labels, mcenters = merge_close_centers(heights, labels, centers, cfg.height_diff_threshold_m)
    if mcenters.size <= 1:
        return single(float(mcenters[0]), "SINGLE_MASS_SINGLE_HEIGHT_CLASS")

    full_lbl = np.full(shape, -1, dtype="int64")
    full_lbl[bld] = labels
    sorted_idx = np.argsort(mcenters)
    sorted_centers = mcenters[sorted_idx]

    level_classes, level_heights = footprint_aware_level_merge(
        full_lbl, sorted_idx, sorted_centers, cfg.min_footprint_change_ratio)
    level_h = [round(h, rd) for h in level_heights]

    if len(level_classes) == 1:
        return single(level_heights[0], "SINGLE_MASS_NO_FOOTPRINT_CHANGE")

    # ---- Root = footprint authoritative ----
    parts: list[_Part] = [_Part(geom=root_geom, det_level=0, part_level=0, parent=None,
                                top_agl=level_h[0], reason="AUTHORITATIVE_ROOT",
                                method="authoritative_footprint", support=bld)]
    min_keep = cfg.min_subregion_area_m2 * 0.5
    prev_mask = inside

    for lvl in range(1, len(level_classes)):
        raw_mask = np.isin(full_lbl, sorted_idx[level_classes[lvl]:])   # cumulative
        m = cleanup_mask(raw_mask, cfg.morph_closing_iters)
        m = fill_small_holes(m, cfg.max_fill_hole_area_m2, pixel_area)
        m &= prev_mask                    # nesting raster: level atas ⊆ level bawah
        prev_mask = m

        cands = []
        for poly in polygonize_mask(m, wt):
            if poly.area < cfg.min_subregion_area_m2:
                continue
            reg, method = regularize_polygon(poly, cfg)
            if reg is None or reg.area < min_keep:
                continue
            reg = enforce_containment(reg, root_geom)
            if reg is None or reg.area < min_keep:
                continue
            cands.append((reg, method))
        cands.sort(key=lambda t: t[0].area, reverse=True)

        accepted_this_level: list[Any] = []
        for geom, method in cands:
            # ---- Parent eksplisit: level lvl-1, fallback ke ancestor, root terakhir ----
            chosen, score = 0, 1.0
            for lv in range(lvl - 1, -1, -1):
                best_i, best_s = None, 0.0
                for i, p in enumerate(parts):
                    if p.det_level != lv:
                        continue
                    s = geom.intersection(p.geom).area / geom.area if geom.area > 0 else 0.0
                    if s > best_s or (s == best_s and best_i is not None
                                      and p.geom.area > parts[best_i].geom.area):
                        best_i, best_s = i, s
                need = cfg.parent_min_containment_ratio if lv > 0 else 0.0
                if best_i is not None and best_s >= need and best_s > 0:
                    chosen, score = best_i, best_s
                    break
            parent = parts[chosen]

            g = enforce_containment(geom, parent.geom)
            if g is None:
                continue
            # Fallback ke ancestor: buang irisan dengan part level antara supaya
            # interval vertikal tidak overlap.
            between = [p.geom for p in parts if parent.det_level < p.det_level < lvl]
            # Hindari overlap dengan sibling di level yang sama (hasil regularisasi).
            blockers = between + accepted_this_level
            if blockers:
                g = as_polygonal(polygonal_parts(g.difference(unary_union(blockers))))
                if g is None:
                    continue

            if level_h[lvl] - parent.top_agl <= 0:
                continue
            reason = ("HEIGHT_AND_FOOTPRINT_CHANGE" if parent.det_level == lvl - 1
                      else "HEIGHT_AND_FOOTPRINT_CHANGE_ANCESTOR_FALLBACK")
            for piece in polygonal_parts(g):
                if piece.area < min_keep:
                    continue
                parts.append(_Part(geom=piece, det_level=lvl,
                                   part_level=parent.part_level + 1, parent=chosen,
                                   top_agl=level_h[lvl], reason=reason, method=method,
                                   containment=round(float(score), 4), support=raw_mask))
                accepted_this_level.append(piece)

    if len(parts) == 1:
        parts[0].reason = "SINGLE_MASS_DERIVED_PARTS_FILTERED"

    return {"status": "ok", "ground": ground, "parts": parts, "valid": valid, "shape": shape}


# =============================================================================
#            HIERARCHY: ID, interval vertikal, properti  (spec §13, §33-34)
# =============================================================================
def build_part_records(object_id: str, result: dict, wt, src_props: dict, cfg: Config) -> list[dict]:
    rd = cfg.round_digits
    parts: list[_Part] = result["parts"]
    ground = result["ground"]
    ids = [f"{object_id}-P{i:02d}" for i in range(len(parts))]   # root = P00

    recs = []
    for i, p in enumerate(parts):
        parent = parts[p.parent] if p.parent is not None else None
        base = parent.top_agl if parent is not None else 0.0
        top = p.top_agl
        height = round(top - base, rd)
        met = geometry_metrics(p.geom)
        ev = raster_evidence(p.geom, wt, result["shape"], result["valid"], p.support)
        area = round(met["area"], rd)

        props = {
            "object_id": object_id,
            "part_id": ids[i],
            "parent_part_id": ids[p.parent] if p.parent is not None else None,
            "part_level": int(p.part_level),

            "ground_elevation_m": ground,

            "base_height_agl_m": round(base, rd),
            "top_height_agl_m": round(top, rd),
            "part_height_m": height,

            "base_elevation_m": round(ground + base, rd),
            "top_elevation_m": round(ground + top, rd),

            "area_m2": area,
            "perimeter_m": round(met["perimeter"], rd),
            "oriented_length_m": round(met["length"], rd),
            "oriented_width_m": round(met["width"], rd),
            "dimension_method": "minimum_rotated_rectangle",
            "orientation_deg": round(met["orientation"], rd),

            "volume_m3": round(area * height, rd),   # net area (hole dikurangi)

            "delta_z_m": height,

            "expected_pixel_count": ev["expected"],
            "valid_pixel_count": ev["valid"],
            "support_pixel_count": ev["support"],
            "valid_coverage_ratio": round(ev["coverage"], 4),

            "decomposition_reason": p.reason,
            "parent_containment_ratio": p.containment,
            "interior_ring_count": met["interior_rings"],
            "geometry_method": p.method,
        }
        for k, v in src_props.items():
            key = f"src_{k}" if k in CANONICAL_KEYS else k
            props[key] = _jsonable(v)
        recs.append({"id": ids[i], "properties": props, "geom_work": p.geom})
    return recs


# =============================================================================
#                          VALIDATION  (spec §30-31)
# =============================================================================
def _tol(cfg: Config) -> float:
    return max(10.0 ** (-cfg.round_digits), 1e-6) * 1.0001


def validate_ids(recs, problems):
    seen = set()
    for r in recs:
        p = r["properties"]
        if not p.get("object_id"):
            problems.append(f"{r['id']}: object_id kosong")
        if p["part_id"] in seen:
            problems.append(f"part_id duplikat: {p['part_id']}")
        seen.add(p["part_id"])
        if r["id"] != p["part_id"]:
            problems.append(f"{p['part_id']}: Feature.id != part_id")


def validate_hierarchy(recs, by_id, problems, tol):
    roots_per_obj: dict[str, int] = {}
    for r in recs:
        p = r["properties"]
        if p["parent_part_id"] is None:
            roots_per_obj[p["object_id"]] = roots_per_obj.get(p["object_id"], 0) + 1
            if p["part_level"] != 0:
                problems.append(f"{p['part_id']}: root dengan part_level {p['part_level']}")
            continue
        par = by_id.get(p["parent_part_id"])
        if par is None:
            problems.append(f"{p['part_id']}: parent {p['parent_part_id']} tidak ada (orphan)")
            continue
        pp = par["properties"]
        if pp["object_id"] != p["object_id"]:
            problems.append(f"{p['part_id']}: parent beda object_id")
        if p["part_level"] != pp["part_level"] + 1:
            problems.append(f"{p['part_id']}: part_level != parent.part_level + 1")
        if abs(p["base_height_agl_m"] - pp["top_height_agl_m"]) > tol:
            problems.append(f"{p['part_id']}: base_height_agl_m != parent.top_height_agl_m")
    for oid, n in roots_per_obj.items():
        if n != 1:
            problems.append(f"object_id {oid}: jumlah root = {n}")


def validate_vertical(recs, problems, tol):
    for r in recs:
        p = r["properties"]
        pid = p["part_id"]
        if abs((p["top_height_agl_m"] - p["base_height_agl_m"]) - p["part_height_m"]) > tol:
            problems.append(f"{pid}: top-base != part_height_m")
        if abs(p["ground_elevation_m"] + p["base_height_agl_m"] - p["base_elevation_m"]) > tol:
            problems.append(f"{pid}: ground+base_agl != base_elevation_m")
        if abs(p["ground_elevation_m"] + p["top_height_agl_m"] - p["top_elevation_m"]) > tol:
            problems.append(f"{pid}: ground+top_agl != top_elevation_m")
        if p["part_height_m"] < 0 or (p["parent_part_id"] is not None and p["part_height_m"] <= 0):
            problems.append(f"{pid}: part_height_m tidak valid ({p['part_height_m']})")
        if not (0.0 <= p["valid_coverage_ratio"] <= 1.0):
            problems.append(f"{pid}: valid_coverage_ratio di luar [0,1]")


def validate_geometry(recs, by_id, root_of, problems):
    for r in recs:
        g = r["geom_work"]
        pid = r["id"]
        if g is None or g.is_empty or not g.is_valid or g.area <= 0:
            problems.append(f"{pid}: geometri invalid/kosong/area 0")
            continue
        par_id = r["properties"]["parent_part_id"]
        if par_id is None:
            continue
        for label, ref in (("parent", by_id[par_id]["geom_work"]),
                           ("root footprint", by_id[root_of[r["properties"]["object_id"]]]["geom_work"])):
            outside = g.difference(ref).area
            if outside > max(1e-6 * g.area, 1e-4):
                problems.append(f"{pid}: keluar dari {label} ({outside:.4f} m²)")


def validate_volume(recs, problems, tol):
    for r in recs:
        p = r["properties"]
        expect = p["area_m2"] * p["part_height_m"]
        vt = max(0.1, tol * max(p["volume_m3"], 1.0))
        if abs(p["volume_m3"] - expect) > vt:
            problems.append(f"{p['part_id']}: volume_m3 != area_m2 * part_height_m")


def validate_all(recs, cfg: Config):
    tol = _tol(cfg)
    by_id = {r["id"]: r for r in recs}
    root_of = {r["properties"]["object_id"]: r["id"] for r in recs
               if r["properties"]["parent_part_id"] is None}
    problems: list[str] = []
    validate_ids(recs, problems)
    validate_hierarchy(recs, by_id, problems, tol)
    validate_vertical(recs, problems, tol)
    if not any("orphan" in s for s in problems):
        validate_geometry(recs, by_id, root_of, problems)
    validate_volume(recs, problems, tol)
    if problems:
        raise AtapValidationError(problems)


# =============================================================================
#                                  OUTPUT
# =============================================================================
def _to_output_geojson(geom_work, to_out: Transformer, digits: int) -> dict:
    g = reproject_geom(geom_work, to_out)
    if not g.is_valid:
        g = as_polygonal(polygonal_parts(g))
    if g is None or g.is_empty:
        raise AtapError("Geometri output tidak dapat diperbaiki setelah reproyeksi.")
    r = shapely.set_precision(g, 10.0 ** (-digits), mode="pointwise")
    if r.is_valid and not r.is_empty:
        g = r
    polys = [orient(p, sign=1.0) for p in polygonal_parts(g)]   # RFC 7946: exterior CCW
    if not polys:
        raise AtapError("Geometri output kosong setelah reproyeksi.")
    return mapping(as_polygonal(polys))


def build_feature_collection(recs, cfg: Config, meta: dict) -> dict:
    to_out = Transformer.from_crs(CRS.from_user_input(cfg.working_crs),
                                  CRS.from_epsg(4326), always_xy=True)
    feats = []
    for r in recs:
        feats.append({"type": "Feature", "id": r["id"], "properties": r["properties"],
                      "geometry": _to_output_geojson(r["geom_work"], to_out, cfg.coord_digits)})
    fc = {"type": "FeatureCollection",
          "name": os.path.splitext(os.path.basename(cfg.output_geojson))[0]}
    fc.update(meta)
    fc["features"] = feats
    return fc


def atomic_write_geojson(obj: dict, path: str):
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".atap_", suffix=".geojson.tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# =============================================================================
#                 EKSEKUSI: urutan spasial + worker paralel
# =============================================================================
def gdal_cache_env(cache_mb: int) -> rasterio.Env:
    # PENTING: rasterio meneruskan GDAL_CACHEMAX ke GDALSetCacheMax64 dalam
    # satuan BYTE (bukan MB seperti env var GDAL biasa).
    return rasterio.Env(GDAL_CACHEMAX=int(cache_mb) * 1024 * 1024)


# Mode otomatis tidak membuat pool untuk dataset kecil: start worker (spawn +
# import numpy/rasterio/shapely) memakan ~1 detik per worker.
AUTO_PARALLEL_MIN_BUILDINGS = 40


def resolve_workers(requested: int, n_tasks: int) -> int:
    if requested and requested > 0:
        w = int(requested)
    else:
        if n_tasks < AUTO_PARALLEL_MIN_BUILDINGS:
            return 1
        w = max(1, (os.cpu_count() or 1) - 1)
    return max(1, min(w, n_tasks))


def spatial_order(records, grid: AnalysisGrid) -> list[int]:
    """Urutkan bangunan per tile DSM (row-major) agar blok raster terpakai ulang."""
    if not grid.dsm_warped and grid.dsm_src.block_shapes:
        bh, bw = grid.dsm_src.block_shapes[0]
    else:
        bh = bw = 256
    inv = ~grid.transform
    keys = []
    for i, (_, geom, _) in enumerate(records):
        if geom is None:
            keys.append((-1, -1, i))
            continue
        minx, miny, maxx, maxy = geom.bounds
        col, row = inv * ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
        keys.append((int(row // bh), int(col // bw), i))
    return [k[2] for k in sorted(keys)]


def process_building(oid: str, geom, props: dict, grid: AnalysisGrid, cfg: Config,
                     pad: int, keep: list[str]) -> dict:
    """Satu bangunan -> {"kind": "ok", "recs", "decomposed"} | {"kind": "skipped", "reason"}."""
    if geom is None:
        return {"kind": "skipped", "reason": "INVALID_OR_EMPTY_FOOTPRINT"}
    win = read_building_window(geom, grid, pad)
    if win is None:
        return {"kind": "skipped", "reason": "OUTSIDE_ANALYSIS_GRID"}
    dtm, dsm, wt = win
    res = process_parcel(geom, dtm, dsm, wt, cfg)
    if res["status"] != "ok":
        return {"kind": "skipped", "reason": res["reason"]}
    src_props = {k: props[k] for k in keep if k in props}
    return {"kind": "ok", "decomposed": len(res["parts"]) > 1,
            "recs": build_part_records(oid, res, wt, src_props, cfg)}


# State per proses worker (diisi oleh initializer, sekali per worker).
_WORKER: dict = {}


def _worker_init(cfg: Config, cache_mb: int):
    env = gdal_cache_env(cache_mb)
    env.__enter__()                      # aktif selama umur proses worker
    work_crs = CRS.from_user_input(cfg.working_crs)
    dsm_src, dsm_reader, dsm_warped = open_dsm_master_grid(cfg, work_crs)
    grid = align_dtm_to_dsm(cfg, work_crs, dsm_src, dsm_reader, dsm_warped)
    _WORKER.update(env=env, cfg=cfg, grid=grid,
                   pad=max(1, int(cfg.morph_closing_iters) + 2),
                   keep=list(cfg.keep_properties or []))


def _worker_chunk(items: list) -> list:
    w = _WORKER
    out = []
    for idx, oid, geom, props in items:
        try:
            out.append((idx, process_building(oid, geom, props, w["grid"], w["cfg"],
                                              w["pad"], w["keep"])))
        except Exception as e:
            raise RuntimeError(f"object_id {oid}: {type(e).__name__}: {e}") from e
    return out


# =============================================================================
#               FUNGSI INTI YANG DIPANGGIL CLI & GUI
# =============================================================================
_OVERRIDABLE = (
    "input_geojson", "dtm_path", "dsm_path", "output_geojson", "id_field",
    "height_diff_threshold_m", "min_subregion_area_m2", "min_building_height_m",
    "base_elevation_stat", "ground_source_type", "vertical_datum",
    "max_height_classes", "min_footprint_change_ratio", "morph_closing_iters",
    "max_fill_hole_area_m2", "parent_min_containment_ratio",
    "regularize", "simplify_tolerance_m", "rectangular_ratio", "circularity_threshold",
    "working_crs", "output_crs", "keep_properties", "round_digits", "coord_digits",
    "workers", "gdal_cache_mb",
)


def run_elevation(
    input_geojson: Optional[str] = None,
    dtm_path: Optional[str] = None,
    dsm_path: Optional[str] = None,
    output_geojson: Optional[str] = None,
    *,
    id_field: Optional[str] = None,
    height_diff_threshold_m: Optional[float] = None,
    min_subregion_area_m2: Optional[float] = None,
    min_building_height_m: Optional[float] = None,
    base_elevation_stat: Optional[str] = None,
    ground_source_type: Optional[str] = None,
    vertical_datum: Optional[str] = None,
    max_height_classes: Optional[int] = None,
    min_footprint_change_ratio: Optional[float] = None,
    morph_closing_iters: Optional[int] = None,
    max_fill_hole_area_m2: Optional[float] = None,
    parent_min_containment_ratio: Optional[float] = None,
    regularize: Optional[bool] = None,
    simplify_tolerance_m: Optional[float] = None,
    rectangular_ratio: Optional[float] = None,
    circularity_threshold: Optional[float] = None,
    working_crs: Optional[str] = None,
    output_crs: Optional[str] = None,
    keep_properties: Optional[list] = None,
    round_digits: Optional[int] = None,
    coord_digits: Optional[int] = None,
    workers: Optional[int] = None,
    gdal_cache_mb: Optional[int] = None,
    base_cfg: Optional[Config] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
    # ---- Parameter lama (dihapus oleh spec ATAP) — diterima agar pemanggil
    #      lama tidak crash, tetapi TIDAK berpengaruh. ----
    embed_ground_z: Optional[bool] = None,
) -> dict:
    """
    Jalankan pipeline ATAP Elevation end-to-end. Parameter None memakai nilai
    dari `base_cfg` (atau CONFIG default).

    Callbacks (opsional):
      progress_cb(current, total, message)  -> total>0 determinate, total==0 indeterminate
      log_cb(message)                       -> satu baris log (default: print)
      cancel_flag() -> bool                 -> diperiksa antar bangunan / tiap ~0,5 s

    Paralel: `workers` > 1 memakai ProcessPoolExecutor. Di Windows (spawn),
    pemanggil harus berada di balik `if __name__ == "__main__":` atau
    menjalankan script ini lewat subprocess (seperti CLI).

    Raise AtapInputError / AtapValidationError bila kontrak dilanggar (fail-fast).
    Bila dibatalkan, file TIDAK ditulis (output parsial bukan canonical).

    Returns: {"output_path", "num_features", "num_parcels", "num_buildings",
              "num_skipped", "cancelled"}
    """
    def _log(msg: str):
        (log_cb or print)(msg)

    def _prog(c: int, t: int, m: str):
        if progress_cb is not None:
            progress_cb(c, t, m)

    def _cancelled() -> bool:
        return bool(cancel_flag()) if cancel_flag is not None else False

    t0 = time.time()
    started = datetime.now(timezone.utc)

    cfg = replace(base_cfg or CONFIG)
    local = locals()
    for k in _OVERRIDABLE:
        v = local.get(k)
        if v is not None:
            setattr(cfg, k, v)

    if embed_ground_z:
        _log("[warn] embed_ground_z diabaikan: Z renderer tidak boleh masuk canonical geometry.")

    # ---- Validasi config dasar ----
    if cfg.base_elevation_stat not in ("min", "mean", "median"):
        raise AtapInputError(f"base_elevation_stat tidak dikenal: {cfg.base_elevation_stat}")
    if cfg.ground_source_type not in ("DTM", "DEM"):
        raise AtapInputError("ground_source_type harus 'DTM' atau 'DEM'.")
    if CRS.from_user_input(cfg.output_crs) != CRS.from_epsg(4326):
        raise AtapInputError("Canonical output ATAP wajib EPSG:4326.")
    try:
        work_crs = CRS.from_user_input(cfg.working_crs)
    except Exception as e:
        raise AtapInputError(f"working_crs tidak valid: {cfg.working_crs}") from e
    if not is_metric_projected(work_crs):
        raise AtapInputError(f"working_crs harus proyeksi metrik: {cfg.working_crs}")
    # DTM dicek paling awal (Test A: gagal eksplisit).
    if not cfg.dtm_path or not os.path.isfile(cfg.dtm_path):
        raise AtapInputError(
            f"DTM wajib untuk produksi ATAP (spec §3.1) — tidak ditemukan: {cfg.dtm_path!r}")

    _prog(0, 0, "Memuat footprint...")
    fp = load_footprints(cfg, work_crs, _log)
    n_parcels = fp["feature_count"]
    _log(f"[info] {n_parcels} footprint dimuat; ID dari "
         f"{'Feature.id' if fp['id_source']['mode'] == 'feature_id' else 'properti ' + repr(fp['id_source']['field'])}")

    _prog(0, 0, "Membuka DSM (master grid) & menyelaraskan DTM...")
    dsm_src, dsm_reader, dsm_warped = open_dsm_master_grid(cfg, work_crs)
    try:
        grid = align_dtm_to_dsm(cfg, work_crs, dsm_src, dsm_reader, dsm_warped)
    except Exception:
        for h in (dsm_reader, dsm_src):
            try:
                h.close()
            except Exception:
                pass
        raise

    try:
        _log(f"[info] Grid analisis = DSM{' (reproyeksi)' if dsm_warped else ''}: "
             f"{grid.width}x{grid.height} px, resolusi {grid.res_x:.4f} x {grid.res_y:.4f} m; "
             f"DTM di-resample {DTM_RESAMPLING} ke grid DSM.")

        keep = list(cfg.keep_properties or [])
        pad = max(1, int(cfg.morph_closing_iters) + 2)
        records = fp["records"]
        order = spatial_order(records, grid)
        items = [(i, records[i][0], records[i][1], records[i][2]) for i in order]
        n_workers = resolve_workers(cfg.workers, n_parcels)
        chunk_size = None
        results: dict[int, dict] = {}
        cancelled = False

        if n_workers == 1:
            _log(f"[info] Eksekusi 1 proses; GDAL cache {cfg.gdal_cache_mb} MB.")
            with gdal_cache_env(cfg.gdal_cache_mb):
                for done, (i, oid, geom, props) in enumerate(items, 1):
                    if _cancelled():
                        cancelled = True
                        break
                    _prog(done, n_parcels, f"Memproses bangunan {done}/{n_parcels}")
                    results[i] = process_building(oid, geom, props, grid, cfg, pad, keep)
        else:
            chunk_size = max(1, min(16, math.ceil(n_parcels / (n_workers * 8))))
            chunks = [items[k:k + chunk_size] for k in range(0, len(items), chunk_size)]
            cache_per_worker = max(64, int(cfg.gdal_cache_mb) // n_workers)
            _log(f"[info] Eksekusi paralel: {n_workers} worker, {len(chunks)} batch "
                 f"@ {chunk_size} bangunan; GDAL cache {cache_per_worker} MB/worker.")
            ex = ProcessPoolExecutor(max_workers=n_workers, initializer=_worker_init,
                                     initargs=(cfg, cache_per_worker),
                                     mp_context=mp.get_context("spawn"))
            try:
                pending = {ex.submit(_worker_chunk, c) for c in chunks}
                _prog(0, n_parcels, f"Memproses bangunan 0/{n_parcels}")
                while pending:
                    finished, pending = wait(pending, timeout=0.5,
                                             return_when=FIRST_COMPLETED)
                    for f in finished:
                        for i, r in f.result():
                            results[i] = r
                    if finished:
                        _prog(len(results), n_parcels,
                              f"Memproses bangunan {len(results)}/{n_parcels}")
                    if pending and _cancelled():
                        cancelled = True
                        for f in pending:
                            f.cancel()
                        break
            except BrokenProcessPool as e:
                raise AtapError(f"Worker paralel berhenti tidak normal: {e}") from e
            except RuntimeError as e:
                raise AtapError(f"Gagal memproses bangunan — {e}") from e
            finally:
                ex.shutdown(wait=True, cancel_futures=True)

        if cancelled:
            _log("[info] Dibatalkan user — output tidak ditulis.")

        # Rakit hasil sesuai URUTAN INPUT (deterministik, apa pun jumlah worker).
        all_recs: list[dict] = []
        skipped: list[dict] = []
        n_decomposed = 0
        for i in range(n_parcels):
            r = results.get(i)
            if r is None:
                continue
            if r["kind"] == "skipped":
                skipped.append({"object_id": records[i][0], "reason": r["reason"]})
            else:
                all_recs.extend(r["recs"])
                n_decomposed += int(r["decomposed"])

        if cancelled:
            return {"output_path": None, "num_features": 0, "num_parcels": n_parcels,
                    "num_buildings": 0, "num_skipped": len(skipped), "cancelled": True}

        if skipped:
            _log(f"[warn] {len(skipped)} bangunan dilewati (lihat summary.skipped_buildings).")
        if not all_recs:
            raise AtapError("Tidak ada bangunan yang dapat diproses (cek cakupan DSM/DTM).")

        _prog(n_parcels, n_parcels, "Validasi invariant...")
        validate_all(all_recs, cfg)

        # ---- Metadata dataset (spec §17-18) ----
        roots = [r for r in all_recs if r["properties"]["parent_part_id"] is None]
        with rasterio.open(cfg.dtm_path) as dsrc:
            dtm_res = (abs(dsrc.transform.a), abs(dsrc.transform.e))
            dtm_unit = (CRS.from_user_input(dsrc.crs).axis_info[0].unit_name
                        if dsrc.crs else None)
        dsm_unit = CRS.from_user_input(dsm_src.crs).axis_info[0].unit_name
        params = {k: v for k, v in asdict(cfg).items()
                  if k not in ("input_geojson", "dtm_path", "dsm_path", "output_geojson",
                               "working_crs", "output_crs", "workers", "gdal_cache_mb",
                               "id_field", "vertical_datum", "ground_source_type",
                               "base_elevation_stat")}
        finished = datetime.now(timezone.utc)
        meta = {
            "atap": {"engine_version": ENGINE_VERSION, "profile_version": PROFILE_VERSION},
            "process": {
                "name": "atap_elevation",
                "implementation": os.path.basename(__file__),
                "started_at_utc": started.isoformat(),
                "finished_at_utc": finished.isoformat(),
                "duration_s": round(time.time() - t0, 2),
                "software": {"python": platform.python_version(), "numpy": np.__version__,
                             "rasterio": rasterio.__version__, "shapely": shapely.__version__},
            },
            "inputs": {
                "footprint": {"file_name": os.path.basename(cfg.input_geojson),
                              "feature_count": n_parcels, "crs": fp["crs"],
                              "id_source": fp["id_source"]},
                "dsm": {"file_name": os.path.basename(cfg.dsm_path),
                        "crs": CRS.from_user_input(dsm_src.crs).to_string(),
                        "resolution_x": abs(dsm_src.transform.a),
                        "resolution_y": abs(dsm_src.transform.e),
                        "resolution_unit": dsm_unit},
                "dtm": {"file_name": os.path.basename(cfg.dtm_path),
                        "crs": CRS.from_user_input(grid.dtm_src.crs).to_string(),
                        "resolution_x": dtm_res[0], "resolution_y": dtm_res[1],
                        "resolution_unit": dtm_unit,
                        "ground_source_type": cfg.ground_source_type},
            },
            "processing": {
                "working_crs": work_crs.to_string(),
                "output_crs": "EPSG:4326",
                "analysis_grid_source": ANALYSIS_GRID_SOURCE,
                "analysis_resolution_x_m": round(grid.res_x, 6),
                "analysis_resolution_y_m": round(grid.res_y, 6),
                "dsm_reprojected": grid.dsm_warped,
                "terrain_normalization": True,
                "dtm_resampling": DTM_RESAMPLING,
                "orientation_convention": "azimut sisi terpanjang MRR, searah jarum jam "
                                          "dari grid-north working_crs, rentang [0,180)",
                "height_clustering": "kmeans_1d (quantile init, exact 1D Lloyd, "
                                     "sorted prefix-sum)",
                "parameters": params,
                "execution": {"workers": n_workers, "chunk_size": chunk_size,
                              "gdal_cache_mb": int(cfg.gdal_cache_mb),
                              "processing_order": "dsm_tile_row_major",
                              "output_order": "input_order"},
            },
            "vertical_reference": {
                "mode": "terrain_normalized",
                "dtm_used": True,
                "height_surface": "nDSM",
                "ground_source": "DTM",
                "ground_source_type": cfg.ground_source_type,
                "base_elevation_stat": cfg.base_elevation_stat,
                "vertical_datum": cfg.vertical_datum,
            },
            "summary": {
                "building_count": len(roots),
                "decomposed_building_count": n_decomposed,
                "part_count": len(all_recs),
                "max_part_level": max(r["properties"]["part_level"] for r in all_recs),
                "max_top_height_agl_m": max(r["properties"]["top_height_agl_m"] for r in all_recs),
                "total_volume_m3": round(sum(r["properties"]["volume_m3"] for r in all_recs),
                                         cfg.round_digits),
                "skipped_building_count": len(skipped),
                "skipped_buildings": skipped,
                "validation": {"status": "passed", "checked_parts": len(all_recs)},
            },
        }

        _prog(n_parcels, n_parcels, "Menulis GeoJSON...")
        fc = build_feature_collection(all_recs, cfg, meta)
        atomic_write_geojson(fc, cfg.output_geojson)
        _log(f"[done] {len(all_recs)} part dari {len(roots)} bangunan ditulis ke "
             f"{cfg.output_geojson} (EPSG:4326)")
        _prog(n_parcels, n_parcels, f"Selesai — {len(all_recs)} part")

        return {"output_path": cfg.output_geojson, "num_features": len(all_recs),
                "num_parcels": n_parcels, "num_buildings": len(roots),
                "num_skipped": len(skipped), "cancelled": False}
    finally:
        grid.close()


# =============================================================================
#                                   CLI
# =============================================================================
def parse_args() -> argparse.Namespace:
    d = Config()
    p = argparse.ArgumentParser(
        description="ATAP Elevation: footprint + DSM + DTM (wajib) -> hierarchical "
                    "building mass GeoJSON (EPSG:4326).")
    # paths
    p.add_argument("--input-geojson", required=True, help="GeoJSON footprint (authoritative)")
    p.add_argument("--dtm", dest="dtm_path", required=True, help="DTM .tif (WAJIB)")
    p.add_argument("--dsm", dest="dsm_path", required=True, help="DSM .tif (master analysis grid)")
    p.add_argument("--output", dest="output_geojson", required=True, help="Output GeoJSON")
    p.add_argument("--id-field", default=d.id_field,
                   help="Properti ID bangunan bila Feature.id tidak tersedia")
    # parameter
    p.add_argument("--height-diff-threshold-m", type=float, default=d.height_diff_threshold_m)
    p.add_argument("--min-subregion-area-m2", type=float, default=d.min_subregion_area_m2)
    p.add_argument("--min-building-height-m", type=float, default=d.min_building_height_m)
    p.add_argument("--base-elevation-stat", choices=["min", "mean", "median"],
                   default=d.base_elevation_stat)
    p.add_argument("--ground-source-type", choices=["DTM", "DEM"], default=d.ground_source_type)
    p.add_argument("--vertical-datum", default=d.vertical_datum)
    p.add_argument("--max-height-classes", type=int, default=d.max_height_classes)
    p.add_argument("--min-footprint-change-ratio", type=float,
                   default=d.min_footprint_change_ratio,
                   help="Footprint level atas harus menyusut >= rasio ini agar jadi massa "
                        "baru; 0.25=25%%. 0 = selalu pisah.")
    p.add_argument("--morph-closing-iters", type=int, default=d.morph_closing_iters)
    p.add_argument("--max-fill-hole-area-m2", type=float, default=d.max_fill_hole_area_m2,
                   help="Hole <= luas ini diisi; lebih besar dipertahankan (courtyard)")
    p.add_argument("--parent-min-containment-ratio", type=float,
                   default=d.parent_min_containment_ratio)
    p.add_argument("--regularize", action="store_true", default=d.regularize)
    p.add_argument("--no-regularize", dest="regularize", action="store_false")
    p.add_argument("--simplify-tolerance-m", type=float, default=d.simplify_tolerance_m)
    p.add_argument("--rectangular-ratio", type=float, default=d.rectangular_ratio)
    p.add_argument("--circularity-threshold", type=float, default=d.circularity_threshold)
    p.add_argument("--keep-properties", default=",".join(d.keep_properties),
                   help="Daftar properti sumber (pisah koma) yang ikut dibawa")
    p.add_argument("--working-crs", default=d.working_crs)
    p.add_argument("--round-digits", type=int, default=d.round_digits)
    p.add_argument("--workers", type=int, default=d.workers,
                   help="Jumlah proses paralel; 0 = otomatis (core - 1), 1 = tanpa paralel")
    p.add_argument("--gdal-cache-mb", type=int, default=d.gdal_cache_mb,
                   help="Total cache blok GDAL (MB), dibagi ke semua worker")
    return p.parse_args()


def _cli_progress(c, t, m):
    if t > 0:
        sys.stderr.write(f"\r{m}  [{c}/{t}]      ")
    else:
        sys.stderr.write(f"\r{m}      ")
    sys.stderr.flush()
    if t > 0 and c == t:
        sys.stderr.write("\n")


def main() -> int:
    a = parse_args()
    try:
        res = run_elevation(
            input_geojson=a.input_geojson,
            dtm_path=a.dtm_path,
            dsm_path=a.dsm_path,
            output_geojson=a.output_geojson,
            id_field=a.id_field,
            height_diff_threshold_m=a.height_diff_threshold_m,
            min_subregion_area_m2=a.min_subregion_area_m2,
            min_building_height_m=a.min_building_height_m,
            base_elevation_stat=a.base_elevation_stat,
            ground_source_type=a.ground_source_type,
            vertical_datum=a.vertical_datum,
            max_height_classes=a.max_height_classes,
            min_footprint_change_ratio=a.min_footprint_change_ratio,
            morph_closing_iters=a.morph_closing_iters,
            max_fill_hole_area_m2=a.max_fill_hole_area_m2,
            parent_min_containment_ratio=a.parent_min_containment_ratio,
            regularize=a.regularize,
            simplify_tolerance_m=a.simplify_tolerance_m,
            rectangular_ratio=a.rectangular_ratio,
            circularity_threshold=a.circularity_threshold,
            keep_properties=[s.strip() for s in a.keep_properties.split(",") if s.strip()],
            working_crs=a.working_crs,
            round_digits=a.round_digits,
            workers=a.workers,
            gdal_cache_mb=a.gdal_cache_mb,
            progress_cb=_cli_progress,
        )
    except AtapError as e:
        sys.stderr.write(f"\n[error] {e}\n")
        return 2
    return 0 if res["num_features"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
