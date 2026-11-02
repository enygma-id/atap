# SPDX-License-Identifier: AGPL-3.0-only
"""Independent, fail-closed conformance gates over freshly generated artifacts.

No ATAP mesh/writer helpers are imported. cjval, val3dity, GDAL, cjio, trimesh,
the complete official XSD graph and Khronos glTF Validator inspect actual bytes.
"""
import argparse
import copy
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import trimesh
from cjio import cityjson
from lxml import etree
from pyproj import Transformer
from read_gml_solids import NS, extract
from shapely.geometry import Polygon, shape
from shapely.ops import transform


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, out, name, check=True):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(a) for a in command], capture_output=True)
    logs = {}
    for key, raw in [('stdout',result.stdout),('stderr',result.stderr)]:
        path = out/f'{name}.{key}.log'
        path.write_bytes(raw)
        logs[key] = {'file':str(path),'sha256':sha(path)}
    report = {'command':[str(a) for a in command],'exit_code':result.returncode,'logs':logs,
              'utc_timestamp':dt.datetime.now(dt.timezone.utc).isoformat()}
    (out/f'{name}.command.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if check and result.returncode:
        raise RuntimeError(f'{name} exited {result.returncode}: {result.stderr.decode(errors="replace")[-800:]}')
    return result.stdout


def require_val3dity(report_path):
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    if (report.get('validity') is not True or report.get('all_errors') != []
            or report.get('dataset_errors') != [] or not report.get('features')):
        raise ValueError(f'val3dity rejected actual geometry: {report.get("all_errors")}')
    if any(f.get('validity') is not True for f in report['features']):
        raise ValueError('Invalid val3dity feature despite a zero process exit code.')
    return report


def check_shells(shells, feature, working_crs, quantum):
    properties = feature['properties']
    projected = transform(Transformer.from_crs(4326,working_crs,always_xy=True).transform,
                          shape(feature['geometry']))
    expected_components = 1 if projected.geom_type == 'Polygon' else len(projected.geoms)
    if len(shells) != expected_components:
        raise ValueError(f'{properties["part_id"]}: disconnected component count changed')
    vertices, indices, triangles = [], {}, []
    for shell in shells:
        for face in shell:
            ring = []
            for point in face:
                key = tuple(point)
                if key not in indices:
                    indices[key] = len(vertices)
                    vertices.append(point)
                ring.append(indices[key])
            for i in range(1,len(ring)-1):
                triangles.append([ring[0],ring[i],ring[i+1]])
            if max(p[2] for p in face)-min(p[2] for p in face) <= quantum:
                cap = Polygon([p[:2] for p in face])
                if not projected.buffer(math.sqrt(2)*quantum+1e-8).covers(cap):
                    raise ValueError(f'{properties["part_id"]}: cap fills a courtyard or concavity')
    vertices = np.asarray(vertices,dtype=float)
    if not np.isfinite(vertices).all():
        raise ValueError('Non-finite decoded vertices')
    reference = vertices.min(axis=0)
    mesh = trimesh.Trimesh(vertices=vertices-reference,faces=triangles,process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        raise ValueError(f'{properties["part_id"]}: independent mesh check failed')
    base, top = properties['base_elevation_m'], properties['top_elevation_m']
    height = top-base
    expected = projected.area*height
    tolerance = (2*projected.area+projected.length*height)*math.sqrt(3)*quantum + expected*1e-8
    if mesh.volume <= 0 or abs(mesh.volume-expected) > max(tolerance,1e-7):
        raise ValueError(f'{properties["part_id"]}: volume {mesh.volume} != {expected} +/- {tolerance}')
    bounds = np.array([*projected.bounds[:2],base,*projected.bounds[2:],top])
    actual = np.r_[vertices.min(axis=0),vertices.max(axis=0)]
    if not np.allclose(bounds,actual,rtol=0,atol=quantum+1e-7):
        raise ValueError(f'{properties["part_id"]}: decoded XYZ bounds changed')
    digits = properties.get('round_digits',2)
    measure_tolerance = projected.area*10**-digits + height*.5*10**-digits + .5*10**-digits
    if abs(properties['volume_m3']-expected) > measure_tolerance+tolerance:
        raise ValueError('Canonical volume and serialized geometry disagree beyond rounding bounds')
    return {'part_id':properties['part_id'],'shells':len(shells),'vertices':len(vertices),
            'watertight':bool(mesh.is_watertight),'winding_consistent':bool(mesh.is_winding_consistent),
            'volume_m3':float(mesh.volume),'expected_volume_m3':expected,
            'volume_tolerance_m3':float(tolerance),'bounds':actual.tolist(),
            'interior_rings':sum(len(p.interiors) for p in ([projected] if projected.geom_type=='Polygon' else projected.geoms))}


def check_cityjson(cj, canonical):
    if cj['version'] != '1.1' or cj['type'] != 'CityJSON':
        raise ValueError('Unexpected CityJSON target version')
    authority = json.loads(Path('tests/fixtures/exports/cityjson-1.1.3.schema.json').read_text(encoding='utf-8'))
    if set(cj)-set(authority['properties']):
        raise ValueError('Unregistered CityJSON root members')
    reader = cityjson.CityJSON(j=copy.deepcopy(cj))
    reader.load_from_j(transform=True)
    original = {f['properties']['part_id']:f for f in canonical['features']}
    objects = cj['CityObjects']
    parts = [o for o in objects.values() if o['type']=='BuildingPart']
    if len(parts) != len(original):
        raise ValueError('CityJSON part count changed')
    reports = []
    for cid,part in objects.items():
        if part['type'] != 'BuildingPart':
            continue
        feature = original[part['attributes']['part_id']]
        if part['attributes'] != feature['properties']:
            raise ValueError('CityJSON attribute values/types changed')
        for parent in part['parents']:
            if cid not in objects[parent]['children']:
                raise ValueError('CityJSON nonreciprocal hierarchy')
        shells = []
        for geometry in reader.cityobjects[cid].geometry:
            if geometry.type != 'Solid' or str(geometry.lod) != '1' or len(geometry.boundaries) != 1:
                raise ValueError('Unexpected primitive/LoD/interior solid shell')
            faces = []
            for surface in geometry.boundaries[0]:
                if len(surface) != 1:
                    raise ValueError('Unexpected triangulated face holes')
                faces.append(surface[0])
            shells.append(faces)
        reports.append(check_shells(shells,feature,canonical['processing']['working_crs'],.001))
    vertices = np.asarray(cj['vertices'])*cj['transform']['scale']+cj['transform']['translate']
    if not np.allclose(np.r_[vertices.min(axis=0),vertices.max(axis=0)],cj['metadata']['geographicalExtent'],rtol=0,atol=1e-8):
        raise ValueError('CityJSON decoded bbox is incorrect')
    buildings = sum(o['type']=='Building' for o in objects.values())
    if buildings != len(set(f['properties']['object_id'] for f in original.values())):
        raise ValueError('CityJSON building count changed')
    return reports


def check_glb(path, canonical):
    raw = Path(path).read_bytes()
    length = struct.unpack_from('<I',raw,12)[0]
    gltf = json.loads(raw[20:20+length])
    origin = np.array(gltf['extras']['origin_projected_m'])
    scene = trimesh.load_scene(path,process=False)
    reports = []
    for feature in canonical['features']:
        pid = feature['properties']['part_id']
        matrix, name = scene.graph[pid]
        geometry = scene.geometry[name]
        points = trimesh.transform_points(geometry.vertices,matrix)
        quantum = max(float(np.abs(points).max()),1)*np.finfo(np.float32).eps*2
        xyz = np.column_stack((points[:,0],-points[:,2],points[:,1]))+origin
        # Split each actual mesh component independently, retaining raw winding.
        mesh = trimesh.Trimesh(vertices=xyz,faces=geometry.faces,process=False)
        mesh.merge_vertices(digits_vertex=10)
        shells = [[component.vertices[face].tolist() for face in component.faces]
                  for component in mesh.split(only_watertight=False)]
        reports.append(check_shells(shells,feature,canonical['processing']['working_crs'],quantum))
    return reports


def check_gml_attributes(path, canonical):
    tree = etree.parse(str(path),etree.XMLParser(resolve_entities=False,no_network=True))
    expected = {f['properties']['part_id']:f['properties'] for f in canonical['features']}
    for node in tree.xpath('//bldg:BuildingPart[gen:stringAttribute[@name="part_id"]]',namespaces=NS):
        elements = node.xpath('gen:*',namespaces=NS)
        entries = {e.get('name'):(etree.QName(e).localname,e.findtext('gen:value',namespaces=NS) or '') for e in elements}
        if len(entries) != len(elements):
            raise ValueError('Duplicate generic attribute names')
        pid = entries['part_id'][1]
        props = expected[pid]
        keys = {k for k,v in props.items() if v is not None and not (k=='name' and isinstance(v,str) and v)}
        if set(entries) != keys:
            raise ValueError(f'{pid}: GML attributes missing or unexpected')
        for key in keys:
            kind,text = entries[key]
            value = props[key]
            if isinstance(value,bool):
                wanted, decoded = 'stringAttribute', text == str(value).lower()
            elif isinstance(value,int) and -(2**31) <= value < 2**31:
                wanted, decoded = 'intAttribute', int(text) == value
            elif isinstance(value,float):
                wanted, decoded = 'doubleAttribute', math.isfinite(float(text)) and float(text)==value
            elif isinstance(value,(dict,list)):
                wanted, decoded = 'stringAttribute', json.loads(text)==value
            else:
                wanted, decoded = 'stringAttribute', text==str(value)
            if kind != wanted or not decoded:
                raise ValueError(f'{pid}: GML generic {key} changed type/value or is non-finite')
        if isinstance(props.get('name'),str) and props['name']:
            if node.findtext('gml:name',namespaces=NS) != props['name']:
                raise ValueError(f'{pid}: GML name changed')


def validate_fixture(source, out, schema_cache, cjval, val3dity, gltf_module):
    source, out = Path(source), Path(out)
    out.mkdir(parents=True,exist_ok=True)
    canonical = json.loads(source.read_text(encoding='utf-8'))
    manifest = json.loads(source.with_suffix('.exports.json').read_text(encoding='utf-8'))
    original_hash = sha(source)
    if original_hash != manifest['source_sha256'] or manifest['canonical_profile'] != '0.6':
        raise ValueError('Manifest canonical source/profile mismatch')
    for artifact in manifest['artifacts'].values():
        path = source.parent/artifact['file']
        if path.parent != source.parent or sha(path) != artifact['sha256'] or path.stat().st_size != artifact['bytes']:
            raise ValueError('Manifest final artifact hash/path mismatch')
    cj_path, gml_path, glb_path = (source.with_suffix(suffix) for suffix in ('.city.json','.gml','.glb'))
    cj_stdout = run([cjval,'-r',cj_path],out,'cjval')
    cj_report = json.loads(cj_stdout)
    (out/'cjval.report.json').write_bytes(cj_stdout)
    if cj_report.get('valid') is not True or cj_report.get('has_warnings') is not False:
        raise ValueError('cjval errors or unapproved warnings')
    for input_path,label in [(cj_path,'cityjson')]:
        report = out/f'{label}.val3dity.report.json'
        report.unlink(missing_ok=True)
        run([val3dity,input_path,'--report',report],out,label+'-val3dity')
        require_val3dity(report)
    schema_stdout = run([sys.executable,'tools/validate_citygml.py',gml_path,
                         '--schema-cache',schema_cache],out,'citygml-xsd')
    schema_report = json.loads(schema_stdout)
    (out/'citygml-xsd.report.json').write_text(json.dumps(schema_report,indent=2),encoding='utf-8')
    check_gml_attributes(gml_path,canonical)
    gml_parts, interchange, reader_report = extract(gml_path,out/'gdal-solids')
    converted = out/'gdal-solids.city.json'
    converted.write_text(json.dumps(interchange,allow_nan=False),encoding='utf-8')
    report = out/'citygml.val3dity.report.json'
    report.unlink(missing_ok=True)
    run([val3dity,converted,'--report',report],out,'citygml-val3dity')
    require_val3dity(report)
    gml_reports = []
    if set(gml_parts) != {f['properties']['part_id'] for f in canonical['features']}:
        raise ValueError('GML reader part identities changed')
    for feature in canonical['features']:
        pid = feature['properties']['part_id']
        gml_reports.append(check_shells(gml_parts[pid],feature,canonical['processing']['working_crs'],1e-9))
    expected_axes = 3 if manifest['coordinate_reference']['vertical_status']=='explicit_crs' else 2
    if set(reader_report['crs_axes']) != {expected_axes}:
        raise ValueError('Independent GML reader disagrees with declared CRS dimensions')
    glb_report = out/'khronos.report.json'
    glb_report.unlink(missing_ok=True)
    run(['node','tools/validate_glb.cjs',gltf_module,glb_path,glb_report],out,'khronos')
    issues = json.loads(glb_report.read_text(encoding='utf-8'))['issues']
    if issues['numErrors'] or issues['numWarnings']:
        raise ValueError('Khronos report has errors or unapproved warnings')
    result = {'status':'PASS','source_sha256':original_hash,'artifacts':manifest['artifacts'],
              'cityjson':check_cityjson(json.loads(cj_path.read_text(encoding='utf-8')),canonical),
              'citygml':gml_reports,'gml_reader':reader_report,'glb':check_glb(glb_path,canonical),
              'warnings':manifest['warnings'], 'warnings_disposition':'int32 overflow is retained as documented string',
              'coordinate_reference':manifest['coordinate_reference']}
    result['reports'] = {p.name:{'file':str(p),'sha256':sha(p)} for p in out.glob('*.report.json')
                         if p.name != 'semantics.report.json'}
    if sha(source) != original_hash:
        raise ValueError('Source GeoJSON bytes were modified')
    (out/'semantics.report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--schema-cache',type=Path,required=True)
    parser.add_argument('--cjval',required=True)
    parser.add_argument('--val3dity',required=True)
    parser.add_argument('--gltf-module',required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    summary = {'status':'BLOCKED','utc_timestamp':dt.datetime.now(dt.timezone.utc).isoformat(),
               'fixtures':[], 'versions':{}, 'failures':[]}
    try:
        summary['checked_commit'] = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        summary['working_tree_status'] = subprocess.check_output(['git','status','--porcelain'],text=True).splitlines()
        summary['schema_lock_sha256'] = sha('tools/export-validation-lock.json')
        summary['ci'] = {'run_id':os.environ.get('GITHUB_RUN_ID'),'sha':os.environ.get('GITHUB_SHA'),
                         'event':os.environ.get('GITHUB_EVENT_NAME')}
        event_path = os.environ.get('GITHUB_EVENT_PATH')
        if event_path:
            event = json.loads(Path(event_path).read_text(encoding='utf-8'))
            if 'pull_request' in event:
                summary['ci']['pr_head'] = event['pull_request']['head']['sha']
                summary['ci']['pr_base'] = event['pull_request']['base']['sha']
        for name,command in [('cjval',[args.cjval,'--version']),('val3dity',[args.val3dity,'--version'])]:
            summary['versions'][name] = run(command,args.out,name+'-version').decode().strip()
            summary['versions'][name+'_binary_sha256'] = sha(shutil.which(str(command[0])) or command[0])
        if '0.10.0' not in summary['versions']['cjval'] or '2.7.0' not in summary['versions']['val3dity']:
            raise ValueError('Validator versions differ from the pinned toolchain')
        summary['versions']['python'] = sys.version
        for package in ('lxml','pyogrio','cjio','trimesh','numpy','pyproj'):
            summary['versions'][package] = importlib.metadata.version(package)
        module = Path(args.gltf_module)
        package = json.loads((module/'package.json').read_text())
        if package['version'] != '2.0.0-dev.3.10':
            raise ValueError('Khronos validator version differs from pin')
        summary['versions']['gltf_validator'] = package['version']
        summary['versions']['gltf_validator_sha256'] = sha(module/package['main'])
        records = json.loads((args.fixtures/'fixtures.json').read_text(encoding='utf-8'))
        for record in records:
            if record['expected'] != 'valid':
                continue
            name = record['name']
            source = args.fixtures/name/'result.geojson'
            if sha(source) != record['canonical_sha256']:
                raise ValueError('Canonical fixture source changed since generation')
            before = json.loads(source.with_suffix('.exports.json').read_text(encoding='utf-8'))
            run([sys.executable,'-m','atap','export',source,'--formats','all'],args.out/name,'repeat-export')
            after = json.loads(source.with_suffix('.exports.json').read_text(encoding='utf-8'))
            if before != after:
                raise ValueError('Repeated writer run changed manifest/artifact hashes in the same environment')
            result = validate_fixture(source,args.out/name,
                                      args.schema_cache,args.cjval,args.val3dity,args.gltf_module)
            summary['fixtures'].append({'name':name,'status':result['status'],
                                        'semantics_report_sha256':sha(args.out/name/'semantics.report.json')})
            print('PASS',name,flush=True)
        if len(summary['fixtures']) != 9:
            raise ValueError('Expected all nine positive generated fixtures')
        summary['status'] = 'PASS'
    except Exception as exc:
        summary['failures'].append(str(exc))
        print('FAIL',str(exc),file=sys.stderr,flush=True)
    finally:
        (args.out/'conformance-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return 0 if summary['status']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
