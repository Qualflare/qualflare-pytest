"""Phase-aware case construction, driven directly rather than through a run.

`test_integration.py` proves these mappings for the handful of shapes a real
suite produces. Reaching the rest that way means writing a test whose fixture
fails in teardown only on the third attempt, which is a lot of machinery to
assert one branch. Here the phase dicts are just data.

The phase table these mirror, measured on pytest 9.1.1:

    a passing test        setup passed  | call passed  | teardown passed
    a failing test        setup passed  | call failed  | teardown passed
    @pytest.mark.skip     setup skipped |    (none)    | teardown passed
    a fixture that raises setup failed  |    (none)    | teardown passed
"""

from __future__ import annotations

from qualflare_pytest.case_builder import build_case, map_status, outcome_of
from qualflare_pytest.constants import MAX_TAG_LENGTH, MAX_TAGS_PER_CASE
from qualflare_pytest.replay import replay


def phase(outcome: str, duration_ns: int = 1_000_000, longrepr=None) -> dict:
    return {"outcome": outcome, "duration_ns": duration_ns, "longrepr": longrepr}


def build(phases, reruns=None, meta=None, nodeid="tests/test_a.py::test_thing"):
    return build_case(
        nodeid=nodeid,
        file_path="tests/test_a.py",
        phases=phases,
        reruns=reruns or [],
        meta=meta or {},
        replay=replay,
    )


class TestMapStatus:
    def test_a_failure_in_setup_is_an_error_not_a_failure(self):
        # The test never ran, so blaming it for a broken fixture is a lie the
        # report then repeats in every flakiness metric downstream.
        assert map_status("setup", "failed") == "error"

    def test_a_failure_in_teardown_is_also_an_error(self):
        assert map_status("teardown", "failed") == "error"

    def test_a_failure_in_the_call_phase_is_a_failure(self):
        assert map_status("call", "failed") == "failed"

    def test_skipped_stays_skipped_in_every_phase(self):
        assert map_status("setup", "skipped") == "skipped"
        assert map_status("call", "skipped") == "skipped"

    def test_an_unknown_outcome_degrades_to_error_rather_than_passing(self):
        # Fail closed: an outcome this plugin does not recognise must never be
        # reported as a pass.
        assert map_status("call", "something-new") == "error"


class TestOutcomeOf:
    def test_all_phases_passing_is_decided_by_call(self):
        assert outcome_of(
            {"setup": phase("passed"), "call": phase("passed"), "teardown": phase("passed")}
        ) == ("call", "passed")

    def test_the_first_non_passing_phase_decides(self):
        assert outcome_of(
            {"setup": phase("passed"), "call": phase("failed"), "teardown": phase("passed")}
        ) == ("call", "failed")

    def test_a_skip_recorded_in_setup_is_found_even_though_call_never_ran(self):
        # A plugin listening only for `when == "call"` drops this case entirely.
        assert outcome_of({"setup": phase("skipped"), "teardown": phase("passed")}) == (
            "setup",
            "skipped",
        )

    def test_a_fixture_error_is_found_even_though_call_never_ran(self):
        assert outcome_of({"setup": phase("failed"), "teardown": phase("passed")}) == (
            "setup",
            "error",
        )

    def test_setup_takes_precedence_over_a_later_failing_phase(self):
        assert outcome_of({"setup": phase("failed"), "teardown": phase("failed")})[0] == "setup"

    def test_a_teardown_failure_after_a_passing_call_is_reported(self):
        assert outcome_of(
            {"setup": phase("passed"), "call": phase("passed"), "teardown": phase("failed")}
        ) == ("teardown", "error")

    def test_setup_and_teardown_only_and_both_passed_still_yields_a_case(self):
        # Rather than dropping it: something ran, and a vanished case is worse
        # than an oddly-shaped one.
        assert outcome_of({"setup": phase("passed"), "teardown": phase("passed")}) == (
            "setup",
            "passed",
        )


class TestBuildCase:
    def test_duration_is_the_sum_of_every_phase_that_ran(self):
        # Not the call phase alone: a slow fixture should be visible rather than
        # hidden behind a fast assertion.
        case = build(
            {
                "setup": phase("passed", 3_000_000),
                "call": phase("passed", 1_000_000),
                "teardown": phase("passed", 500_000),
            }
        )
        assert case.duration == 4_500_000

    def test_the_id_keeps_the_file_but_the_name_does_not(self):
        # Two files may each hold a test with the same name; a bare id would
        # merge their histories.
        case = build({"call": phase("passed")}, nodeid="tests/test_a.py::test_thing")
        assert case.id == "tests/test_a.py::test_thing"
        assert case.name == "test_thing"

    def test_a_nodeid_without_a_separator_falls_back_to_itself(self):
        case = build({"call": phase("passed")}, nodeid="tests/test_a.py")
        assert case.name == "tests/test_a.py"

    def test_a_parametrised_name_is_kept_intact(self):
        case = build({"call": phase("passed")}, nodeid="tests/test_a.py::test_x[a-1]")
        assert case.name == "test_x[a-1]"

    def test_a_passing_case_carries_no_error(self):
        assert build({"call": phase("passed")}).error is None

    def test_a_failing_case_carries_the_failure_text(self):
        case = build({"call": phase("failed", longrepr="E   AssertionError: boom")})
        assert case.error is not None
        assert "boom" in case.error

    def test_the_file_is_recorded_as_a_property(self):
        assert build({"call": phase("passed")}).properties["file"] == "tests/test_a.py"

    def test_class_name_falls_back_to_the_file(self):
        assert build({"call": phase("passed")}).class_name == "tests/test_a.py"

    def test_class_name_from_metadata_wins(self):
        assert build({"call": phase("passed")}, meta={"class_name": "TestThing"}).class_name == (
            "TestThing"
        )


class TestRetryFields:
    def _flaky(self, final="passed"):
        return build(
            {"call": phase(final)},
            reruns=[{"when": "call", "longrepr": "E   AssertionError: boom", "execution_count": 1}],
        )

    def test_retry_count_is_one_less_than_the_attempts(self):
        case = self._flaky()
        assert len(case.attempts) == 2
        assert case.retry_count == 1

    def test_a_run_that_ended_green_is_flaky(self):
        assert self._flaky("passed").is_flaky is True

    def test_a_run_that_failed_after_retries_is_not_flaky(self):
        # The narrow definition the sibling reporters use: "failed after
        # retries" is failed, not flaky.
        case = self._flaky("failed")
        assert case.is_flaky is False
        assert case.status == "failed"

    def test_a_case_that_never_retried_reports_no_retry_fields(self):
        case = build({"call": phase("passed")})
        assert case.attempts == []
        assert case.retry_count is None
        assert case.is_flaky is None


class TestMetadataApplied:
    def test_a_masked_parameter_never_reaches_the_properties(self):
        case = build(
            {"call": phase("passed")},
            meta={
                "messages": [
                    {"kind": "parameter", "name": "token", "value": "s3cret", "masked": True}
                ]
            },
        )
        assert case.properties["token"] == "••••••"
        assert "s3cret" not in str(case.properties)

    def test_tags_are_capped_in_count(self):
        case = build(
            {"call": phase("passed")},
            meta={"tags": [f"t{i}" for i in range(MAX_TAGS_PER_CASE + 25)]},
        )
        assert len(case.tags) == MAX_TAGS_PER_CASE

    def test_an_overlong_tag_is_clipped_rather_than_dropped(self):
        case = build({"call": phase("passed")}, meta={"tags": ["x" * (MAX_TAG_LENGTH + 50)]})
        assert len(case.tags[0]) == MAX_TAG_LENGTH

    def test_marker_tags_and_runtime_tags_are_merged(self):
        case = build(
            {"call": phase("passed")},
            meta={"tags": ["from-marker"], "messages": [{"kind": "tag", "tags": ["from-runtime"]}]},
        )
        assert set(case.tags) == {"from-marker", "from-runtime"}

    def test_a_shard_index_of_zero_is_recorded(self):
        # gw0 is a real worker; treating 0 as "unset" merges its cases in wrongly.
        assert build({"call": phase("passed")}, meta={"shard_index": 0}).shard_index == 0

    def test_a_non_integer_shard_index_is_ignored(self):
        assert build({"call": phase("passed")}, meta={"shard_index": "gw0"}).shard_index is None
