"""Shared fixtures for the plugin's own test suite.

`pytester` runs a REAL pytest in a subprocess against a generated project, which
is the analogue of the JavaScript packages' integration fixtures: it exercises the
installed plugin through the same entry point a user gets, rather than calling
internals directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


@pytest.fixture
def read_report():
    """Reads the single report the plugin wrote, failing loudly if there is not
    exactly one — two would mean a worker wrote its own, which is the bug the
    controller-only write exists to prevent."""

    def _read(output_dir: Path) -> dict:
        reports = sorted(Path(output_dir).glob("*.json"))
        assert len(reports) == 1, f"expected exactly one report, found {len(reports)}"
        return json.loads(reports[0].read_text())

    return _read


@pytest.fixture
def cases():
    """Flattens a report's cases, sorted by name so comparisons are stable."""

    def _cases(report: dict) -> list[dict]:
        return sorted(
            (c for s in report["suites"] for c in s["cases"]), key=lambda c: c["name"]
        )

    return _cases
