"""Per-attempt retry history and failure description.

`longrepr` is the awkward part. It has three shapes in practice -- a rich
ExceptionRepr, a plain string, and a `(path, lineno, reason)` TUPLE for a skip --
and the tuple form renders as a meaningless repr if treated as a string. Driving
all three through a real run needs pytest-rerunfailures installed and a suite
that fails on a schedule; here they are just objects.
"""

from __future__ import annotations

from qualflare_pytest.attempts import build_attempts, clamp_attempts, describe_failure
from qualflare_pytest.constants import MAX_ATTEMPT_MESSAGE_RUNES, MAX_ATTEMPTS_PER_CASE
from qualflare_pytest.wire import Attempt


class FakeCrash:
    def __init__(self, message: str):
        self.message = message


class FakeLongrepr:
    """Stands in for pytest's ExceptionRepr: renders as the full traceback and
    carries `reprcrash.message` as its own one-line summary."""

    def __init__(self, text: str, message: str | None = None):
        self._text = text
        if message is not None:
            self.reprcrash = FakeCrash(message)

    def __str__(self) -> str:
        return self._text


TRACEBACK = (
    "def test_thing():\n"
    ">       assert value == 3\n"
    "E       AssertionError: assert 2 == 3\n"
    "\n"
    "tests/test_suite.py:11: AssertionError"
)


class TestDescribeFailure:
    def test_nothing_in_nothing_out(self):
        assert describe_failure(None) == (None, None)

    def test_the_message_comes_from_reprcrash_not_the_last_line(self):
        # The rendered traceback ENDS with the location line, so taking the last
        # line yields "tests/test_suite.py:11: AssertionError" -- a file
        # reference where the reader expects the assertion.
        message, trace = describe_failure(FakeLongrepr(TRACEBACK, "AssertionError: assert 2 == 3"))
        assert message == "AssertionError: assert 2 == 3"
        assert trace == TRACEBACK
        assert not message.startswith("tests/test_suite.py")

    def test_without_reprcrash_the_marked_error_line_is_used(self):
        # A plain-string longrepr has no reprcrash. pytest marks the failure line
        # with "E   ", which is a better summary than the first line of source.
        message, trace = describe_failure(TRACEBACK)
        assert message == "AssertionError: assert 2 == 3"
        assert trace == TRACEBACK

    def test_without_a_marker_the_first_non_empty_line_is_used(self):
        message, _ = describe_failure("\n\nRuntimeError: exploded\nsecond line")
        assert message == "RuntimeError: exploded"

    def test_a_skip_tuple_yields_its_reason_and_no_trace(self):
        # The shape that is easy to miss: `(path, lineno, reason)`. Treated as a
        # string it renders as the tuple's repr.
        message, trace = describe_failure(("tests/test_a.py", 10, "Skipped: deliberate"))
        assert message == "Skipped: deliberate"
        assert trace is None

    def test_a_two_element_tuple_is_not_mistaken_for_a_skip(self):
        message, _ = describe_failure(("only", "two"))
        assert message == "('only', 'two')"

    def test_an_empty_longrepr_yields_nothing(self):
        assert describe_failure("") == (None, None)

    def test_an_oversized_message_is_clamped_to_what_the_server_stores(self):
        message, _ = describe_failure("E   " + "x" * (MAX_ATTEMPT_MESSAGE_RUNES * 2))
        assert len(message) == MAX_ATTEMPT_MESSAGE_RUNES


class TestBuildAttempts:
    def test_no_reruns_produces_nothing(self):
        # Not a one-element array: below two the server persists nothing, so it
        # would be body bytes for a discarded row.
        assert build_attempts([], "passed", None, 1_000) == []

    def test_a_flaky_run_records_every_attempt_including_the_final_pass(self):
        attempts = build_attempts(
            [
                {"when": "call", "longrepr": "E   AssertionError: boom 1", "execution_count": 1},
                {"when": "call", "longrepr": "E   AssertionError: boom 2", "execution_count": 2},
            ],
            "passed",
            None,
            5_000_000,
        )
        assert [a.attempt for a in attempts] == [1, 2, 3]
        assert [a.status for a in attempts] == ["failed", "failed", "passed"]
        assert attempts[0].message == "AssertionError: boom 1"
        # The final attempt passed, so it contributed no failure text.
        assert attempts[2].message is None
        assert attempts[2].duration == 5_000_000

    def test_the_terminal_attempt_of_a_failing_run_explains_why(self):
        attempts = build_attempts(
            [{"when": "call", "longrepr": "E   AssertionError: boom 1", "execution_count": 1}],
            "failed",
            FakeLongrepr(TRACEBACK, "AssertionError: final"),
            1_000,
        )
        assert attempts[-1].status == "failed"
        assert attempts[-1].message == "AssertionError: final"

    def test_the_terminal_attempt_of_an_errored_run_also_explains_why(self):
        # A fixture that keeps failing ends as `error`, not `failed`. Testing
        # only for "failed" here shipped this blank.
        attempts = build_attempts(
            [{"when": "setup", "longrepr": "boom", "execution_count": 1}],
            "error",
            FakeLongrepr(TRACEBACK, "RuntimeError: fixture exploded"),
            1_000,
        )
        assert attempts[-1].status == "error"
        assert attempts[-1].message == "RuntimeError: fixture exploded"

    def test_a_rerun_triggered_by_a_fixture_is_an_error_not_a_failure(self):
        # rerunfailures retries setup failures too; the phase decides, exactly as
        # it does for the final outcome.
        attempts = build_attempts(
            [{"when": "setup", "longrepr": "boom", "execution_count": 1}], "passed", None, 1_000
        )
        assert attempts[0].status == "error"

    def test_a_rerun_in_the_call_phase_is_a_failure(self):
        attempts = build_attempts(
            [{"when": "call", "longrepr": "boom", "execution_count": 1}], "passed", None, 1_000
        )
        assert attempts[0].status == "failed"

    def test_a_missing_phase_defaults_to_call(self):
        attempts = build_attempts([{"longrepr": "boom"}], "passed", None, 1_000)
        assert attempts[0].status == "failed"

    def test_the_ordinal_falls_back_to_arrival_order_without_execution_count(self):
        # `execution_count` is set only on tests rerunfailures manages, so it is
        # optional everywhere.
        attempts = build_attempts(
            [{"when": "call", "longrepr": "a"}, {"when": "call", "longrepr": "b"}],
            "passed",
            None,
            1_000,
        )
        assert [a.attempt for a in attempts] == [1, 2, 3]

    def test_per_attempt_durations_are_carried_when_reported(self):
        attempts = build_attempts(
            [{"when": "call", "longrepr": "a", "duration_ns": 250_000}], "passed", None, 900_000
        )
        assert attempts[0].duration == 250_000
        assert attempts[-1].duration == 900_000


class TestClampAttempts:
    def test_a_list_within_the_cap_is_untouched(self):
        attempts = [Attempt(attempt=i, status="failed") for i in range(1, 4)]
        assert clamp_attempts(attempts) == attempts

    def test_an_oversized_list_keeps_the_final_attempt(self):
        # A plain head-slice would discard the only attempt that explains the
        # outcome.
        attempts = [Attempt(attempt=i, status="failed") for i in range(1, 81)]
        attempts[-1].status = "passed"
        clamped = clamp_attempts(attempts)
        assert len(clamped) == MAX_ATTEMPTS_PER_CASE
        assert clamped[-1].attempt == 80
        assert clamped[-1].status == "passed"
        assert clamped[-2].attempt == MAX_ATTEMPTS_PER_CASE - 1

    def test_build_attempts_applies_the_cap(self):
        reruns = [{"when": "call", "longrepr": f"boom {i}"} for i in range(80)]
        attempts = build_attempts(reruns, "passed", None, 1_000)
        assert len(attempts) == MAX_ATTEMPTS_PER_CASE
        assert attempts[-1].status == "passed"
