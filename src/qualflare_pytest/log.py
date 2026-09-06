"""A logger that writes to stderr, deliberately.

stdout is where pytest's own machine-readable output goes, and a plugin's
diagnostics must not corrupt anything parsing it. `print()` would land there.
"""

from __future__ import annotations

import sys

PREFIX = "[qualflare-pytest]"


def warn(message: str) -> None:
    try:
        sys.stderr.write(f"{PREFIX} {message}\n")
    except Exception:
        # A logger must never be the reason a run fails.
        pass


def info(message: str) -> None:
    warn(message)
