# SPDX-License-Identifier: AGPL-3.0-only
"""Validate actual CityGML bytes against the complete pinned official 2.0 XSD."""
import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree
from prepare_export_validation import DEFAULT_LOCK, file_name, normalize


def schema(cache, lock_path=DEFAULT_LOCK):
    lock = json.loads(Path(lock_path).read_text(encoding='utf-8'))
    data = {}
    for source in lock['sources']:
        if source['kind'] != 'xsd':
            continue
        path = Path(cache) / file_name(source['url'])
        raw = path.read_bytes()  # Missing dependencies are fatal, never fetched here.
        if hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise ValueError(f'Schema hash mismatch: {source["url"]}')
        data[normalize(source['url'])] = raw

    class Catalog(etree.Resolver):
        def resolve(self, url, public_id, context):
            key = normalize(url)
            if key not in data:
                raise OSError(f'Unpinned schema dependency: {url}')
            return self.resolve_string(data[key], context, base_url=key)

    parser = etree.XMLParser(no_network=True, resolve_entities=False)
    parser.resolvers.add(Catalog())
    return etree.XMLSchema(etree.parse(lock['citygml_root'], parser))


def validate(path, cache, lock_path=DEFAULT_LOCK):
    xsd = schema(cache, lock_path)
    document = etree.parse(str(path), etree.XMLParser(no_network=True, resolve_entities=False))
    if document.docinfo.doctype:
        raise ValueError('DOCTYPE is not permitted in export validation.')
    xsd.assertValid(document)
    return {'file': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'standard': 'CityGML 2.0', 'lxml': etree.LXML_VERSION,
            'schema_status': 'PASS', 'network_during_validation': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--schema-cache', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.path, args.schema_cache, args.lock), indent=2))
    except (etree.Error, ValueError, OSError) as exc:
        parser.exit(1, f'CityGML 2.0 validation failed: {exc}\n')
