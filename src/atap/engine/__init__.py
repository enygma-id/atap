# SPDX-License-Identifier: AGPL-3.0-only
"""ATAP elevation engine."""

from .config import AtapError, AtapInputError, AtapValidationError, Config

__all__ = ["AtapError", "AtapInputError", "AtapValidationError", "Config", "run_elevation"]


def __getattr__(name: str):
    """Load the pipeline only when the public entry point is requested."""
    if name == "run_elevation":
        from .pipeline import run_elevation

        return run_elevation
    raise AttributeError(name)
