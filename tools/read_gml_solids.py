# SPDX-License-Identifier: AGPL-3.0-only
"""Read unchanged CityGML Solid subtrees through GDAL's independent GML reader.

The lightweight feature wrapper avoids GDAL's default Building flattening.
No coordinates, ring order or CRS declarations are repaired or recomputed.
The result is a validation interchange, not an additional ATAP output format.
"""
import ctypes as C
import json
from pathlib import Path

import numpy as np
import pyogrio
from lxml import etree

NS = {'gml':'http://www.opengis.net/gml', 'bldg':'http://www.opengis.net/citygml/building/2.0',
      'gen':'http://www.opengis.net/citygml/generics/2.0'}


class GMLReader:
    def __init__(self):
        libs = Path(pyogrio.__file__).parent.parent / 'pyogrio.libs'
        paths = [*libs.glob('*gdal*.dll'), *libs.glob('libgdal*.so*'), *libs.glob('libgdal*.dylib')]
        if not paths:
            raise RuntimeError('Pinned GDAL reader library is missing.')
        self.lib = C.CDLL(str(paths[0]))
        self.library = str(paths[0])
        # GDAL otherwise intentionally strips vertical CRS metadata on GML read.
        self.function('CPLSetConfigOption', None, [C.c_char_p,C.c_char_p])(b'GML_REPORT_COMPD_CS',b'YES')
        self.open = self.function('GDALOpenEx', C.c_void_p, [C.c_char_p,C.c_uint,C.c_void_p,C.c_void_p,C.c_void_p])
        self.close = self.function('GDALClose', None, [C.c_void_p])
        self.layer = self.function('GDALDatasetGetLayer', C.c_void_p, [C.c_void_p,C.c_int])
        self.next = self.function('OGR_L_GetNextFeature', C.c_void_p, [C.c_void_p])
        self.destroy = self.function('OGR_F_Destroy', None, [C.c_void_p])
        self.geom = self.function('OGR_F_GetGeometryRef', C.c_void_p, [C.c_void_p])
        self.child = self.function('OGR_G_GetGeometryRef', C.c_void_p, [C.c_void_p,C.c_int])
        self.count = self.function('OGR_G_GetGeometryCount', C.c_int, [C.c_void_p])
        self.point_count = self.function('OGR_G_GetPointCount', C.c_int, [C.c_void_p])
        self.dimension = self.function('OGR_G_GetCoordinateDimension', C.c_int, [C.c_void_p])
        self.srs = self.function('OGR_L_GetSpatialRef', C.c_void_p, [C.c_void_p])
        self.axes_count = self.function('OSRGetAxesCount', C.c_int, [C.c_void_p])
        self.axes = []
        self.xyz = [self.function('OGR_G_Get'+axis, C.c_double, [C.c_void_p,C.c_int]) for axis in 'XYZ']
        self.version = self.function('GDALVersionInfo', C.c_char_p, [C.c_char_p])(b'RELEASE_NAME').decode()
        self.function('GDALAllRegister', None, [])()

    def function(self, name, restype, args):
        function = getattr(self.lib, name)
        function.restype, function.argtypes = restype, args
        return function

    def read(self, path):
        dataset = self.open(str(Path(path).resolve()).encode(), 4, None, None, None)
        if not dataset:
            raise ValueError(f'GDAL cannot open GML solid: {path}')
        try:
            layer = self.layer(dataset, 0)
            srs = self.srs(layer)
            if not srs:
                raise ValueError('GDAL could not resolve the declared GML CRS.')
            self.axes.append(self.axes_count(srs))
            feature = self.next(layer)
            if not feature:
                raise ValueError('GDAL did not read a feature.')
            try:
                geometry = self.geom(feature)
                if not geometry or self.dimension(geometry) != 3:
                    raise ValueError('GDAL did not preserve three-dimensional geometry.')
                faces = []
                for i in range(self.count(geometry)):
                    polygon = self.child(geometry, i)
                    if self.count(polygon) != 1:
                        raise ValueError('Reader expects one ring per triangulated export face.')
                    ring = self.child(polygon, 0)
                    points = [[axis(ring,j) for axis in self.xyz] for j in range(self.point_count(ring))]
                    if len(points) < 4 or points[0] != points[-1]:
                        raise ValueError('GDAL ring is empty or not closed.')
                    faces.append(points[:-1])
                if not faces:
                    raise ValueError('GDAL discarded GML solid faces.')
                return faces
            finally:
                self.destroy(feature)
        finally:
            self.close(dataset)


def extract(path, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    reader = GMLReader()
    tree = etree.parse(str(path), etree.XMLParser(no_network=True, resolve_entities=False))
    parts, objects, vertices, lookup = {}, {}, [], {}
    ids = tree.xpath('//@gml:id', namespaces=NS)
    if len(ids) != len(set(ids)):
        raise ValueError('GML IDs are not unique.')
    for node in tree.xpath('//bldg:BuildingPart[gen:stringAttribute[@name="part_id"]]', namespaces=NS):
        pid = node.xpath('string(gen:stringAttribute[@name="part_id"]/gen:value)', namespaces=NS)
        oid = node.xpath('string(gen:stringAttribute[@name="object_id"]/gen:value)', namespaces=NS)
        solids = node.xpath('.//gml:Solid', namespaces=NS)
        if not solids:
            raise ValueError(f'{pid}: required ATAP derived solid is missing (even if optional in XSD).')
        faces_per_solid = []
        for index, solid in enumerate(solids):
            wrapper = etree.Element('{urn:atap:validation}FeatureCollection', nsmap={'v':'urn:atap:validation','gml':NS['gml']})
            member = etree.SubElement(wrapper,'{'+NS['gml']+'}featureMember')
            feature = etree.SubElement(member,'{urn:atap:validation}geometry')
            prop = etree.SubElement(feature,'{urn:atap:validation}shape')
            # Reparse a byte copy so the actual output tree is never modified.
            prop.append(etree.fromstring(etree.tostring(solid)))
            fragment = out / f'solid-{len(parts)}-{index}.gml'
            etree.ElementTree(wrapper).write(str(fragment), encoding='utf-8',xml_declaration=True)
            faces = reader.read(fragment)
            raw_rings = solid.xpath('.//gml:posList/text()', namespaces=NS)
            expected = [[float(v) for v in ring.split()] for ring in raw_rings]
            if len(expected) != len(faces):
                raise ValueError(f'{pid}: GDAL changed the face count.')
            for ring, face in zip(expected, faces):
                flat = [v for p in face+face[:1] for v in p]
                if ring != flat:
                    raise ValueError(f'{pid}: GDAL changed ring coordinates/order.')
            faces_per_solid.append(faces)
        parts[pid] = faces_per_solid
        bid = 'building:'+oid
        objects.setdefault(bid, {'type':'Building','children':[]})['children'].append(pid)
        geometries = []
        for faces in faces_per_solid:
            surfaces = []
            for face in faces:
                ring = []
                for point in face:
                    key = tuple(point)
                    if key not in lookup:
                        lookup[key] = len(vertices)
                        vertices.append(point)
                    ring.append(lookup[key])
                surfaces.append([ring])
            geometries.append({'type':'Solid','lod':'1','boundaries':[surfaces]})
        objects[pid] = {'type':'BuildingPart','parents':[bid],'geometry':geometries}
    if not parts:
        raise ValueError('No ATAP BuildingPart solids read.')
    # Match the GML writer's nine-decimal serialization, not measurement accuracy.
    origin = np.asarray(vertices).min(axis=0)
    encoded = np.rint((np.asarray(vertices)-origin)/1e-9).astype(np.int64).tolist()
    interchange = {'type':'CityJSON','version':'1.1','transform':{'scale':[1e-9]*3,'translate':origin.tolist()},
                   'CityObjects':objects,'vertices':encoded}
    return parts, interchange, {'tool':'GDAL GML via pyogrio library','version':reader.version,
                                'solid_count':sum(map(len,parts.values())), 'dimensions':3,
                                'crs_axes':reader.axes, 'interchange_quantum_m':1e-9,
                                'gdal_config':{'GML_REPORT_COMPD_CS':'YES'}}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    parts, interchange, info = extract(args.path, args.out)
    (args.out/'gdal-solids.city.json').write_text(json.dumps(interchange,allow_nan=False),encoding='utf-8')
    print(json.dumps(info,indent=2))
