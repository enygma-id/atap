# SPDX-License-Identifier: AGPL-3.0-only
"""
Scientific equivalence check between two ATAP outputs.

    python compare_outputs.py BASELINE.geojson CANDIDATE.geojson

Ignores the `process` block (timestamps, duration, implementation file,
software versions) and `processing.execution` (workers, cache). Everything
else — features, geometry, properties, inputs, processing.parameters,
vertical_reference, summary — must be identical. Exit 0 = equivalent.
"""
import json
import sys

IGNORED_TOP = {"process"}
IGNORED_PROCESSING = {"execution"}

# Profile 0.6 English migration changes only this metadata value. Use
# --allow-orientation-translation solely when comparing a pre-migration golden.
ALLOW_ORIENTATION_TRANSLATION = "--allow-orientation-translation" in sys.argv


def canonical(path):
    d = json.load(open(path, encoding="utf-8"))
    for k in IGNORED_TOP:
        d.pop(k, None)
    for k in IGNORED_PROCESSING:
        d.get("processing", {}).pop(k, None)
    if ALLOW_ORIENTATION_TRANSLATION:
        d.get("processing", {}).pop("orientation_convention", None)
    return d


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
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    problems = diff(canonical(paths[0]), canonical(paths[1]))
    if problems:
        print("NOT EQUIVALENT (first differences):")
        print("\n".join("  " + p for p in problems))
        sys.exit(1)
    print("EQUIVALENT (ignoring process metadata and execution settings)")
