# SPDX-License-Identifier: AGPL-3.0-only
"""Generate small synthetic inputs through the real ATAP API, then real writers."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon, box, mapping
from shapely.ops import transform

from atap import export_file, run_elevation
from atap.engine.config import AtapInputError, AtapValidationError


def generate(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # Artificial metre grid offshore, no real building/client input.
    x, y = 500000, 1000
    project = Transformer.from_crs(32631, 4326, always_xy=True).transform
    square = box(x+10, y+10, x+50, y+50)
    concave = Polygon([(x+10,y+10),(x+50,y+10),(x+50,y+25),
                       (x+25,y+25),(x+25,y+50),(x+10,y+50)])
    courtyard = Polygon(square.exterior.coords, [box(x+22,y+22,x+38,y+38).exterior.coords])
    multipart = MultiPolygon([box(x+8,y+8,x+23,y+23), box(x+37,y+37,x+57,y+57)])
    near = Polygon([(x+10,y+10),(x+50,y+10),(x+50,y+50),(x+10,y+50),
                    (x+10,y+40),(x+10.0001,y+40),(x+10,y+39.9999)])
    cases = [
        ('simple', square, [], None, 1),
        ('stepped', square, [(box(x+20,y+20,x+40,y+40), 20)], None, 2),
        ('courtyard', courtyard, [], None, 1),
        ('concave', concave, [], None, 1),
        ('multipart', multipart, [], None, 1),
        ('stacked', box(x+5,y+5,x+65,y+65),
         [(box(x+15,y+15,x+55,y+55),18),(box(x+25,y+25,x+45,y+45),30)], None, 2),
        ('attributes', square, [], None, 1),
        ('unknown_datum', square, [], None, 1),
        ('known_vertical_crs', square, [], 'EPSG:5709', 1),
        ('near_degenerate', near, [], None, 1),
    ]
    records = []
    grid = from_origin(x, y+80, .5, .5)
    for name, geometry, tiers, datum, expected in cases:
        directory = out / name
        directory.mkdir(exist_ok=True)
        working_crs = 'EPSG:32631'
        if name == 'known_vertical_crs':
            working_crs = 'EPSG:28992'
            geometry = translate(geometry, xoff=155000-x, yoff=463000-y)
            grid = from_origin(155000, 463080, .5, .5)
            project = Transformer.from_crs(28992, 4326, always_xy=True).transform
        else:
            grid = from_origin(x, y+80, .5, .5)
            project = Transformer.from_crs(32631, 4326, always_xy=True).transform
        attributes = dict(id=name, name='Bâtiment & <Annex> 東京', count=3, ratio=1.25,
                          enabled=True, absent=None, tags=['a',2], details={'b':False,'a':1},
                          huge=2**40)
        footprint = directory / 'footprints.geojson'
        footprint.write_text(json.dumps({'type':'FeatureCollection','features':[
            {'type':'Feature','properties':attributes,'geometry':mapping(transform(project,geometry))}
        ]}, ensure_ascii=False), encoding='utf-8')
        heights = rasterize([(mapping(geometry),8), *[(mapping(g), h) for g,h in tiers]],
                            out_shape=(160,160), transform=grid, fill=0, dtype='float32')
        for label, data in [('dtm',np.full((160,160),12,dtype='float32')),('dsm',heights+12)]:
            with rasterio.open(directory/f'{label}.tif','w',driver='GTiff',height=160,width=160,
                               count=1,dtype='float32',crs=working_crs,transform=grid,nodata=-9999) as dst:
                dst.write(data,1)
        source = directory / 'result.geojson'
        run_elevation(footprint, directory/'dtm.tif', directory/'dsm.tif', source,
                      working_crs=working_crs, workers=1, max_height_classes=8,
                      coord_digits=12, vertical_datum=datum, log_cb=lambda _: None)
        before = source.read_bytes()
        doc = json.loads(before)
        assert len(doc['features']) == expected, (name,len(doc['features']),expected)
        record = {'name':name, 'source':str(source), 'parts':expected, 'buildings':1,
                  'canonical_sha256':hashlib.sha256(before).hexdigest()}
        try:
            export_file(source)
            assert name != 'near_degenerate', 'Quantization-negative fixture unexpectedly exported'
            record['expected'] = 'valid'
        except AtapValidationError as exc:
            if name != 'near_degenerate':
                raise
            assert 'quantization collapses' in str(exc), str(exc)
            record.update(expected='reject', reason=str(exc))
            assert not source.with_suffix('.exports.json').exists()
        assert source.read_bytes() == before
        records.append(record)
        print(name, record['expected'], expected, flush=True)
    # Invalid reference must fail without changing the canonical source bytes.
    bad = out/'invalid_crs.geojson'
    doc = json.loads((out/'simple/result.geojson').read_text(encoding='utf-8'))
    doc['processing']['working_crs'] = 'EPSG:4326'
    bad.write_text(json.dumps(doc), encoding='utf-8')
    try:
        export_file(bad)
        raise AssertionError('Invalid CRS unexpectedly exported')
    except AtapInputError as exc:
        records.append({'name':'invalid_crs','expected':'reject','reason':str(exc)})
    (out/'fixtures.json').write_text(json.dumps(records,indent=2), encoding='utf-8')
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    generate(parser.parse_args().out)
