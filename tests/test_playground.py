# SPDX-License-Identifier: AGPL-3.0-only
"""Contract checks for the packaged single-file playground."""

import ast
import re
from dataclasses import asdict
from pathlib import Path

from atap.engine.config import Config

HTML = Path("src/atap/server/static/index.html")
EXCLUDED_CONFIG_FIELDS = {
    "input_geojson",
    "dsm_path",
    "dtm_path",
    "output_geojson",
    "output_crs",
    "raster_drivers",
    "coord_digits",
}


def _params() -> list[dict]:
    source = HTML.read_text(encoding="utf-8")
    match = re.search(r"const PARAMS = \[(.*?)\n\];", source, re.DOTALL)
    assert match
    value = "[" + match.group(1) + "]"
    value = re.sub(r"([,{]\s*)([A-Za-z][A-Za-z0-9_]*):", r'\1"\2":', value)
    value = re.sub(r"\btrue\b", "True", value)
    value = re.sub(r"\bfalse\b", "False", value)
    value = re.sub(r"\bnull\b", "None", value)
    return ast.literal_eval(value)


def test_ui_parameter_defaults_match_engine_config():
    definitions = _params()
    ui_defaults = {item["key"]: item["def"] for item in definitions}
    ui_defaults["keep_properties"] = (
        [value.strip() for value in ui_defaults["keep_properties"].split(",") if value.strip()]
        or None
    )
    ui_defaults["id_field"] = ui_defaults["id_field"] or None
    ui_defaults["vertical_datum"] = ui_defaults["vertical_datum"] or None

    engine_defaults = asdict(Config())
    run_fields = set(engine_defaults) - EXCLUDED_CONFIG_FIELDS
    assert set(ui_defaults) == run_fields
    assert ui_defaults == {key: engine_defaults[key] for key in run_fields}
    assert all(item.get("hint", "").strip() for item in definitions)


def test_accessibility_basics_and_packaged_source():
    source = HTML.read_text(encoding="utf-8")
    font_sizes = [
        float(value)
        for value in re.findall(r"font-size:\s*([0-9.]+)px", source)
    ]
    assert font_sizes and min(font_sizes) >= 10
    for button_id in ("btn-settings", "btn-open", "btn-fit", "btn-reset-view"):
        tag = re.search(rf'<button[^>]*id="{button_id}"[^>]*>', source)
        assert tag and "aria-label=" in tag.group(0)
    assert 'aria-label="$' + '{esc(def.label)}"' in source
    assert not Path("prototype").exists()


def test_level_palette_has_six_colors_and_matching_legend():
    source = HTML.read_text(encoding="utf-8")
    match = re.search(r"const LEVEL_COLORS = \[(.*?)\];", source)
    assert match and match.group(1).count("[") == 6
    assert all(f"Level {level}" in source for level in range(6))
    assert "LEVEL_COLORS.length - 1" in source
