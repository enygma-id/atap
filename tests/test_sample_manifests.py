# SPDX-License-Identifier: AGPL-3.0-only
"""Shipped samples must exist and match their complete integrity manifests."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("sample_manifest_verifier", ROOT / "tools/verify_sample_manifests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_manifest


@pytest.mark.parametrize("sample,count", [("atap-sample-area-01", 3), ("atap-sample-tree-01", 6)])
def test_shipped_sample_integrity(verifier, sample, count):
    assert len(verifier(ROOT / "samples" / sample / "MANIFEST.sha256")) == count


@pytest.mark.parametrize("case,message", [
    ("missing", "missing reference"), ("corrupted", "SHA-256 mismatch"),
    ("escape", "unsafe relative path"), ("duplicate", "duplicate reference"),
])
def test_invalid_manifest_fails(verifier, tmp_path, case, message):
    digest = hashlib.sha256(b"original").hexdigest()
    (tmp_path / "present.bin").write_bytes(b"changed" if case == "corrupted" else b"original")
    name = "missing.bin" if case == "missing" else "../outside.bin" if case == "escape" else "present.bin"
    entry = f"{digest}  {name}\n"
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text(entry * (2 if case == "duplicate" else 1), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        verifier(manifest)
