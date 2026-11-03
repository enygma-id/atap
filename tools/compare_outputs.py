# SPDX-License-Identifier: AGPL-3.0-only
"""
Scientific equivalence check between two ATAP outputs.

    python compare_outputs.py BASELINE.geojson CANDIDATE.geojson

Ignores the `process` block (timestamps, duration, implementation file,
software versions) and `processing.execution` (workers, cache). Everything
else — features, geometry, properties, inputs, processing.parameters,
vertical_reference, summary — must be identical. Exit 0 = equivalent.
"""
import argparse
import hashlib
import json
import sys

IGNORED_TOP = {"process"}
IGNORED_PROCESSING = {"execution"}

def canonical(path, *, ignore_engine_version=False, allow_orientation_translation=False):
    d = json.load(open(path, encoding="utf-8"))
    for k in IGNORED_TOP:
        d.pop(k, None)
    for k in IGNORED_PROCESSING:
        d.get("processing", {}).pop(k, None)
    if allow_orientation_translation:
        d.get("processing", {}).pop("orientation_convention", None)
    if ignore_engine_version and "engine_version" in d.get("atap", {}):
        # Preserve the member's presence and all other provenance/scientific fields.
        d["atap"]["engine_version"] = "<engine-version>"
    return d


def digest(document):
    serialized = json.dumps(document, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def diff(a, b, path="$", out=None, limit=20):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path}: type {type(a).__name__} != {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'candidate' if k in b else 'baseline'}")
            else:
                diff(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline")
    parser.add_argument("candidate", nargs="?")
    parser.add_argument("--ignore-engine-version", action="store_true",
                        help="Normalize only atap.engine_version for explicit cross-version comparisons")
    parser.add_argument("--allow-orientation-translation", action="store_true")
    parser.add_argument("--digest", action="store_true", help="Print one canonical SHA-256 instead of comparing")
    args = parser.parse_args()
    options = dict(ignore_engine_version=args.ignore_engine_version,
                   allow_orientation_translation=args.allow_orientation_translation)
    baseline = canonical(args.baseline, **options)
    if args.digest:
        if args.candidate:
            parser.error("--digest accepts one input")
        print(digest(baseline))
        raise SystemExit(0)
    if not args.candidate:
        parser.error("candidate is required unless --digest is selected")
    problems = diff(baseline, canonical(args.candidate, **options))
    if problems:
        print("NOT EQUIVALENT (first differences):")
        print("\n".join("  " + p for p in problems))
        sys.exit(1)
    print("EQUIVALENT (ignoring process metadata and execution settings)")
    if args.ignore_engine_version:
        print("Cross-version mode: only atap.engine_version was additionally normalized.")
