# SPDX-License-Identifier: AGPL-3.0-only
"""Verify a complete run_baselines.py output directory against frozen goldens."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tests/golden/verify.py BASELINE_DIRECTORY")
    golden = Path(__file__).resolve().parent
    candidate = Path(sys.argv[1])
    comparator = golden.parents[1] / "tools/compare_outputs.py"
    for name in ("stepped_default", "stepped_k8_regularize", "courtyard_default"):
        print(name, flush=True)
        subprocess.run([sys.executable, str(comparator),
                        str(golden / (name + ".geojson")),
                        str(candidate / (name + ".geojson"))], check=True)
    bench = read(candidate / "bench_default.geojson")
    if bench["summary"] != read(golden / "bench_default.summary.json"):
        raise SystemExit("NOT EQUIVALENT: benchmark summary")
    bench.pop("process", None)
    bench.get("processing", {}).pop("execution", None)
    serialized = json.dumps(bench, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    expected = {
        line.split()[0]
        for line in (golden / "bench_default.sha256").read_text().splitlines()
        if line.strip()
    }
    if digest not in expected:
        raise SystemExit(
            f"NOT EQUIVALENT: benchmark SHA-256 {digest} not in "
            f"{', '.join(sorted(expected))}"
        )
    print(f"bench_default EQUIVALENT: SHA-256 {digest}")
    old, new = read(golden / "summary.json"), read(candidate / "summary.json")
    for summary in (old, new):
        for case in summary.values():
            case.pop("seconds_workers_1", None)
    if old != new:
        raise SystemExit("NOT EQUIVALENT: case summaries")
    print("All four golden cases and summaries are EQUIVALENT.")


if __name__ == "__main__":
    main()
