# SPDX-License-Identifier: AGPL-3.0-only
"""Fuzz properties-ID selection through the real footprint loader."""
import json
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from pyproj import CRS

    from atap.engine.config import AtapInputError, Config
    from atap.engine.io import load_footprints


def test_one_input(data):
    provider = atheris.FuzzedDataProvider(data)
    kind = provider.ConsumeIntInRange(0, 3)
    value = [None, provider.ConsumeBool(), provider.ConsumeInt(8),
             provider.ConsumeUnicodeNoSurrogates(256)][kind]
    second = value if provider.ConsumeBool() else "second-building"
    geometry = {"type": "Polygon", "coordinates": [[[700000, 9430000],
                [700010, 9430000], [700010, 9430010], [700000, 9430010],
                [700000, 9430000]]]}
    document = {"type": "FeatureCollection", "crs": {"type": "name",
                "properties": {"name": "EPSG:32750"}}, "features": [
                {"type": "Feature", "id": "ignored", "properties": {"id": v},
                 "geometry": geometry} for v in (value, second)]}
    with tempfile.TemporaryDirectory(prefix="atap-fuzz-ids-") as temporary:
        path = Path(temporary) / "footprints.geojson"
        path.write_text(json.dumps(document), encoding="utf-8")
        try:
            result = load_footprints(Config(input_geojson=str(path)), CRS.from_epsg(32750), lambda _: None)
        except (AtapInputError, ValueError):
            return
        ids = [record[0] for record in result["records"]]
        assert len(ids) == len(set(ids)) == 2
        assert all(isinstance(value, str) and value.strip() for value in ids)
        assert result["id_source"] == {"mode": "property", "field": "id"}


if __name__ == "__main__":
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
