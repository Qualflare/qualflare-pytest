"""Turns the reports pytest emits for one test into a wire `Case`.

WHY THIS IS PHASE-AWARE, AND WHY THAT MATTERS

pytest reports each test in three phases -- setup, call, teardown -- but NOT every
test reaches `call`. Measured on pytest 9.1.1:

    a passing test        setup passed  | call passed  | teardown passed
    a failing test        setup passed  | call failed  | teardown passed
    @pytest.mark.skip     setup skipped |    (none)    | teardown passed
    a fixture that raises setup failed  |    (none)    | teardown passed

So a plugin that listens only for `when == "call"` silently drops every skipped
test and every fixture error -- they never appear in the report at all, and the
case count quietly shrinks. The outcome therefore comes from the first
non-passing phase, falling back to `call`, which is the rule pytest's own junitxml
uses.
"""

from __future__ import annotations

from typing import Any, Optional

from .attempts import build_attempts, describe_failure
from .constants import (
    MAX_ATTACHMENTS_PER_CASE,
    MAX_CASE_ERROR_RUNES,
    MAX_LABELS_PER_CASE,
    MAX_LINKS_PER_CASE,
    MAX_STEPS_PER_TEST_ATTEMPT,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_CASE,
)
from .text import truncate
from .wire import Case

# pytest's vocabulary is narrower than the wire contract's seven values. It has no
# distinct timed-out state, so `timeout` and `aborted` are never produced.
_STATUS = {"passed": "passed", "failed": "failed", "skipped": "skipped", "error": "error"}


def map_status(phase: str, outcome: str) -> str:
    """Maps a (phase, outcome) pair onto the wire vocabulary.

    A failure during SETUP is not the test failing -- the test never ran. `error`
    says "did not reach a verdict", which is honest; `failed` would blame the test
    for a broken fixture.
    """
    if phase in ("setup", "teardown") and outcome == "failed":
        return "error"
    return _STATUS.get(outcome, "error")


def outcome_of(phases: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Returns (phase, wire status) for the phase that decided the case."""
    for phase in ("setup", "call", "teardown"):
        report = phases.get(phase)
        if report is None:
            continue
        outcome = report["outcome"]
        if outcome != "passed":
            return phase, map_status(phase, outcome)
    if "call" in phases:
        return "call", "passed"
    # Only setup/teardown seen and both passed: the test was deselected or the
    # call phase never happened. Report it rather than dropping it.
    return "setup", "passed"


def build_case(
    nodeid: str,
    file_path: str,
    phases: dict[str, dict[str, Any]],
    reruns: list[dict[str, Any]],
    meta: dict[str, Any],
    replay: Any,
) -> Optional[Case]:
    phase, status = outcome_of(phases)
    deciding = phases.get(phase) or {}

    # Duration is the sum of the phases pytest actually ran, so a slow fixture is
    # visible rather than hidden behind a fast call.
    duration_ns = sum(int(p.get("duration_ns") or 0) for p in phases.values())

    message, trace = describe_failure(deciding.get("longrepr"))
    error = None
    if status in ("failed", "error"):
        # The full text is sent; the server truncates at 65536 and never rejects.
        error = truncate(trace or message, MAX_CASE_ERROR_RUNES)

    name = nodeid.split("::", 1)[1] if "::" in nodeid else nodeid
    replayed = replay(meta.get("messages") or [])

    properties: dict[str, str] = {"file": file_path}
    for param in replayed.case_parameters:
        properties[param.name] = "••••••" if param.masked else str(param.value)

    attempts = build_attempts(reruns, status, deciding.get("longrepr"), duration_ns)

    tags = [t[:MAX_TAG_LENGTH] for t in (list(meta.get("tags") or []) + replayed.tags)]

    case = Case(
        # The file is part of the id deliberately: two files may each hold a test
        # with the same name, and a bare name would merge their histories.
        id=nodeid,
        name=name,
        status=status,
        duration=duration_ns,
        class_name=meta.get("class_name") or file_path,
        error=error,
        description=replayed.description,
        priority=replayed.priority,
        properties=properties,
        tags=tags[:MAX_TAGS_PER_CASE],
        labels=replayed.labels[:MAX_LABELS_PER_CASE],
        links=replayed.links[:MAX_LINKS_PER_CASE],
        steps=replayed.steps[:MAX_STEPS_PER_TEST_ATTEMPT],
        attachments=replayed.attachments[:MAX_ATTACHMENTS_PER_CASE],
        attempts=attempts,
    )

    if attempts:
        # retryCount counts RETRIES, so it is one less than the attempts. isFlaky
        # follows the narrow definition the siblings use: flaky only when the run
        # ended green. "Failed after retries" is failed, not flaky.
        case.retry_count = len(attempts) - 1
        case.is_flaky = status == "passed"

    shard = meta.get("shard_index")
    if isinstance(shard, int):
        case.shard_index = shard

    return case
