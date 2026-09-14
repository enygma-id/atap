# SPDX-License-Identifier: AGPL-3.0-only
"""Shared synthetic datasets generated for the test session."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def synthetic(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("synthetic")
    subprocess.run(
        [sys.executable, "tools/make_synthetic.py", "--out", str(target)],
        check=True,
    )
    return target

