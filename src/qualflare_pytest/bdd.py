"""pytest-bdd support: Gherkin steps become `Case.steps`.

The hooks emit into the SAME message stream as `qualflare.step()`, so the replay
needs no special case and a scenario can mix Gherkin steps with manual ones.

pytest-bdd is an OPTIONAL dependency. These hooks are only registered when it is
importable: pytest rejects unknown `pytest_bdd_*` hook names outright when the
plugin defining them is absent, so declaring them unconditionally would break
every run that does not use BDD.
"""

from __future__ import annotations

import time
from typing import Any

from .runtime import _emit


def bdd_is_available() -> bool:
    try:
        import pytest_bdd  # noqa: F401
    except ImportError:
        return False
    return True


class BDDHooks:
    """Gherkin step timing.

    One start time per step is enough: pytest-bdd runs a scenario's steps
    sequentially and never nests them, so there is no stack to keep.
    """

    def __init__(self) -> None:
        self._started: float | None = None

    def pytest_bdd_before_step(
        self, request: Any, feature: Any, scenario: Any, step: Any, step_func: Any
    ) -> None:
        self._started = time.perf_counter()
        _emit(
            "step_start",
            {
                "name": getattr(step, "name", "") or "",
                # "Given"/"When"/"Then" as written in the feature file. The wire
                # contract has a dedicated `keyword` field for exactly this, so it
                # is not smuggled into the name.
                "keyword": getattr(step, "keyword", None),
                "location": _location(feature, step),
            },
        )

    def pytest_bdd_after_step(
        self,
        request: Any,
        feature: Any,
        scenario: Any,
        step: Any,
        step_func: Any,
        step_func_args: Any,
    ) -> None:
        self._stop("passed", None)

    def pytest_bdd_step_error(
        self,
        request: Any,
        feature: Any,
        scenario: Any,
        step: Any,
        step_func: Any,
        step_func_args: Any,
        exception: Any,
    ) -> None:
        # pytest-bdd fires step_error INSTEAD of after_step for a failing step, so
        # this is the only place a failed Gherkin step is closed.
        self._stop("failed", str(exception))

    def _stop(self, status: str, error: str | None) -> None:
        elapsed = time.perf_counter() - (self._started or time.perf_counter())
        self._started = None
        _emit(
            "step_stop",
            {"status": status, "error": error, "duration": int(elapsed * 1_000_000_000)},
        )


def _location(feature: Any, step: Any) -> str | None:
    """`feature.rel_filename:line` — enough to open the step in an editor."""
    name = getattr(feature, "rel_filename", None) or getattr(feature, "filename", None)
    line = getattr(step, "line_number", None)
    if not name:
        return None
    return f"{name}:{line}" if line else str(name)
