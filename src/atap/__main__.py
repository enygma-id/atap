# SPDX-License-Identifier: AGPL-3.0-only
"""Run the ATAP command-line interface with ``python -m atap``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
