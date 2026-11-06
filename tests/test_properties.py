# SPDX-License-Identifier: AGPL-3.0-only
"""Generated scientific contract checks; production algorithms remain unchanged."""
import math

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from shapely.geometry import box

from atap.engine.validation import validate_hierarchy, validate_vertical
from atap.exports import _mesh


@settings(max_examples=40, deadline=None)
@given(width=st.integers(2, 100), depth=st.integers(2, 100),
       height=st.integers(1, 200), ground=st.integers(-100, 2000),
       courtyard=st.booleans())
def test_generated_solid_volume_and_ground_translation(width, depth, height, ground, courtyard):
    geometry = box(0, 0, width, depth)
    if courtyard:
        geometry = geometry.difference(box(width / 4, depth / 4, 3 * width / 4, 3 * depth / 4))
    volumes = []
    for placement in (ground, ground + 150):
        shells = _mesh(geometry, placement, placement + height)
        volume = 0.0
        for shell in shells:
            origin = np.asarray(shell[0][0])
            for face in shell:
                for index in range(1, len(face) - 1):
                    a, b, c = np.asarray([face[0], face[index], face[index + 1]]) - origin
                    volume += float(np.dot(a, np.cross(b, c))) / 6
        assert volume >= 0
        assert math.isclose(volume, geometry.area * height, rel_tol=1e-8, abs_tol=1e-6)
        volumes.append(volume)
    assert math.isclose(*volumes, rel_tol=1e-8, abs_tol=1e-6)


@settings(max_examples=40, deadline=None)
@given(root_height=st.integers(1, 100), child_height=st.integers(1, 100),
       ground=st.integers(-100, 2000))
def test_generated_vertical_family_and_corruption(root_height, child_height, ground):
    records = []
    for pid, parent, level, base, top in [("A-P00", None, 0, 0, root_height),
                                         ("A-P01", "A-P00", 1, root_height, root_height + child_height)]:
        assert top >= base
        records.append({"id": pid, "properties": {
            "object_id": "A", "part_id": pid, "parent_part_id": parent,
            "part_level": level, "base_height_agl_m": base, "top_height_agl_m": top,
            "part_height_m": top - base, "ground_elevation_m": ground,
            "base_elevation_m": ground + base, "top_elevation_m": ground + top,
            "valid_coverage_ratio": 1}})
    problems = []
    validate_hierarchy(records, {r["id"]: r for r in records}, problems, 0.01)
    validate_vertical(records, problems, 0.01)
    assert not problems
    # A child must inherit its parent's top, regardless of absolute placement.
    records[1]["properties"]["base_height_agl_m"] += 1
    validate_hierarchy(records, {r["id"]: r for r in records}, problems, 0.01)
    assert any("base_height_agl_m" in problem for problem in problems)
