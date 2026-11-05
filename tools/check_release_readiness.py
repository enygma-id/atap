# SPDX-License-Identifier: AGPL-3.0-only
"""Capture automated metadata, sample-integrity and formal CFF validation evidence.

PASS covers technical checks only. It does not approve dataset rights, confirm
Zenodo account settings, set a publication date, or authorize a release/DOI.
"""
import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--uv', default='uv', help='uv executable used for isolated cffconvert 2.0.0')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'status': 'BLOCKED', 'scope': 'automated technical checks only', 'commands': [],
              'utc_timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
              'human_rights_review': 'not_checked', 'zenodo_enablement': 'not_checked',
              'human_release_approval': False}

    def run(name, command):
        command = list(map(str, command))
        result = subprocess.run(command, capture_output=True)
        logs = {}
        for label, raw in [('stdout', result.stdout), ('stderr', result.stderr)]:
            path = args.out / f'{name}.{label}.log'
            path.write_bytes(raw)
            logs[label] = {'path': str(path), 'sha256': sha(path)}
        report['commands'].append({'command': command, 'exit_code': result.returncode, 'logs': logs})
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}: {result.stderr.decode(errors="replace")[-800:]}')
        return result.stdout.decode('utf-8').strip()

    try:
        report['checked_commit'] = run('commit', ['git', 'rev-parse', 'HEAD'])
        report['working_tree_status'] = run('tree', ['git', 'status', '--porcelain']).splitlines()
        report['ci'] = {'run_id': os.environ.get('GITHUB_RUN_ID'), 'sha': os.environ.get('GITHUB_SHA'),
                        'event': os.environ.get('GITHUB_EVENT_NAME')}
        report['python'] = sys.version
        report['installed_version'] = importlib.metadata.version('atap')
        report['uv'] = run('uv-version', [args.uv, '--version'])
        cff_env = (args.out / 'cff-env').resolve()
        if not cff_env.exists():
            run('cff-environment', [args.uv, 'venv', cff_env, '--python', sys.executable])
        cff_python = cff_env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        run('cff-install', [args.uv, 'pip', 'install', '--python', cff_python,
                            '--require-hashes', '-r', 'requirements/cff.txt'])
        cff = [str(cff_env / ('Scripts/cffconvert.exe' if os.name == 'nt' else 'bin/cffconvert'))]
        report['cffconvert'] = run('cff-version', [*cff, '--version'])
        if '2.0.0' not in report['cffconvert']:
            raise ValueError('Unexpected CFF validator version')
        run('cff-validate', [*cff, '--validate', '--infile', 'CITATION.cff'])
        samples = run('sample-integrity', [sys.executable, 'tools/verify_sample_manifests.py'])
        sample_path = args.out / 'samples.json'
        sample_path.write_text(samples + '\n', encoding='utf-8')
        report['sample_report'] = {'path': str(sample_path), 'sha256': sha(sample_path)}
        run('metadata-tests', [sys.executable, '-m', 'pytest', 'tests/test_release_metadata.py',
                              'tests/test_sample_manifests.py', '-q',
                              f'--junitxml={args.out / "metadata-tests.xml"}'])
        report['files'] = {name: sha(name) for name in ('CITATION.cff', 'pyproject.toml', 'uv.lock')}
        report['status'] = 'PASS'
    except Exception as exc:
        report['failure'] = str(exc)
    finally:
        (args.out / 'readiness-summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'out': str(args.out), 'failure': report.get('failure')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
