# SPDX-License-Identifier: AGPL-3.0-only
"""Build evidence for wheel/sdist contents and a fresh, non-editable wheel install."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import venv
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist',type=Path,required=True)
    parser.add_argument('--sample',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    report = {'status':'BLOCKED','steps':[],'distributions':[]}
    try:
        wheel,sdist = list(args.dist.glob('*.whl')),list(args.dist.glob('*.tar.gz'))
        if len(wheel)!=1 or len(sdist)!=1:
            raise ValueError('Expected exactly one wheel and sdist')
        for path in [wheel[0],sdist[0]]:
            report['distributions'].append({'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        with zipfile.ZipFile(wheel[0]) as archive:
            assert 'atap/exports.py' in archive.namelist()
            assert 'atap/server/static/index.html' in archive.namelist()
        with tarfile.open(sdist[0]) as archive:
            assert any(name.endswith('/src/atap/exports.py') for name in archive.getnames())
            assert not any('/.cache/' in name for name in archive.getnames())
        env = args.out/'venv'
        venv.EnvBuilder(with_pip=True).create(env)
        python = (env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')).resolve()
        def run(name,command):
            child = subprocess.run(list(map(str,command)),capture_output=True,cwd=args.out.resolve())
            (args.out/f'{name}.stdout.log').write_bytes(child.stdout)
            (args.out/f'{name}.stderr.log').write_bytes(child.stderr)
            report['steps'].append({'command':list(map(str,command)),'exit_code':child.returncode})
            if child.returncode:
                raise RuntimeError(child.stderr.decode(errors='replace')[-1200:])
        run('install',[python,'-m','pip','install',str(wheel[0].resolve())+'[server]'])
        sample = args.out/'sample.geojson'
        sample.write_bytes(args.sample.read_bytes())
        before = hashlib.sha256(sample.read_bytes()).hexdigest()
        code = ('import atap,pathlib; p=pathlib.Path(atap.__file__).resolve(); '
                'assert "site-packages" in str(p); print(p); print(atap.__version__); '
                'm=atap.export_file("sample.geojson","all"); '
                'assert set(m["artifacts"])=={"glb","cityjson","citygml"}; '
                'assert m["canonical_profile"]=="0.6"')
        run('import-export',[python,'-c',code])
        run('cli',[python,'-m','atap','--version'])
        assert hashlib.sha256(sample.read_bytes()).hexdigest()==before
        report['status']='PASS'
    except Exception as exc:
        report['failure']=str(exc)
    (args.out/'distribution-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
