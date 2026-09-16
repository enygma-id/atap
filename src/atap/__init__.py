# SPDX-License-Identifier: AGPL-3.0-only
"""Public Python API for ATAP elevation."""

from .engine.config import AtapError, AtapInputError, AtapValidationError, Config

__version__ = "0.2.0"

__all__ = [
    "AtapError",
    "AtapInputError",
    "AtapValidationError",
    "Config",
    "run_elevation",
]


def __getattr__(name: str):
    """Load the engine entry point only when callers request it."""
    if name == "run_elevation":
        from .engine.pipeline import run_elevation

        return run_elevation
    raise AttributeError(name)
