# SPDX-License-Identifier: AGPL-3.0-only
"""Fuzz the real canonical schema with bounded arbitrary JSON documents."""
import itertools
import json
import sys
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schema" /
                     "atap-elevation-0.6.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def test_one_input(data):
    try:
        document = json.loads(data)
    except (ValueError, RecursionError):
        # Invalid encodings/JSON or Python's JSON nesting limit never reach ATAP.
        return
    # Schema errors are expected results; unexpected validator exceptions escape.
    list(itertools.islice(VALIDATOR.iter_errors(document), 20))


if __name__ == "__main__":
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
