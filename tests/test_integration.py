"""Drives a real pytest run against a generated project and asserts the report.

These run the plugin the way a user gets it — installed, auto-registered through
its `pytest11` entry point — rather than by calling internals.
"""

from __future__ import annotations

import json
import os

SUITE = '''
import pytest
from qualflare_pytest import qualflare

_n = {"c": 0}

@pytest.mark.smoke
@pytest.mark.flaky(reruns=2)
def test_fails_twice_then_passes():
    _n["c"] += 1
    if _n["c"] < 3:
        raise AssertionError(f"boom attempt {_n['c']}")

def test_passes():
    pass

def test_records_metadata():
    qualflare.label("team", "platform")
    qualflare.tag("checkout")
    qualflare.priority("high")
    qualflare.link("https://example.com/issue/42", type="issue", name="QF-42")
    qualflare.parameter("plan", "pro")
    qualflare.parameter("token", "super-secret-value", masked=True)
    with qualflare.step("outer"):
        with qualflare.step("inner"):
            qualflare.parameter("sku", "widget")

def test_fails_with_a_marker_in_the_message():
    raise AssertionError("qualflare-pytest-integration-marker")

@pytest.mark.skip(reason="deliberate")
def test_skipped():
    pass

@pytest.fixture
def broken():
    raise RuntimeError("fixture exploded")

def test_guarded_by_broken_fixture(broken):
    assert True
'''


def _run(pytester, *extra):
    """Runs a real pytest subprocess against the generated suite.

    `runpytest_subprocess` rather than in-process: the plugin registers through an
    entry point and, under `-n`, spawns workers — neither of which behaves the
    same way inside the parent interpreter.
    """
    pytester.makepyfile(test_suite=SUITE)
    out = pytester.path / "out"
    monkey = {"QUALFLARE_OUTPUT_DIR": str(out)}
    old = {k: os.environ.get(k) for k in monkey}
    os.environ.update(monkey)
    try:
        pytester.runpytest_subprocess("-p", "no:cacheprovider", *extra)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out


def test_writes_one_identifiable_report(pytester, read_report, cases):
    out = _run(pytester)
    report = read_report(out)

    # The detection triple. Drop any one and `qf collect` falls back to filename
    # detection and misroutes the file.
    assert report["framework"] == "pytest"
    assert report["metadata"]
    assert report["suites"]
    # Value-or-null, always present — the server distinguishes these from absent.
    assert "branch" in report and "commit" in report and "milestone" in report

    got = cases(report)
    assert len(got) == 6
    by_name = {c["name"]: c for c in got}
    assert by_name["test_passes"]["status"] == "passed"
    assert by_name["test_fails_with_a_marker_in_the_message"]["status"] == "failed"
    assert "qualflare-pytest-integration-marker" in by_name[
        "test_fails_with_a_marker_in_the_message"
    ]["error"]


def test_skipped_and_fixture_errors_are_not_dropped(pytester, read_report, cases):
    # These emit NO `call` report — only `setup`. A plugin keyed on the call phase
    # loses them silently, and the case count shrinks with no warning.
    report = read_report(_run(pytester))
    by_name = {c["name"]: c for c in cases(report)}

    assert by_name["test_skipped"]["status"] == "skipped"
    # A broken fixture means the test never reached a verdict. `error` says that;
    # `failed` would blame the test for someone else's fixture.
    assert by_name["test_guarded_by_broken_fixture"]["status"] == "error"


def test_metadata_and_masking(pytester, read_report, cases):
    report = read_report(_run(pytester))
    meta = {c["name"]: c for c in cases(report)}["test_records_metadata"]

    assert {"name": "team", "value": "platform"} in meta["labels"]
    assert "checkout" in meta["tags"]
    assert meta["priority"] == "high"
    assert meta["links"][0]["url"] == "https://example.com/issue/42"
    assert meta["properties"]["plan"] == "pro"

    # Masked at SOURCE. Asserted over the WHOLE payload, because the only
    # convincing proof is that the secret appears nowhere at all.
    assert "super-secret-value" not in json.dumps(report)

    inner = next(s for s in meta["steps"] if s["name"] == "inner")
    assert inner["parentIndex"] == 0


def test_markers_become_tags(pytester, read_report, cases):
    report = read_report(_run(pytester))
    flaky = {c["name"]: c for c in cases(report)}["test_fails_twice_then_passes"]
    assert "smoke" in flaky["tags"]
    # pytest's own control markers describe HOW a test runs, not what it covers.
    assert "flaky" not in flaky["tags"]


def test_retry_history(pytester, read_report, cases):
    report = read_report(_run(pytester))
    flaky = {c["name"]: c for c in cases(report)}["test_fails_twice_then_passes"]

    assert flaky["status"] == "passed"
    assert flaky["retryCount"] == 2
    assert flaky["isFlaky"] is True
    assert [a["status"] for a in flaky["attempts"]] == ["failed", "failed", "passed"]
    # pytest supplies each attempt's traceback with no opt-in.
    assert "boom attempt 1" in flaky["attempts"][0]["message"]
    assert "boom attempt 2" in flaky["attempts"][1]["message"]


def test_serial_and_xdist_produce_the_same_report(pytester, read_report, cases):
    """THE load-bearing test.

    Under xdist the reporting hooks run on the controller while tests run in
    workers, and metadata only survives because it rides `user_properties`. This
    is what proves that path holds — and that the controller-only write does not
    produce two files.
    """
    serial = read_report(_run(pytester))
    for f in (pytester.path / "out").glob("*.json"):
        f.unlink()
    parallel = read_report(_run(pytester, "-n", "2"))

    def shape(report):
        return sorted(
            "|".join([
                c["name"], c["status"], str(len(c.get("attempts") or [])),
                str(len(c.get("steps") or [])), str(len(c.get("labels") or [])),
                ",".join(sorted(c.get("tags") or [])), c.get("priority") or "",
            ])
            for c in cases(report)
        )

    assert shape(parallel) == shape(serial)


def test_shard_index_only_under_xdist(pytester, read_report, cases):
    serial = cases(read_report(_run(pytester)))
    assert all(c.get("shardIndex") is None for c in serial), "no shard without xdist"

    for f in (pytester.path / "out").glob("*.json"):
        f.unlink()
    parallel = cases(read_report(_run(pytester, "-n", "2")))
    # PYTEST_XDIST_WORKER is readable only in the worker, so a populated value
    # proves it travelled with the metadata.
    assert any(isinstance(c.get("shardIndex"), int) for c in parallel)
