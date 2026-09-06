"""Per-attempt retry history.

Built from what `pytest-rerunfailures` actually emits, measured rather than
inferred. A test that fails twice then passes produces three `call`-phase reports:

    call rerun  (execution_count 1)  <- carries its own traceback
    call rerun  (execution_count 2)  <- carries its own traceback
    call passed (execution_count 3)

Identical under `-n 2`. `execution_count` is set only on tests rerunfailures
manages, so it is optional everywhere and the ordinal falls back to arrival order.

rerunfailures is an OPTIONAL dependency. Without it no report ever has outcome
"rerun", this produces nothing, and that is the correct result -- not an error.
"""

from __future__ import annotations

from typing import Any

from .constants import (
    MAX_ATTEMPT_MESSAGE_RUNES,
    MAX_ATTEMPT_TRACE_RUNES,
    MAX_ATTEMPTS_PER_CASE,
)
from .text import truncate
from .wire import Attempt


def describe_failure(longrepr: Any) -> tuple[str | None, str | None]:
    """Extracts (message, trace) from a report's longrepr.

    longrepr has three shapes in practice: a rich ExceptionRepr for a failure, a
    plain string, and a (path, lineno, reason) TUPLE for a skip. The tuple form
    is easy to miss and renders as a meaningless repr if treated as a string.
    """
    if longrepr is None:
        return None, None
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return truncate(str(longrepr[2]), MAX_ATTEMPT_MESSAGE_RUNES), None
    text = str(longrepr)
    if not text:
        return None, None

    # `reprcrash.message` is pytest's own one-line summary of the failure --
    # "AssertionError: boom attempt 1". Deriving it from the rendered traceback
    # instead is wrong: that text ENDS with the location line
    # ("test_suite.py:11: AssertionError"), so taking the last line yields a file
    # reference where the reader expects the assertion.
    crash = getattr(longrepr, "reprcrash", None)
    message = getattr(crash, "message", None)
    if not message:
        # No reprcrash (a plain string longrepr, or a custom repr): fall back to
        # the first line that carries pytest's "E   " error marker, then to the
        # first line of all.
        lines = [ln for ln in text.splitlines() if ln.strip()]
        marked = [ln.strip()[1:].strip() for ln in lines if ln.lstrip().startswith("E ")]
        message = marked[0] if marked else (lines[0] if lines else text)

    return (
        truncate(str(message), MAX_ATTEMPT_MESSAGE_RUNES),
        truncate(text, MAX_ATTEMPT_TRACE_RUNES),
    )


def build_attempts(
    reruns: list[dict[str, Any]], final_status: str, final_longrepr: Any, final_duration_ns: int
) -> list[Attempt]:
    """Assembles attempts[], every entry including the final one, 1-based.

    Returns [] below two attempts: the server persists nothing for a lone attempt,
    so sending one costs body bytes for a row that is discarded.
    """
    if not reruns:
        return []

    out: list[Attempt] = []
    for index, rerun in enumerate(reruns, start=1):
        message, trace = describe_failure(rerun.get("longrepr"))
        # A retry triggered by a failing FIXTURE is not the test body failing.
        # rerunfailures retries setup failures too, so the phase decides the
        # status -- the same rule map_status applies to the final outcome.
        phase = rerun.get("when") or "call"
        out.append(
            Attempt(
                attempt=int(rerun.get("execution_count") or index),
                status="error" if phase in ("setup", "teardown") else "failed",
                duration=rerun.get("duration_ns"),
                message=message,
                trace=trace,
            )
        )

    terminal = Attempt(attempt=out[-1].attempt + 1, status=final_status, duration=final_duration_ns)
    # "error" as well as "failed": a fixture that keeps failing across every retry
    # ends as `error`, and the terminal attempt is the one entry that explains why
    # the retries were exhausted. Testing only for "failed" shipped it blank.
    if final_status in ("failed", "error"):
        terminal.message, terminal.trace = describe_failure(final_longrepr)
    out.append(terminal)

    if len(out) < 2:
        return []
    return clamp_attempts(out)


def clamp_attempts(attempts: list[Attempt]) -> list[Attempt]:
    """Bounds the list, keeping the FINAL attempt.

    A plain head-slice would discard the attempt carrying the outcome -- the only
    one that explains why the case passed or failed.
    """
    if len(attempts) <= MAX_ATTEMPTS_PER_CASE:
        return attempts
    return attempts[: MAX_ATTEMPTS_PER_CASE - 1] + [attempts[-1]]
