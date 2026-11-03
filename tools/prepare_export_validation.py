# SPDX-License-Identifier: AGPL-3.0-only
"""Fetch the complete pinned schema graph; no network is used by validation."""
import argparse
import hashlib
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

GML_ROOT = 'https://schemas.opengis.net/citygml/profiles/base/2.0/CityGML.xsd'
CJ_ROOT = 'https://raw.githubusercontent.com/cityjson/specs/1.1.3/schemas/cityjson.schema.json'
DEFAULT_LOCK = Path(__file__).with_name('export-validation-lock.json')


def normalize(url):
    if url.startswith('http://'):
        return 'https://' + url[7:]
    return url


def file_name(url):
    return hashlib.sha256(normalize(url).encode()).hexdigest()


def fetch(url):
    with urllib.request.urlopen(normalize(url), timeout=45) as response:
        return response.read()


def prepare(cache, lock_path=DEFAULT_LOCK, record=False):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    if record:
        pending = [(GML_ROOT, 'xsd'), (CJ_ROOT, 'json-schema')]
        sources = {}
        while pending:
            url, kind = pending.pop()
            url = normalize(url.split('#')[0])
            if url in sources:
                continue
            data = fetch(url)
            sources[url] = {'url': url, 'kind': kind, 'bytes': len(data),
                            'sha256': hashlib.sha256(data).hexdigest()}
            (cache / file_name(url)).write_bytes(data)
            print(f'PIN {kind} {url} {sources[url]["sha256"]}', flush=True)
            if kind == 'xsd':
                for element in ET.fromstring(data).iter():
                    location = element.get('schemaLocation')
                    if location:
                        pending.append((urllib.parse.urljoin(url, location), kind))
            else:
                def visit(node):
                    if isinstance(node, dict):
                        ref = node.get('$ref', '').split('#')[0]
                        if ref:
                            pending.append((urllib.parse.urljoin(url, ref), kind))
                        for value in node.values():
                            visit(value)
                    elif isinstance(node, list):
                        for value in node:
                            visit(value)
                visit(json.loads(data))
        lock = {'citygml_root': GML_ROOT, 'cityjson_root': CJ_ROOT,
                'schema_versions': {'cityjson': '1.1.3', 'citygml': '2.0', 'gml': '3.1.1'},
                'schema_licenses': {'cityjson': 'CC0-1.0',
                                    'citygml_gml': 'OGC Software Notice (embedded in schemas)',
                                    'xal': 'OASIS copyright notice (embedded in schema)',
                                    'w3c': 'W3C Software and Document Notice (embedded)'},
                'tools': {'cjval': {'version': '0.10.0', 'commit': '40db6dd698cfe9de5a88a4a1aac4a5173095d86f'},
                          'val3dity': {'version': '2.7.0', 'commit': 'fbe9e4d65376e1c3f63401f15967485783f78c0a',
                                       'windows_zip_sha256': 'cf8d3f025cd52aafc9ea370296a2430baa4aa39ce44a8b3ba1d8b3a540d8a5a7'}},
                'sources': sorted(sources.values(), key=lambda s: s['url'])}
        Path(lock_path).write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    else:
        lock = json.loads(Path(lock_path).read_text(encoding='utf-8'))
        for source in lock['sources']:
            path = cache / file_name(source['url'])
            data = path.read_bytes() if path.exists() else fetch(source['url'])
            if hashlib.sha256(data).hexdigest() != source['sha256']:
                raise ValueError(f'Schema hash mismatch: {source["url"]}')
            path.write_bytes(data)
    return lock


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    parser.add_argument('--record', action='store_true', help='Maintainer-only bootstrap; review resulting pins')
    args = parser.parse_args()
    manifest = prepare(args.cache, args.lock, args.record)
    print(f'Verified {len(manifest["sources"])} schema files')
