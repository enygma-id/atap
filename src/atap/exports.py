# SPDX-License-Identifier: AGPL-3.0-only
"""LoD1 building derivatives from validated canonical ATAP GeoJSON.

Binary glTF packing and axis conventions follow ARCA's AGPL-3.0-only
GLBWriter (Enygma), revision c2db610. No BIM ingestion code is required.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import mapbox_earcut
import numpy as np
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely.geometry.polygon import orient
from shapely.ops import transform

from .engine.config import AtapInputError, AtapValidationError

FORMATS = ("glb", "cityjson", "citygml")
SUFFIXES = {"glb": ".glb", "cityjson": ".city.json", "citygml": ".gml"}


def parse_formats(value: str) -> tuple[str, ...]:
    """Normalize a CLI/API selection without changing scientific parameters."""
    if value == "all":
        return FORMATS
    if value == "none":
        return ()
    selected = value.split(",")
    if not selected or any(item not in FORMATS for item in selected):
        raise AtapInputError("Export formats must be all, none, or glb,cityjson,citygml.")
    return tuple(item for item in FORMATS if item in selected)


def _check_cancel(cancel):
    if cancel and cancel():
        raise KeyboardInterrupt("Export cancelled")


def _mesh(geometry, base, top):
    """Closed outward-oriented shells; cap triangulation retains every hole."""
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    shells = []
    for polygon in polygons:
        # Earcut may omit duplicate/collinear boundary vertices. Use the same
        # zero-tolerance boundary for caps and walls, leaving source data intact.
        polygon = orient(polygon.simplify(0, preserve_topology=True), sign=1)
        rings = [np.asarray(r.coords, dtype=np.float64)[:-1, :2]
                 for r in [polygon.exterior, *polygon.interiors]]
        xy = np.concatenate(rings)
        ends = np.cumsum([len(r) for r in rings], dtype=np.uint32)
        indices = mapbox_earcut.triangulate_float64(xy, ends).reshape(-1, 3)
        faces = []
        cap_area = 0.0
        for indices3 in indices:
            tri = xy[indices3]
            cross = np.linalg.det(np.stack((tri[1] - tri[0], tri[2] - tri[0])))
            if cross < 0:
                tri = tri[[0, 2, 1]]
            cap_area += abs(cross) / 2
            faces.append([[float(x), float(y), top] for x, y in tri])
            faces.append([[float(x), float(y), base] for x, y in tri[::-1]])
        if not math.isclose(cap_area, polygon.area, rel_tol=1e-8, abs_tol=1e-6):
            raise AtapValidationError(["Export triangulation does not preserve polygon area."])
        for ring in rings:
            for a, b in zip(ring, np.roll(ring, -1, axis=0)):
                faces.append([[float(a[0]), float(a[1]), base],
                              [float(b[0]), float(b[1]), base],
                              [float(b[0]), float(b[1]), top],
                              [float(a[0]), float(a[1]), top]])
        _validate_shell(faces)
        shells.append(faces)
    return shells


def _validate_shell(faces):
    edges = defaultdict(list)
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            a, b = tuple(a), tuple(b)
            edges[tuple(sorted((a, b)))].append((a, b))
    if any(len(pair) != 2 or pair[0] != pair[1][::-1] for pair in edges.values()):
        raise AtapValidationError(["Export shell has open or inconsistently oriented edges."])


def _prepare(doc, cancel):
    if doc.get("processing", {}).get("parameters", {}).get("mode", "building") != "building":
        raise AtapInputError("Building exports do not support tree mode.")
    try:
        crs = CRS.from_user_input(doc.get("processing", {}).get("working_crs", ""))
    except CRSError as exc:
        raise AtapInputError("Exports require a valid processing.working_crs.") from exc
    if not crs.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-9
                                 for axis in crs.axis_info[:2]):
        raise AtapInputError("Exports require a projected working CRS in metres.")
    project = Transformer.from_crs(4326, crs, always_xy=True).transform
    parts = []
    for feature in doc["features"]:
        _check_cancel(cancel)
        props = feature["properties"]
        base, top = float(props["base_elevation_m"]), float(props["top_elevation_m"])
        if not math.isfinite(base) or not math.isfinite(top) or top <= base:
            raise AtapValidationError([f"{props['part_id']}: export requires positive finite height."])
        geom = transform(project, shape(feature["geometry"]))
        if not geom.is_valid or not all(math.isfinite(v) for v in geom.bounds):
            raise AtapValidationError([f"{props['part_id']}: invalid projected export geometry."])
        try:
            shells = _mesh(geom, base, top)
        except AtapValidationError as exc:
            raise AtapValidationError([f"{props['part_id']}: {problem}"
                                       for problem in exc.problems]) from exc
        parts.append({"properties": props, "shells": shells})
    return crs, parts


def _id(prefix, value):
    # UTF-8 hex is reversible, XML NCName-safe and collision-free across IDs.
    return prefix + str(value).encode("utf-8").hex()


def _points(parts):
    return np.array([p for part in parts for shell in part["shells"]
                     for face in shell for p in face], dtype=np.float64)


def _write_cityjson(path, parts, crs, doc, cancel):
    vertices, lookup, objects = [], {}, {}
    xyz = _points(parts)
    origin = xyz.min(axis=0)
    scale = 0.001

    def vertex(point):
        key = tuple(int(round((point[i] - origin[i]) / scale)) for i in range(3))
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append(list(key))
        return lookup[key]

    for part in parts:
        _check_cancel(cancel)
        props = part["properties"]
        building_id = _id("b_", props["object_id"])
        pid = _id("p_", props["part_id"])
        building = objects.setdefault(building_id, {"type": "Building", "children": [],
                                                   "attributes": {"object_id": props["object_id"]}})
        building["children"].append(pid)
        solids = []
        for shell in part["shells"]:
            faces = []
            for face in shell:
                ring = [vertex(point) for point in face]
                if len(set(ring)) != len(ring):
                    raise AtapValidationError(["CityJSON millimetre quantization collapses an edge."])
                faces.append([ring])
            solids.append([faces])
        objects[pid] = {"type": "BuildingPart", "parents": [building_id],
                        "attributes": props, "geometry": [
                            {"type": "Solid", "lod": "1", "boundaries": solid} for solid in solids]}
    epsg = crs.to_epsg()
    decoded = np.asarray(vertices, dtype=np.float64) * scale + origin
    metadata = {"title": doc.get("name", "ATAP buildings"),
                "geographicalExtent": [*decoded.min(axis=0), *decoded.max(axis=0)]}
    if epsg:
        metadata["referenceSystem"] = f"https://www.opengis.net/def/crs/EPSG/0/{epsg}"
    result = {"type": "CityJSON", "version": "1.1", "CityObjects": objects,
              "vertices": vertices, "transform": {"scale": [scale] * 3, "translate": origin.tolist()},
              "metadata": metadata, "atap": {"vertical_reference": doc.get("vertical_reference", {}),
                                            "working_crs": crs.to_string()}}
    _json(path, result)


GML = "http://www.opengis.net/gml"
CORE = "http://www.opengis.net/citygml/2.0"
BLDG = "http://www.opengis.net/citygml/building/2.0"
GEN = "http://www.opengis.net/citygml/generics/2.0"
for prefix, uri in (("gml", GML), ("core", CORE), ("bldg", BLDG), ("gen", GEN)):
    ET.register_namespace(prefix, uri)


def _xml_text(value):
    text = str(value)
    if any(not (c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or
                0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in text):
        raise AtapValidationError(["An export attribute contains characters forbidden by XML 1.0."])
    return text


def _el(parent, ns, tag, text=None, **attrs):
    child = ET.SubElement(parent, f"{{{ns}}}{tag}", {k: _xml_text(v) for k, v in attrs.items()})
    if text is not None:
        child.text = _xml_text(text)
    return child


def _write_citygml(path, parts, crs, doc, cancel):
    model = ET.Element(f"{{{CORE}}}CityModel")
    model.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
              f"{BLDG} https://schemas.opengis.net/citygml/building/2.0/building.xsd "
              f"{GEN} https://schemas.opengis.net/citygml/generics/2.0/generics.xsd")
    _el(model, GML, "description", json.dumps({"working_crs": crs.to_string(),
        "vertical_reference": doc.get("vertical_reference", {})}, ensure_ascii=False))
    epsg = crs.to_epsg()
    srs = f"urn:ogc:def:crs:EPSG::{epsg}" if epsg else crs.to_wkt()
    xyz = _points(parts)
    envelope = _el(_el(model, GML, "boundedBy"), GML, "Envelope", srsName=srs, srsDimension="3")
    _el(envelope, GML, "lowerCorner", " ".join(map(str, xyz.min(axis=0))))
    _el(envelope, GML, "upperCorner", " ".join(map(str, xyz.max(axis=0))))
    buildings = {}
    for part in parts:
        _check_cancel(cancel)
        props = part["properties"]
        oid = str(props["object_id"])
        if oid not in buildings:
            buildings[oid] = _el(_el(model, CORE, "cityObjectMember"), BLDG, "Building",
                                 **{f"{{{GML}}}id": _id("b_", oid)})
        node = _el(_el(buildings[oid], BLDG, "consistsOfBuildingPart"), BLDG, "BuildingPart",
                   **{f"{{{GML}}}id": _id("p_", props["part_id"])})
        if props.get("name"):
            _el(node, GML, "name", props["name"])
        for key, value in sorted(props.items()):
            attr = _el(node, GEN, "stringAttribute", name=key)
            _el(attr, GEN, "value", json.dumps(value, ensure_ascii=False))
        if len(part["shells"]) == 1:
            containers = [_el(node, BLDG, "lod1Solid")]
        else:
            # Disconnected MultiPolygon components are separate child solids,
            # never an invalid disconnected CompositeSolid.
            containers = []
            for index in range(len(part["shells"])):
                component = _el(_el(node, BLDG, "consistsOfBuildingPart"), BLDG, "BuildingPart",
                    **{f"{{{GML}}}id": _id("p_", props["part_id"]) + f"_c{index}"})
                containers.append(_el(component, BLDG, "lod1Solid"))
        for shell, container in zip(part["shells"], containers):
            solid = _el(container, GML, "Solid", srsName=srs, srsDimension="3")
            surface = _el(_el(solid, GML, "exterior"), GML, "CompositeSurface")
            for face in shell:
                polygon = _el(_el(surface, GML, "surfaceMember"), GML, "Polygon")
                ring = _el(_el(polygon, GML, "exterior"), GML, "LinearRing")
                _el(ring, GML, "posList", " ".join(format(v, ".9f") for p in face + face[:1] for v in p))
    ET.ElementTree(model).write(path, encoding="utf-8", xml_declaration=True)


def _write_glb(path, parts, crs, doc, cancel):
    xyz = _points(parts)
    origin = np.array([*np.mean([xyz.min(axis=0)[:2], xyz.max(axis=0)[:2]], axis=0), xyz[:, 2].min()])
    blob = bytearray()
    views, accessors, meshes, nodes, roots = [], [], [], [], []
    building_nodes = {}

    def attribute(values):
        array = np.asarray(values, dtype="<f4").reshape(-1, 3)
        view = len(views)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": array.nbytes, "target": 34962})
        blob.extend(array.tobytes())
        idx = len(accessors)
        accessors.append({"bufferView": view, "componentType": 5126, "count": len(array),
                          "type": "VEC3", "min": array.min(axis=0).tolist(), "max": array.max(axis=0).tolist()})
        return idx

    for part in parts:
        _check_cancel(cancel)
        props = part["properties"]
        oid = str(props["object_id"])
        if oid not in building_nodes:
            building_nodes[oid] = len(nodes)
            roots.append(len(nodes))
            nodes.append({"name": oid, "children": [], "extras": {"object_id": oid}})
        positions, normals = [], []
        for shell in part["shells"]:
            for face in shell:
                for i in range(1, len(face) - 1):
                    tri = np.asarray([face[0], face[i], face[i + 1]]) - origin
                    tri = np.column_stack((tri[:, 0], tri[:, 2], -tri[:, 1]))
                    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                    norm = np.linalg.norm(normal)
                    if norm <= 1e-12:
                        raise AtapValidationError(["Degenerate GLB triangle."])
                    positions.extend(tri)
                    normals.extend([normal / norm] * 3)
        primitive = {"attributes": {"POSITION": attribute(positions), "NORMAL": attribute(normals)},
                     "mode": 4, "material": 0}
        nodes[building_nodes[oid]]["children"].append(len(nodes))
        nodes.append({"mesh": len(meshes), "name": str(props["part_id"]), "extras": props})
        meshes.append({"primitives": [primitive]})
    gltf = {"asset": {"version": "2.0", "generator": "ATAP building exporter"},
            "scene": 0, "scenes": [{"nodes": roots}], "nodes": nodes, "meshes": meshes,
            "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [.65, .72, .8, 1],
                                                     "metallicFactor": 0, "roughnessFactor": .85}}],
            "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
            "extras": {"working_crs": crs.to_string(), "origin_projected_m": origin.tolist(),
                       "axes": "glTF XYZ = local East, Up, -North", "vertical_reference": doc.get("vertical_reference", {})}}
    raw = json.dumps(gltf, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    raw += b" " * (-len(raw) % 4)
    blob.extend(b"\0" * (-len(blob) % 4))
    with path.open("wb") as stream:
        stream.write(struct.pack("<4sII", b"glTF", 2, 28 + len(raw) + len(blob)))
        stream.write(struct.pack("<II", len(raw), 0x4E4F534A))
        stream.write(raw)
        stream.write(struct.pack("<II", len(blob), 0x004E4942))
        stream.write(blob)


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")), encoding="utf-8")


def export_file(source: str | Path, formats="all", *, cancel=None, log=None) -> dict:
    """Export a saved result; commit manifest last, leaving canonical bytes intact.

    Files are staged beside the source and replaced individually. A manifest is
    published only after every requested writer succeeds; this is not a
    filesystem-wide atomic transaction. Failed attempts leave GeoJSON usable.
    """
    from .cli import validate_file

    selected = parse_formats(formats)
    if not selected:
        return {}
    source = Path(source)
    if source.suffix.lower() not in (".json", ".geojson"):
        raise AtapInputError("Export source must have a .geojson or .json extension.")
    problems = validate_file(source)
    if problems:
        raise AtapValidationError(["Cannot export invalid ATAP result: " + "; ".join(problems)])
    doc = json.loads(source.read_text(encoding="utf-8"))
    crs, parts = _prepare(doc, cancel)
    writers = {"glb": _write_glb, "cityjson": _write_cityjson, "citygml": _write_citygml}
    manifest = {"profile": "atap-building-solids-1", "lod": "1", "working_crs": crs.to_string(),
                "vertical_reference": doc.get("vertical_reference", {}),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "artifacts": {}}
    with tempfile.TemporaryDirectory(prefix=".atap-export-", dir=source.parent) as temp:
        stage = Path(temp)
        for kind in selected:
            _check_cancel(cancel)
            if log:
                log(f"[info] Exporting {kind} ...")
            name = source.stem + SUFFIXES[kind]
            path = stage / name
            writers[kind](path, parts, crs, doc, cancel)
            manifest["artifacts"][kind] = {"file": name, "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        _check_cancel(cancel)
        name = source.stem + ".exports.json"
        _json(stage / name, manifest)
        for artifact in manifest["artifacts"].values():
            os.replace(stage / artifact["file"], source.parent / artifact["file"])
        os.replace(stage / name, source.parent / name)
    return manifest
