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


# --------------------------------------------------------------------------
# Regressions from the self-review. Every one of these was a real defect that
# produced a WRONG report rather than an error, and none was caught by the
# original suite.
# --------------------------------------------------------------------------

RETRY_METADATA_SUITE = '''
import time, os, pytest
from qualflare_pytest import qualflare

_n = {"c": 0}

@pytest.mark.flaky(reruns=2)
def test_metadata_across_retries():
    qualflare.label("team", "platform")
    qualflare.tag("smoke")
    with qualflare.step("a step"):
        pass
    _n["c"] += 1
    if _n["c"] < 3:
        raise AssertionError("retry me")

def test_outer_step_keeps_its_own_timing():
    with qualflare.step("OUTER"):
        for i in range(320):
            with qualflare.step(f"child-{i}"):
                pass
        time.sleep(0.05)

def test_attaches_a_file():
    open("shot.png", "wb").write(b"PNGDATA")
    qualflare.attachment_from_file("screenshot", os.path.abspath("shot.png"), mime_type="image/png")

def test_oversized_inline_attachment_is_skipped():
    qualflare.attachment("huge", "x" * 3_000_000)
'''


def _run_suite(pytester, source, *extra):
    pytester.makepyfile(test_regress=source)
    out = pytester.path / "out"
    old = os.environ.get("QUALFLARE_OUTPUT_DIR")
    os.environ["QUALFLARE_OUTPUT_DIR"] = str(out)
    try:
        pytester.runpytest_subprocess("-p", "no:cacheprovider", *extra)
    finally:
        if old is None:
            os.environ.pop("QUALFLARE_OUTPUT_DIR", None)
        else:
            os.environ["QUALFLARE_OUTPUT_DIR"] = old
    return out


def test_metadata_is_not_duplicated_across_retries(pytester, read_report, cases):
    """pytest-rerunfailures loops INSIDE one pytest_runtest_protocol call, so a
    shared metadata bucket accumulates every attempt's messages. It produced
    three copies of each label, tag and step on a reruns=2 test."""
    report = read_report(_run_suite(pytester, RETRY_METADATA_SUITE))
    c = {x["name"]: x for x in cases(report)}["test_metadata_across_retries"]

    assert len(c["labels"]) == 1, c["labels"]
    assert c["tags"].count("smoke") == 1
    assert len([s for s in c["steps"] if s["name"] == "a step"]) == 1
    # The retry history itself must still be complete.
    assert len(c["attempts"]) == 3


def test_step_dropped_at_the_cap_does_not_close_an_open_parent(pytester, read_report, cases):
    """A dropped step_start still gets a step_stop. Without a sentinel it popped
    whichever step was legitimately open, overwriting its status and duration and
    then discarding its real stop event."""
    report = read_report(_run_suite(pytester, RETRY_METADATA_SUITE))
    c = {x["name"]: x for x in cases(report)}["test_outer_step_keeps_its_own_timing"]
    outer = next(s for s in c["steps"] if s["name"] == "OUTER")

    # OUTER wraps a 50ms sleep; before the fix it reported 0.000ms because a
    # dropped child's stop closed it.
    assert outer["duration"] >= 50_000_000, f"outer lost its own timing: {outer['duration']}ns"


def test_attachment_from_file_is_copied_and_referenced_relatively(pytester, read_report, cases):
    """`localImagePath` is defined as relative to outputDir. Passing the user's
    own path through made it unresolvable for the CLI — the server stored an
    undownloadable placeholder — and leaked the agent's directory layout."""
    out = _run_suite(pytester, RETRY_METADATA_SUITE)
    report = read_report(out)
    c = {x["name"]: x for x in cases(report)}["test_attaches_a_file"]
    att = c["attachments"][0]

    path = att["localImagePath"]
    assert not os.path.isabs(path), path
    assert (out / path).is_file(), "the file must be copied INTO outputDir"
    assert att["fileSize"] == len(b"PNGDATA")


def test_oversized_inline_attachment_is_dropped_not_truncated(pytester, read_report, cases):
    """A rejected /collect body loses the whole launch, not one attachment. Half a
    base64 payload is not a usable file, so it is dropped rather than truncated."""
    report = read_report(_run_suite(pytester, RETRY_METADATA_SUITE))
    c = {x["name"]: x for x in cases(report)}["test_oversized_inline_attachment_is_skipped"]

    assert c["status"] == "passed", "an oversized attachment must never fail the test"
    assert "content" not in c["attachments"][0]


FIXTURE_RETRY_SUITE = '''
import pytest

_s = {"c": 0}

@pytest.fixture
def flaky_fixture():
    _s["c"] += 1
    if _s["c"] < 3:
        raise RuntimeError(f"fixture boom {_s['c']}")
    return True

@pytest.mark.flaky(reruns=2)
def test_flaky_fixture_recovers(flaky_fixture):
    assert flaky_fixture

@pytest.fixture
def always_broken():
    raise RuntimeError("permanently broken fixture")

@pytest.mark.flaky(reruns=1)
def test_fixture_never_recovers(always_broken):
    assert True
'''


def test_setup_triggered_retries_are_errors_not_failures(pytester, read_report, cases):
    """rerunfailures retries setup failures too. Hardcoding every attempt as
    "failed" blamed the test body for a flaky fixture, contradicting the rule the
    plugin applies to the final outcome."""
    report = read_report(_run_suite(pytester, FIXTURE_RETRY_SUITE))
    c = {x["name"]: x for x in cases(report)}["test_flaky_fixture_recovers"]

    assert [a["status"] for a in c["attempts"]] == ["error", "error", "passed"]
    assert c["status"] == "passed"


def test_terminal_attempt_keeps_its_message_when_the_status_is_error(
    pytester, read_report, cases
):
    """The terminal attempt is the entry explaining why the retries ran out.
    Testing only for "failed" shipped it blank whenever a fixture kept failing."""
    report = read_report(_run_suite(pytester, FIXTURE_RETRY_SUITE))
    c = {x["name"]: x for x in cases(report)}["test_fixture_never_recovers"]

    assert c["status"] == "error"
    assert "permanently broken fixture" in c["attempts"][-1]["message"]


def test_ci_metadata_reaches_the_report(pytester, read_report):
    """ci_detect computed provider, build number, run URL and PR number, and
    resolve_config never read them — so every CI report dropped them silently."""
    ci = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Qualflare/qualflare-pytest",
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_NUMBER": "7",
        "GITHUB_SHA": "abc123",
        "GITHUB_REF_NAME": "main",
    }
    old = {k: os.environ.get(k) for k in ci}
    os.environ.update(ci)
    try:
        report = read_report(_run_suite(pytester, "def test_ok(): pass\n"))
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    assert report["ciProvider"] == "github"
    assert report["ciBuildNumber"] == "7"
    assert report["ciRunUrl"].endswith("/actions/runs/42")
    assert report["commit"] == "abc123"
