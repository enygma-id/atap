# SPDX-License-Identifier: AGPL-3.0-only
"""Command-line interface for running and validating ATAP output."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform

from .engine.config import (
    ENGINE_VERSION,
    PROFILE_VERSION,
    AtapError,
    AtapInputError,
    AtapValidationError,
)

RUN_FIELDS = (
    "id_field", "height_diff_threshold_m", "min_subregion_area_m2",
    "min_building_height_m", "base_elevation_stat", "ground_source_type",
    "vertical_datum", "max_height_classes", "min_footprint_change_ratio",
    "morph_closing_iters", "max_fill_hole_area_m2",
    "parent_min_containment_ratio", "regularize", "simplify_tolerance_m",
    "rectangular_ratio", "circularity_threshold", "keep_properties",
    "working_crs", "round_digits", "workers", "gdal_cache_mb", "raster_drivers",
)


def run_elevation(*args, **kwargs):
    """Invoke the engine without importing it in the server process."""
    from .engine.pipeline import run_elevation as engine_run

    return engine_run(*args, **kwargs)


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-geojson", required=True)
    parser.add_argument("--dsm", dest="dsm_path", required=True)
    parser.add_argument("--dtm", dest="dtm_path", required=True)
    parser.add_argument("--output", dest="output_geojson", required=True)
    parser.add_argument("--params-json", type=Path)
    parser.add_argument("--events", choices=("human", "jsonl"), default="human")
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--raster-drivers", nargs="+")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--id-field", help="Building ID properties key (default: id; overrides automatic selection)")
    parser.add_argument("--height-diff-threshold-m", type=float)
    parser.add_argument("--min-subregion-area-m2", type=float)
    parser.add_argument("--min-building-height-m", type=float)
    parser.add_argument("--base-elevation-stat", choices=("min", "mean", "median"))
    parser.add_argument("--ground-source-type", choices=("DTM", "DEM"))
    parser.add_argument("--vertical-datum")
    parser.add_argument("--max-height-classes", type=int)
    parser.add_argument("--min-footprint-change-ratio", type=float)
    parser.add_argument("--morph-closing-iters", type=int)
    parser.add_argument("--max-fill-hole-area-m2", type=float)
    parser.add_argument("--parent-min-containment-ratio", type=float)
    regularize = parser.add_mutually_exclusive_group()
    regularize.add_argument("--regularize", action="store_true", default=None)
    regularize.add_argument("--no-regularize", dest="regularize", action="store_false")
    parser.add_argument("--simplify-tolerance-m", type=float)
    parser.add_argument("--rectangular-ratio", type=float)
    parser.add_argument("--circularity-threshold", type=float)
    parser.add_argument("--keep-properties")
    parser.add_argument("--working-crs")
    parser.add_argument("--round-digits", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--gdal-cache-mb", type=int)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="atap")
    parser.add_argument(
        "--version", action="version",
        version=f"ATAP engine {ENGINE_VERSION}, profile {PROFILE_VERSION}",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Generate hierarchical building masses")
    _add_run_arguments(run)
    validate = commands.add_parser("validate", help="Validate an ATAP GeoJSON file")
    validate.add_argument("file", type=Path)
    serve = commands.add_parser("serve", help="Start the local HTTP API and playground")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--work-dir", type=Path)
    serve.add_argument("--max-upload-mb", type=int, default=1024)
    serve.add_argument("--max-concurrent", type=int, default=1)
    serve.add_argument("--job-ttl-hours", type=float, default=24)
    serve.add_argument("--grace-seconds", type=float, default=30)
    serve.add_argument("--cors-origin")
    return parser.parse_args(argv)


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, allow_nan=False), flush=True)


def _load_params(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AtapInputError(f"Cannot read parameter JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AtapInputError("Parameter JSON must contain an object.")
    unknown = sorted(set(value) - set(RUN_FIELDS))
    if unknown:
        raise AtapInputError(f"Unknown parameter(s): {', '.join(unknown)}")
    return value


def _run(args: argparse.Namespace) -> int:
    params = _load_params(args.params_json)
    for field in RUN_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            if field == "keep_properties" and isinstance(value, str):
                value = [item.strip() for item in value.split(",") if item.strip()]
            params[field] = value

    def progress(current: int, total: int, message: str) -> None:
        if args.events == "jsonl":
            _emit({"type": "progress", "current": current, "total": total, "message": message})
        elif not args.quiet:
            print(f"{message} [{current}/{total}]", file=sys.stderr)

    def log(message: str) -> None:
        if args.events == "jsonl":
            tag = message[1:message.find("]")] if message.startswith("[") else "info"
            level = "info" if tag == "done" else tag
            _emit({"type": "log", "level": level, "message": message})
        elif not args.quiet:
            print(message, file=sys.stderr)

    result = run_elevation(
        args.input_geojson, args.dtm_path, args.dsm_path, args.output_geojson,
        progress_cb=progress, log_cb=log,
        cancel_flag=(lambda: args.cancel_file.exists()) if args.cancel_file else None,
        **params,
    )
    if result["cancelled"]:
        return 130
    if args.events == "jsonl":
        _emit({"type": "result", **result})
    elif not args.quiet:
        print(json.dumps(result, indent=2), file=sys.stderr)
    return 0


def _problem(message: str, problems: list[str]) -> None:
    if len(problems) < 100:
        problems.append(message)


def validate_file(path: Path) -> list[str]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read GeoJSON: {exc}"]
    problems: list[str] = []
    if doc.get("type") != "FeatureCollection":
        return ["Top-level type must be FeatureCollection."]
    features = doc.get("features")
    if not isinstance(features, list) or not features:
        return ["features must be a non-empty array."]
    digits = doc.get("processing", {}).get("parameters", {}).get("round_digits", 2)
    tol = max(10 ** -digits, 1e-6)
    by_id: dict[str, dict] = {}
    geometries: dict[str, object] = {}
    for index, feature in enumerate(features):
        p = feature.get("properties", {})
        pid = p.get("part_id")
        if not p.get("object_id"):
            _problem(f"features[{index}]: object_id is missing", problems)
        if not pid:
            _problem(f"features[{index}]: part_id is missing", problems)
        elif pid in by_id:
            _problem(f"Duplicate part_id: {pid}", problems)
        else:
            by_id[pid] = feature
        if feature.get("id") != pid:
            _problem(f"{pid}: Feature.id must equal part_id", problems)
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            _problem(f"{pid}: geometry must be Polygon or MultiPolygon", problems)
        else:
            try:
                geom = shape(geometry)
                if geom.is_empty or not geom.is_valid or geom.area <= 0:
                    _problem(f"{pid}: geometry must be valid, non-empty, and positive-area", problems)
                elif pid:
                    geometries[pid] = geom
            except Exception as exc:
                _problem(f"{pid}: invalid geometry: {exc}", problems)
        for key in ("valid_coverage_ratio",):
            value = p.get(key)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                _problem(f"{pid}: {key} must be between 0 and 1", problems)
        equations = (
            ("part_height_m", p.get("top_height_agl_m", 0) - p.get("base_height_agl_m", 0)),
            ("base_elevation_m", p.get("ground_elevation_m", 0) + p.get("base_height_agl_m", 0)),
            ("top_elevation_m", p.get("ground_elevation_m", 0) + p.get("top_height_agl_m", 0)),
        )
        for key, expected in equations:
            if not isinstance(p.get(key), (int, float)) or abs(p[key] - expected) > tol:
                _problem(f"{pid}: invalid {key}", problems)
        expected_volume = p.get("area_m2", 0) * p.get("part_height_m", 0)
        volume_tol = max(0.1, tol * max(p.get("volume_m3", 0), 1))
        if abs(p.get("volume_m3", 0) - expected_volume) > volume_tol:
            _problem(f"{pid}: invalid volume_m3", problems)
    for pid, feature in by_id.items():
        p = feature["properties"]
        parent_id = p.get("parent_part_id")
        level = p.get("part_level")
        if level == 0 and parent_id is not None:
            _problem(f"{pid}: root parent_part_id must be null", problems)
        if level and parent_id not in by_id:
            _problem(f"{pid}: parent_part_id does not exist", problems)
        elif level and parent_id in by_id:
            parent = by_id[parent_id]["properties"]
            if p.get("object_id") != parent.get("object_id"):
                _problem(f"{pid}: parent belongs to another object_id", problems)
            if level != parent.get("part_level") + 1:
                _problem(f"{pid}: part_level is not parent level + 1", problems)
            if abs(p.get("base_height_agl_m", 0) - parent.get("top_height_agl_m", 0)) > tol:
                _problem(f"{pid}: child base does not equal parent top", problems)
    if geometries:
        union = next(iter(geometries.values()))
        for geom in list(geometries.values())[1:]:
            union = union.union(geom)
        lon, lat = union.centroid.x, union.centroid.y
        zone = max(1, min(60, int((lon + 180) // 6) + 1))
        utm = CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)
        project = Transformer.from_crs(4326, utm, always_xy=True).transform
        metric = {pid: transform(project, geom) for pid, geom in geometries.items()}
        roots = {
            feature["properties"]["object_id"]: pid
            for pid, feature in by_id.items()
            if feature["properties"].get("parent_part_id") is None
        }
        for pid, feature in by_id.items():
            parent_id = feature["properties"].get("parent_part_id")
            container_id = parent_id or roots.get(feature["properties"].get("object_id"))
            if pid in metric and container_id in metric and container_id != pid:
                outside = metric[pid].difference(metric[container_id].buffer(tol)).area
                if outside > tol:
                    _problem(f"{pid}: geometry lies {outside:.4f} m2 outside its parent", problems)
    return problems


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "validate":
        problems = validate_file(args.file)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 3
        print(f"Valid ATAP GeoJSON: {args.file}", file=sys.stderr)
        return 0
    if args.command == "serve":
        from .server import serve

        return serve(args)
    raise AtapInputError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    events = "jsonl" if "--events" in (argv or sys.argv[1:]) and "jsonl" in (argv or sys.argv[1:]) else "human"
    try:
        return _main(argv)
    except AtapInputError as exc:
        if events == "jsonl":
            _emit({"type": "error", "code": "INPUT", "message": str(exc)})
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 2
    except AtapValidationError as exc:
        if events == "jsonl":
            _emit({"type": "error", "code": "VALIDATION", "message": str(exc)})
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
    except AtapError as exc:
        if events == "jsonl":
            _emit({"type": "error", "code": "INPUT", "message": str(exc)})
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - final CLI boundary
        if events == "jsonl":
            _emit({"type": "error", "code": "INTERNAL", "message": str(exc)})
        else:
            traceback.print_exc(file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
