# SPDX-License-Identifier: AGPL-3.0-only
"""Verify a complete run_baselines.py output directory against frozen goldens."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_directory", type=Path)
    parser.add_argument("--ignore-engine-version", action="store_true")
    parser.add_argument("--expected-engine-version",
                        help="Also require actual output provenance to report this version")
    args = parser.parse_args()
    golden = Path(__file__).resolve().parent
    candidate = args.baseline_directory
    comparator = golden.parents[1] / "tools/compare_outputs.py"
    sys.path.insert(0, str(comparator.parent))
    from compare_outputs import canonical, digest

    if args.expected_engine_version:
        for name in ("stepped_default", "stepped_k8_regularize", "courtyard_default", "bench_default"):
            if read(candidate / (name + ".geojson")).get("atap", {}).get("engine_version") != args.expected_engine_version:
                raise SystemExit(f"NOT EQUIVALENT: {name} engine_version does not report {args.expected_engine_version}")
    for name in ("stepped_default", "stepped_k8_regularize", "courtyard_default"):
        print(name, flush=True)
        flags = ["--ignore-engine-version"] if args.ignore_engine_version else []
        subprocess.run([sys.executable, str(comparator), *flags,
                        str(golden / (name + ".geojson")),
                        str(candidate / (name + ".geojson"))], check=True)
    bench = read(candidate / "bench_default.geojson")
    if bench["summary"] != read(golden / "bench_default.summary.json"):
        raise SystemExit("NOT EQUIVALENT: benchmark summary")
    actual_digest = digest(canonical(candidate / "bench_default.geojson",
                                     ignore_engine_version=args.ignore_engine_version))
    hash_file = "bench_default.scientific.sha256" if args.ignore_engine_version else "bench_default.sha256"
    expected = {
        line.split()[0]
        for line in (golden / hash_file).read_text().splitlines()
        if line.strip()
    }
    if actual_digest not in expected:
        raise SystemExit(
            f"NOT EQUIVALENT: benchmark SHA-256 {actual_digest} not in "
            f"{', '.join(sorted(expected))}"
        )
    print(f"bench_default EQUIVALENT: SHA-256 {actual_digest} ({hash_file})")
    old, new = read(golden / "summary.json"), read(candidate / "summary.json")
    for summary in (old, new):
        for case in summary.values():
            case.pop("seconds_workers_1", None)
    if old != new:
        raise SystemExit("NOT EQUIVALENT: case summaries")
    print("All four golden cases and summaries are EQUIVALENT.")


if __name__ == "__main__":
    main()
