# SPDX-License-Identifier: AGPL-3.0-only
"""Package output stays equivalent to all frozen Phase 0 baselines."""

import subprocess
import sys
from pathlib import Path


def test_all_four_frozen_goldens(synthetic: Path, tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    candidate = tmp_path / "baseline"
    run = subprocess.run(
        [
            sys.executable,
            str(root / "tools/run_baselines.py"),
            "--data",
            str(synthetic),
            "--out",
            str(candidate),
            "--engine",
            "atap",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    verify = subprocess.run(
        [sys.executable, str(root / "tests/golden/verify.py"), str(candidate)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "All four golden cases and summaries are EQUIVALENT." in verify.stdout
