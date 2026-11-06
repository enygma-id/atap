# SPDX-License-Identifier: AGPL-3.0-only
"""Fuzz the saved-result export boundary without changing canonical source bytes."""
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from atap.engine.config import AtapError
    from atap.exports import export_file


def test_one_input(data):
    with tempfile.TemporaryDirectory(prefix="atap-fuzz-export-") as temporary:
        source = Path(temporary) / "input.geojson"
        source.write_bytes(data)
        try:
            export_file(source, "all")
        except (AtapError, ValueError):
            pass
        # Unexpected exceptions, crashes and timeouts are findings, not ignored.
        assert source.read_bytes() == data


if __name__ == "__main__":
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
