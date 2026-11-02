# SPDX-License-Identifier: AGPL-3.0-only
"""Reproduce exact canonical equivalence for worker counts 1 and 2."""
import argparse
import json
from pathlib import Path

from atap import run_elevation
from compare_outputs import canonical, diff
from run_baselines import CASES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    reports = []
    for name,dataset,footprints,params in (CASES[0],CASES[-1]):
        source = args.data/dataset
        files = []
        for workers in (1,2):
            target = args.out/f'workers-{workers}'/f'{name}.geojson'
            target.parent.mkdir(parents=True,exist_ok=True)
            run_elevation(source/footprints,source/'dtm.tif',source/'dsm.tif',target,
                          workers=workers,log_cb=lambda _:None,**params)
            files.append(target)
        differences = diff(canonical(files[0]),canonical(files[1]))
        reports.append({'case':name,'workers':[1,2],'result':'EQUIVALENT' if not differences else 'DIFFERENT',
                        'differences':differences})
        print(name,reports[-1]['result'],flush=True)
    (args.out/'worker-equivalence.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    return 1 if any(r['differences'] for r in reports) else 0


if __name__=='__main__':
    raise SystemExit(main())
