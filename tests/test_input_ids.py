# SPDX-License-Identifier: AGPL-3.0-only
"""Source identifiers come only from a single properties key."""
import json

import pytest
from pyproj import CRS

from atap import AtapInputError, Config
from atap.engine.io import load_footprints


def load(tmp_path, properties, field=None):
    path = tmp_path / "ids.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "ignored", "geometry": None, "properties": p}
        for p in properties
    ]}), encoding="utf-8")
    return load_footprints(Config(input_geojson=str(path), id_field=field),
                           CRS.from_epsg(32750), lambda _: None)


def test_auto_property_id_ignores_duplicate_feature_ids(tmp_path):
    result = load(tmp_path, [{"id": "A"}, {"id": "B"}])
    assert [r[0] for r in result["records"]] == ["A", "B"]
    assert result["id_source"] == {"mode": "property", "field": "id"}


def test_explicit_key_overrides_existing_id(tmp_path):
    result = load(tmp_path, [{"id": "same", "code": "A"},
                             {"id": "same", "code": "B"}], "code")
    assert [r[0] for r in result["records"]] == ["A", "B"]
    assert result["id_source"]["field"] == "code"


@pytest.mark.parametrize("properties", [[{}, {}], [{"id": "A"}, {}],
                                        [{"id": " "}], [{"id": None}]])
def test_feature_ids_never_rescue_missing_properties(tmp_path, properties):
    with pytest.raises(AtapInputError, match="--id-field"):
        load(tmp_path, properties)


def test_duplicate_normalized_property_ids_fail(tmp_path):
    with pytest.raises(AtapInputError, match="Duplicate"):
        load(tmp_path, [{"id": 1}, {"id": "1"}])


def test_alternate_key_without_id(tmp_path):
    assert load(tmp_path, [{"code": "A"}], "code")["records"][0][0] == "A"
