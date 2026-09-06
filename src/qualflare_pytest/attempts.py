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

from typing import Any, Optional

from .constants import (
    MAX_ATTEMPT_MESSAGE_RUNES,
    MAX_ATTEMPT_TRACE_RUNES,
    MAX_ATTEMPTS_PER_CASE,
)
from .text import truncate
from .wire import Attempt


def describe_failure(longrepr: Any) -> tuple[Optional[str], Optional[str]]:
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
    # The last line of a pytest traceback is the assertion line; the whole thing
    # is the trace.
    last = text.strip().splitlines()[-1] if text.strip() else text
    return truncate(last, MAX_ATTEMPT_MESSAGE_RUNES), truncate(text, MAX_ATTEMPT_TRACE_RUNES)


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
        out.append(
            Attempt(
                attempt=int(rerun.get("execution_count") or index),
                status="failed",
                duration=rerun.get("duration_ns"),
                message=message,
                trace=trace,
            )
        )

    terminal = Attempt(attempt=out[-1].attempt + 1, status=final_status, duration=final_duration_ns)
    if final_status == "failed":
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
