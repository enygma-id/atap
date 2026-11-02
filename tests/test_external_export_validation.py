# SPDX-License-Identifier: AGPL-3.0-only
"""Required in export-conformance CI; ordinary installs need no QA dependencies."""
import json
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('ATAP_CONFORMANCE') != '1',
                                reason='Independent toolchain runs in export-conformance CI')


@pytest.fixture(scope='module')
def gates():
    sys.path.insert(0,str(Path('tools').resolve()))
    import validate_exports
    from validate_citygml import schema
    root = Path(os.environ.get('ATAP_EXPORT_FIXTURES','.cache/release-evidence/fixtures-linux'))
    cache = Path(os.environ.get('ATAP_SCHEMA_CACHE','.cache/export-validation-schemas'))
    # Missing tools, graph, fixtures and environment are failures in the required job.
    assert (root/'fixtures.json').is_file()
    return validate_exports, schema(cache), root


@pytest.mark.parametrize('mutation',['namespace','order','id','ring','int-type','xml-character'])
def test_official_full_xsd_rejects_corruption(gates,tmp_path,mutation):
    from lxml import etree
    tool,xsd,root = gates
    from read_gml_solids import NS
    tree = etree.parse(str(root/'simple/result.gml'))
    node = tree.xpath('//bldg:BuildingPart',namespaces=NS)[0]
    if mutation == 'namespace':
        node.tag = '{urn:invalid}BuildingPart'
    elif mutation == 'order':
        name = node.find('gml:name',namespaces=NS)
        node.remove(name)
        node.append(name)
    elif mutation == 'id':
        node.set('{'+NS['gml']+'}id','not a valid ID')
    elif mutation == 'ring':
        ring = tree.xpath('//gml:LinearRing',namespaces=NS)[0]
        ring.getparent().remove(ring)
    elif mutation == 'int-type':
        tree.xpath('//gen:intAttribute/gen:value',namespaces=NS)[0].text = '1.5'
    path = tmp_path/(mutation+'.gml')
    tree.write(str(path),encoding='utf-8')
    if mutation == 'xml-character':
        path.write_bytes(path.read_bytes().replace(b'Annex',b'Bad\x00Annex'))
    with pytest.raises((etree.DocumentInvalid,etree.XMLSyntaxError)):
        xsd.assertValid(etree.parse(str(path)))


def test_optional_standard_geometry_is_required_by_export_profile(gates,tmp_path):
    from lxml import etree
    from read_gml_solids import NS, extract
    tool,xsd,root = gates
    tree = etree.parse(str(root/'simple/result.gml'))
    for container in tree.xpath('//bldg:lod1Solid',namespaces=NS):
        container.getparent().remove(container)
    path = tmp_path/'missing.gml'
    tree.write(str(path))
    # CityGML itself permits no geometry, but ATAP's derived-solid profile does not.
    xsd.assertValid(etree.parse(str(path)))
    with pytest.raises(ValueError,match='required ATAP derived solid is missing'):
        extract(path,tmp_path/'reader')


def test_schema_numeric_nan_is_rejected_by_semantic_gate(gates,tmp_path):
    from lxml import etree
    from read_gml_solids import NS
    tool,xsd,root = gates
    tree = etree.parse(str(root/'simple/result.gml'))
    tree.xpath('//gen:doubleAttribute[@name="part_height_m"]/gen:value',namespaces=NS)[0].text = 'NaN'
    path = tmp_path/'nan.gml'
    tree.write(str(path))
    xsd.assertValid(etree.parse(str(path)))  # xs:double permits NaN; measured values must not.
    canonical = json.loads((root/'simple/result.geojson').read_text(encoding='utf-8'))
    with pytest.raises(ValueError,match='non-finite'):
        tool.check_gml_attributes(path,canonical)


@pytest.mark.parametrize('mutation',['root','parent','index'])
def test_cjval_rejects_bad_roots_and_references(gates,tmp_path,mutation):
    tool,xsd,root = gates
    doc = json.loads((root/'simple/result.city.json').read_text(encoding='utf-8'))
    part = next(o for o in doc['CityObjects'].values() if o['type']=='BuildingPart')
    if mutation == 'root':
        doc['atap'] = {'invalid_root':True}
    elif mutation == 'parent':
        part['parents'] = ['does-not-exist']
    else:
        part['geometry'][0]['boundaries'][0][0][0][0] = len(doc['vertices'])+100
    path = tmp_path/'bad.city.json'
    path.write_text(json.dumps(doc),encoding='utf-8')
    report = json.loads(tool.run([os.environ['CJVAL'],'-r',path],tmp_path,'negative-cjval',check=False))
    assert report.get('valid') is False or report.get('has_warnings') is True


@pytest.mark.parametrize('mutation',['winding','overlap'])
def test_val3dity_negative_geometry_and_no_disabled_overlap(gates,tmp_path,mutation):
    tool,xsd,root = gates
    doc = json.loads((root/'stepped/result.city.json').read_text(encoding='utf-8'))
    parts = [o for o in doc['CityObjects'].values() if o['type']=='BuildingPart']
    if mutation == 'winding':
        parts[0]['geometry'][0]['boundaries'][0][0][0].reverse()
    else:
        upper = max(parts,key=lambda p:p['attributes']['base_elevation_m'])
        def indices(node):
            if isinstance(node,int):
                return {node}
            return set().union(*(indices(value) for value in node))
        for i in indices(upper['geometry'][0]['boundaries']):
            doc['vertices'][i][2] -= 2000  # Two metres of true interior overlap.
    path,report = tmp_path/'bad.city.json',tmp_path/'val3dity.report.json'
    path.write_text(json.dumps(doc),encoding='utf-8')
    tool.run([os.environ['VAL3DITY'],path,'--report',report],tmp_path,'negative-val3dity',check=False)
    parsed = json.loads(report.read_text())
    assert parsed['validity'] is False and parsed['all_errors']
    if mutation == 'overlap':
        assert 601 in parsed['all_errors']
    with pytest.raises(ValueError):
        tool.require_val3dity(report)


def test_missing_validator_or_report_fails_closed(gates,tmp_path):
    tool,xsd,root = gates
    with pytest.raises(FileNotFoundError):
        tool.run([str(tmp_path/'not-a-validator')],tmp_path,'missing')
    with pytest.raises(FileNotFoundError):
        tool.require_val3dity(tmp_path/'missing.json')
    false = tmp_path/'false.json'
    false.write_text(json.dumps({'validity':True,'all_errors':[],'dataset_errors':[],'features':[]}))
    with pytest.raises(ValueError):
        tool.require_val3dity(false)


def test_incomplete_catalog_is_not_a_schema_pass(gates,tmp_path):
    from validate_citygml import schema
    with pytest.raises(FileNotFoundError):
        schema(tmp_path/'empty-cache')
