# SPDX-License-Identifier: AGPL-3.0-only
"""Verify sample SHA-256 manifests on Windows, Linux and macOS."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def verify_manifest(manifest):
    manifest = Path(manifest)
    root = manifest.parent.resolve()
    records, seen = [], set()
    for number, line in enumerate(manifest.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or len(fields[0]) != 64 or any(c not in '0123456789abcdef' for c in fields[0]):
            raise ValueError(f'{manifest}:{number}: invalid SHA-256 entry')
        expected, name = fields
        name = name.removeprefix('*')
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or ':' in name or not relative.parts):
            raise ValueError(f'{manifest}:{number}: unsafe relative path {name!r}')
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f'{manifest}:{number}: path escapes sample directory')
        if name in seen:
            raise ValueError(f'{manifest}:{number}: duplicate reference {name}')
        seen.add(name)
        if not path.is_file():
            raise ValueError(f'{manifest}:{number}: missing reference {name}')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise ValueError(f'{manifest}:{number}: SHA-256 mismatch for {name}: {actual} != {expected}')
        records.append({'file': name, 'bytes': path.stat().st_size, 'sha256': actual})
    if not records:
        raise ValueError(f'{manifest}: empty manifest')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests', nargs='*', type=Path)
    args = parser.parse_args()
    manifests = args.manifests or sorted((Path(__file__).resolve().parents[1] / 'samples').glob('*/MANIFEST.sha256'))
    if not manifests:
        parser.exit(1, 'No sample manifests found\n')
    try:
        results = [{'manifest': str(p), 'files': verify_manifest(p)} for p in manifests]
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Sample integrity failed: {exc}\n')
    print(json.dumps({'status': 'PASS', 'samples': results}, indent=2))


if __name__ == '__main__':
    main()
