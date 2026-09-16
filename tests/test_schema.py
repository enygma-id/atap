# SPDX-License-Identifier: AGPL-3.0-only
"""Validate complete ATAP goldens against profile 0.6 JSON Schema."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = json.loads(Path("schema/atap-elevation-0.6.schema.json").read_text(encoding="utf-8-sig"))


def test_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_complete_goldens_match_profile_schema():
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    for path in sorted(Path("tests/golden").glob("*.geojson")):
        errors = list(validator.iter_errors(json.loads(path.read_text(encoding="utf-8"))))
        assert not errors, f"{path}: {errors[0].message}"
