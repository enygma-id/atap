# SPDX-License-Identifier: AGPL-3.0-only
"""Geometry, placement, serialization, cancellation and CLI export regression tests."""

import json
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import transform

from atap.engine.config import AtapInputError, AtapValidationError
from atap.exports import BLDG, GML, _mesh, export_file


@pytest.fixture
def export_source(tmp_path):
    project = Transformer.from_crs(32750, 4326, always_xy=True).transform
    x, y = 700000, 9430000
    courtyard = Polygon([(x,y),(x+20,y),(x+20,y+20),(x,y+20)],
                        [[(x+5,y+5),(x+5,y+15),(x+15,y+15),(x+15,y+5)]])
    upper = Polygon([(x,y),(x+4,y),(x+4,y+4),(x,y+4)])
    multi = MultiPolygon([Polygon([(x+30,y),(x+32,y),(x+32,y+2),(x+30,y+2)]),
                          Polygon([(x+35,y),(x+38,y),(x+38,y+2),(x+35,y+2)])])
    features = []
    for oid, pid, parent, level, geom, base, top in [
        ('A & <mall>', 'A-P00', None, 0, courtyard, 0, 10),
        ('A & <mall>', 'A-P01', 'A-P00', 1, upper, 10, 17),
        ('B', 'B-P00', None, 0, multi, 0, 6),
    ]:
        props = dict(object_id=oid, part_id=pid, parent_part_id=parent, part_level=level,
                     name='Mall & <Annex>', ground_elevation_m=12,
                     base_height_agl_m=base, top_height_agl_m=top, part_height_m=top-base,
                     base_elevation_m=12+base, top_elevation_m=12+top,
                     area_m2=geom.area, volume_m3=geom.area*(top-base), valid_coverage_ratio=1)
        features.append(dict(type='Feature', id=pid, properties=props,
                             geometry=mapping(transform(project, geom))))
    doc = dict(type='FeatureCollection', name='Two buildings',
               processing=dict(working_crs='EPSG:32750', parameters=dict(round_digits=2)),
               vertical_reference=dict(mode='terrain_normalized', vertical_datum=None), features=features)
    path = tmp_path / 'result.geojson'
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def signed_volume(shell):
    origin = np.array(shell[0][0])
    total = 0
    for face in shell:
        for i in range(1, len(face)-1):
            a, b, c = np.array([face[0], face[i], face[i+1]]) - origin
            total += np.dot(a, np.cross(b, c)) / 6
    return total


def test_closed_concave_courtyard_shell_volume():
    polygon = Polygon([(0,0),(12,0),(12,4),(8,4),(8,10),(0,10)],
                      [[(2,2),(2,6),(5,6),(5,2)]])
    shell = _mesh(polygon, 15, 27)[0]
    assert signed_volume(shell) == pytest.approx(polygon.area * 12)
    # No cap may bridge across the courtyard.
    for face in shell:
        if len(face) == 3:
            assert polygon.covers(Polygon([p[:2] for p in face]))


@pytest.mark.parametrize('polygon', [
    Polygon([(0,0),(8,0),(8,0),(8,6),(0,6)]),
    Polygon([(0,0),(0,0),(4,0),(8,0),(8,6),(0,6),(0,0),(0,0)]),
    Polygon([(0,0),(12,0),(12,12),(0,12)],
            [[(2,2),(2,4),(2,6),(6,6),(6,2)]]),
    MultiPolygon([Polygon([(0,0),(8,0),(8,0),(8,6),(0,6)]),
                  Polygon([(10,0),(14,0),(14,3),(14,6),(10,6)])]),
], ids=['duplicate', 'duplicate-closure-and-collinear', 'collinear-hole', 'multipart'])
def test_redundant_boundary_vertices_keep_closed_shell_and_volume(polygon):
    before = polygon.wkb
    shells = _mesh(polygon, 15, 27)
    assert polygon.wkb == before
    assert sum(signed_volume(shell) for shell in shells) == pytest.approx(polygon.area * 12)
    for shell in shells:
        for face in shell:
            if len(face) == 3:
                assert polygon.covers(Polygon([p[:2] for p in face]))


@pytest.mark.parametrize('redundant_boundary', [False, True], ids=['clean', 'duplicate'])
def test_formats_identity_georef_hierarchy_and_xml_escaping(export_source, redundant_boundary):
    if redundant_boundary:
        doc = json.loads(export_source.read_text())
        for ring in doc['features'][0]['geometry']['coordinates']:
            ring.insert(1, ring[0][:])
        export_source.write_text(json.dumps(doc))
    before = export_source.read_bytes()
    result = export_file(export_source)
    assert set(result['artifacts']) == {'glb', 'cityjson', 'citygml'}
    assert export_source.read_bytes() == before
    cj = json.loads(export_source.with_suffix('.city.json').read_text())
    assert len([o for o in cj['CityObjects'].values() if o['type'] == 'Building']) == 2
    parts = [o for o in cj['CityObjects'].values() if o['type'] == 'BuildingPart']
    assert len(parts) == 3
    assert any(len(o['geometry']) == 2 and all(g['type'] == 'Solid' for g in o['geometry'])
               for o in parts)
    assert cj['metadata']['referenceSystem'].endswith('/32750')
    vertices = np.array(cj['vertices']) * cj['transform']['scale'] + cj['transform']['translate']
    bbox = cj['metadata']['geographicalExtent']
    assert np.all(vertices >= np.asarray(bbox[:3]) - 1e-9)
    assert np.all(vertices <= np.asarray(bbox[3:]) + 1e-9)
    assert min(vertices[:,2]) == pytest.approx(12)
    assert max(vertices[:,2]) == pytest.approx(29)
    assert vertices[:,0].min() == pytest.approx(700000, abs=.001)
    for part in parts:
        p = part['attributes']
        if p['part_id'] == 'A-P01':
            rings = part['geometry'][0]['boundaries'][0]
            indices = [i for face in rings for ring in face for i in ring]
            assert min(vertices[indices,2]) == pytest.approx(22)
            assert p['parent_part_id'] == 'A-P00'
    gml = ET.parse(export_source.with_suffix('.gml'))
    assert len(gml.findall(f'.//{{{BLDG}}}Building')) == 2
    assert len(gml.findall(f'.//{{{GML}}}Solid')) == 4
    assert gml.find(f'.//{{{GML}}}name').text == 'Mall & <Annex>'
    raw = export_source.with_suffix('.glb').read_bytes()
    magic, version, total = struct.unpack_from('<4sII', raw)
    assert (magic, version, total) == (b'glTF', 2, len(raw))
    length, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    gltf = json.loads(raw[20:20+length])
    assert len(gltf['scenes'][0]['nodes']) == 2
    assert gltf['extras']['origin_projected_m'][2] == 12
    assert gltf['extras']['working_crs'] == 'EPSG:32750'
    child = next(n for n in gltf['nodes'] if n['name'] == 'A-P01')
    assert child['extras']['parent_part_id'] == 'A-P00'
    # Reconstruct upper-part Z in world coordinates from the actual GLB buffer.
    accessor = gltf['accessors'][gltf['meshes'][child['mesh']]['primitives'][0]['attributes']['POSITION']]
    view = gltf['bufferViews'][accessor['bufferView']]
    arr = np.frombuffer(raw, dtype='<f4', count=accessor['count']*3,
                        offset=20+length+8+view['byteOffset']).reshape(-1,3)
    assert arr[:,1].min() + 12 == pytest.approx(22)
    assert arr[:,1].max() + 12 == pytest.approx(29)


def test_cancel_and_writer_failure_publish_nothing(export_source, monkeypatch):
    with pytest.raises(KeyboardInterrupt):
        export_file(export_source, cancel=lambda: True)
    assert not export_source.with_suffix('.glb').exists()
    import atap.exports as exports

    def broken(*args):
        raise RuntimeError('disk full')
    monkeypatch.setattr(exports, '_write_cityjson', broken)
    with pytest.raises(RuntimeError, match='disk full'):
        export_file(export_source)
    assert not export_source.with_suffix('.glb').exists()
    assert not export_source.with_suffix('.exports.json').exists()


def test_invalid_result_rejected(export_source):
    doc = json.loads(export_source.read_text())
    doc['features'][1]['properties']['base_height_agl_m'] = 0
    export_source.write_text(json.dumps(doc))
    with pytest.raises(AtapValidationError):
        export_file(export_source)
    with pytest.raises(AtapInputError):
        export_file(export_source, 'bad')


def test_shell_failure_identifies_part(export_source, monkeypatch):
    import atap.exports as exports

    def broken(*args):
        raise AtapValidationError(['Export shell has open or inconsistently oriented edges.'])
    monkeypatch.setattr(exports, '_mesh', broken)
    with pytest.raises(AtapValidationError, match='A-P00: Export shell'):
        export_file(export_source)
    assert not export_source.with_suffix('.glb').exists()


def test_xml_control_character_rejected_without_publishing(export_source):
    doc = json.loads(export_source.read_text())
    doc['features'][0]['properties']['name'] = 'Bad\u0000name'
    export_source.write_text(json.dumps(doc))
    with pytest.raises(AtapValidationError, match='XML 1.0'):
        export_file(export_source)
    assert not export_source.with_suffix('.glb').exists()


def test_export_cli_selection_and_repeatability(export_source):
    command = [sys.executable, '-m', 'atap', 'export', str(export_source), '--formats', 'glb,cityjson']
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    original = export_source.with_suffix('.glb').read_bytes()
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert original == export_source.with_suffix('.glb').read_bytes()
    assert not export_source.with_suffix('.gml').exists()
