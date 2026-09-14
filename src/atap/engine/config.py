# SPDX-License-Identifier: AGPL-3.0-only
"""Configuration, version constants, and public engine errors."""

from dataclasses import dataclass, field

ENGINE_VERSION = "0.2.0"
PROFILE_VERSION = "0.6"
ANALYSIS_GRID_SOURCE = "DSM"
DTM_RESAMPLING = "bilinear"


# =============================================================================
#                                   ERRORS
# =============================================================================
class AtapError(RuntimeError):
    """Explicit fail-fast engine error."""


class AtapInputError(AtapError):
    """Input does not satisfy the DTM, DSM, footprint, ID, or CRS contract."""


class AtapValidationError(AtapError):
    """Output violates canonical invariants and is not written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        head = "\n  - ".join(problems[:25])
        more = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        super().__init__(f"ATAP output validation failed ({len(problems)} problems):\n  - {head}{more}")


# =============================================================================
#                                  CONFIG  (DEFAULT)
# =============================================================================
@dataclass
class Config:
    # Input and output paths.
    input_geojson: str = "../data/persil_bangunan.geojson"
    dtm_path: str = "../data/dtm_warped.tif"      # Required terrain input.
    dsm_path: str = "../data/dsm_warped.tif"      # Required master analysis grid.
    output_geojson: str = "../output/LOD1.geojson"

    # Stable ID fallback after GeoJSON Feature.id.
    id_field: str | None = None

    # ---- CRS ----
    working_crs: str = "EPSG:32750"   # Metric working CRS (UTM 50S).
    output_crs: str = "EPSG:4326"     # Canonical output is always EPSG:4326.

    # Height and area thresholds.
    height_diff_threshold_m: float = 3.0
    min_subregion_area_m2: float = 12.0
    min_building_height_m: float = 2.0

    # Ground placement reference from the DTM.
    base_elevation_stat: str = "min"       # 'min' | 'mean' | 'median'
    ground_source_type: str = "DTM"        # 'DTM' | 'DEM' terrain reference quality.
    vertical_datum: str | None = None   # For example, "EGM2008" when known.

    # Height segmentation.
    max_height_classes: int = 4
    # A higher level becomes a mass only when its cumulative footprint shrinks
    # by at least this ratio relative to the previous level.
    min_footprint_change_ratio: float = 0.25

    # Masks, holes, and hierarchy.
    morph_closing_iters: int = 3
    # Fill raster-noise holes up to this area and preserve larger interior rings.
    max_fill_hole_area_m2: float = 4.0
    # Minimum child-parent intersection ratio for parent selection.
    parent_min_containment_ratio: float = 0.5

    # Shape regularization.
    regularize: bool = False
    simplify_tolerance_m: float = 0.9
    rectangular_ratio: float = 0.4
    circularity_threshold: float = 0.8

    # Source properties copied to every generated part.
    keep_properties: list[str] = field(
        default_factory=lambda: ["id", "NAMOBJ", "REMARK", "floor_est"])

    # Execution resources. Zero workers selects cores minus one; one is sequential.
    workers: int = 0
    # Total GDAL block cache in MB, divided across workers.
    gdal_cache_mb: int = 512
    # Restrict raster input to these GDAL drivers. None uses GDAL auto-detection.
    raster_drivers: list[str] | None = None

    # Measurement and coordinate rounding.
    round_digits: int = 2
    coord_digits: int = 8   # Output longitude/latitude decimals (about 1 mm).


CONFIG = Config()

# Colliding source attributes receive the "src_" prefix.
CANONICAL_KEYS = (
    "object_id", "part_id", "parent_part_id", "part_level",
    "ground_elevation_m", "base_height_agl_m", "top_height_agl_m", "part_height_m",
    "base_elevation_m", "top_elevation_m", "area_m2", "perimeter_m",
    "oriented_length_m", "oriented_width_m", "dimension_method", "orientation_deg",
    "volume_m3", "delta_z_m", "expected_pixel_count", "valid_pixel_count",
    "support_pixel_count", "valid_coverage_ratio", "decomposition_reason",
    "parent_containment_ratio", "interior_ring_count", "geometry_method",
)
