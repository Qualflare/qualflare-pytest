"""A logger that writes to stderr, deliberately.

stdout is where pytest's own machine-readable output goes, and a plugin's
diagnostics must not corrupt anything parsing it. `print()` would land there.
"""

from __future__ import annotations

import contextlib
import sys

PREFIX = "[qualflare-pytest]"


def warn(message: str) -> None:
    # Suppressed unconditionally: a logger must never be the reason a run fails.
    with contextlib.suppress(Exception):
        sys.stderr.write(f"{PREFIX} {message}\n")


def info(message: str) -> None:
    warn(message)
