# SPDX-License-Identifier: AGPL-3.0-only
"""Keep installed, source, lock and citation versions aligned before release."""
import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

import atap
from atap.engine.config import ENGINE_VERSION, PROFILE_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_consistent():
    # These narrowly scoped literal checks work on Python 3.10 without adding a
    # TOML/YAML runtime dependency. uv and cffconvert validate their full formats.
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").split("[project]\n", 1)[1].split("\n[", 1)[0]
    version = re.search(r'^version = "([^"]+)"$', project, re.MULTILINE).group(1)
    assert version == atap.__version__ == ENGINE_VERSION == importlib.metadata.version("atap") == "0.3.0"
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert re.search(r'^version:\s*["\']?([^\s"\']+)', citation, re.MULTILINE).group(1) == version
    packages = (ROOT / "uv.lock").read_text(encoding="utf-8").split("[[package]]")
    editable = [p for p in packages if re.search(r'^name = "atap"$', p, re.MULTILINE)]
    assert len(editable) == 1
    assert re.search(r'^version = "([^"]+)"$', editable[0], re.MULTILINE).group(1) == version
    assert 'source = { editable = "." }' in editable[0]
    assert PROFILE_VERSION == "0.6"


def test_release_cli_version():
    result = subprocess.run([sys.executable, "-m", "atap", "--version"], capture_output=True, text=True, check=True)
    assert "engine 0.3.0, profile 0.6" in result.stdout
