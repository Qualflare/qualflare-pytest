"""pytest-bdd support, and its absence.

Both directions matter: BDD is optional, and pytest REJECTS unknown
`pytest_bdd_*` hook names when pytest-bdd is not installed — so registering the
hooks unconditionally would break every run that does not use BDD.
"""

from __future__ import annotations

import os

import pytest

pytest_bdd = pytest.importorskip("pytest_bdd", reason="pytest-bdd not installed")


FEATURE = """\
Feature: Checkout
  Scenario: Buying a widget
    Given a cart
    When I add a widget
    Then the total is wrong
"""

STEPS = '''
from pytest_bdd import scenarios, given, when, then
scenarios("checkout.feature")

@given("a cart")
def _cart():
    return []

@when("I add a widget")
def _add():
    pass

@then("the total is wrong")
def _total():
    raise AssertionError("totals disagree")
'''


def _run_bdd(pytester):
    (pytester.path / "checkout.feature").write_text(FEATURE)
    pytester.makepyfile(test_checkout=STEPS)
    out = pytester.path / "out"
    old = os.environ.get("QUALFLARE_OUTPUT_DIR")
    os.environ["QUALFLARE_OUTPUT_DIR"] = str(out)
    try:
        pytester.runpytest_subprocess("-p", "no:cacheprovider")
    finally:
        if old is None:
            os.environ.pop("QUALFLARE_OUTPUT_DIR", None)
        else:
            os.environ["QUALFLARE_OUTPUT_DIR"] = old
    return out


def test_gherkin_steps_become_case_steps(pytester, read_report, cases):
    report = read_report(_run_bdd(pytester))
    case = cases(report)[0]

    assert case["status"] == "failed"
    steps = case["steps"]
    assert [s["name"] for s in steps] == [
        "a cart",
        "I add a widget",
        "the total is wrong",
    ]
    # The keyword goes in its own wire field rather than being smuggled into the
    # step name, so the UI can render Given/When/Then distinctly.
    assert [s["keyword"] for s in steps] == ["Given", "When", "Then"]
    # pytest-bdd fires step_error INSTEAD of after_step for a failing step; if
    # that hook were missing the final step would be recorded as passed.
    assert [s["status"] for s in steps] == ["passed", "passed", "failed"]
    assert steps[-1]["location"].endswith("checkout.feature:5")


def test_gherkin_steps_are_flat_not_nested(pytester, read_report, cases):
    # Gherkin steps are sequential, never nested. A parentIndex here would mean
    # the step stack was left open between steps.
    report = read_report(_run_bdd(pytester))
    steps = cases(report)[0]["steps"]
    assert all("parentIndex" not in s for s in steps)
