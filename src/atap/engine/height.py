# SPDX-License-Identifier: AGPL-3.0-only
"""Terrain normalization and one-dimensional height clustering."""

import numpy as np


# =============================================================================
#                 HEIGHT: nDSM, exact 1D clustering, and merging
# =============================================================================
def compute_ndsm(dsm: np.ndarray, dtm: np.ndarray) -> np.ndarray:
    return dsm - dtm


def configured_ground_stat(arr: np.ndarray, how: str) -> float:
    if how == "mean":
        return float(np.nanmean(arr))
    if how == "median":
        return float(np.nanmedian(arr))
    return float(np.nanmin(arr))


def kmeans_1d(values: np.ndarray, k: int, iters: int = 60):
    """
    Deterministic one-dimensional Lloyd k-means with quantile initialization.

    Cluster means use prefix sums after one O(n log n) sort, followed by
    O(k log n) work per iteration without an n-by-k distance matrix.
    Return labels and ascending centers.
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
    A higher cluster starts a mass only when the cumulative footprint shrinks
    by at least min_change. Otherwise the current level is raised to the next
    cluster center. Return classes and cumulative level heights.
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
