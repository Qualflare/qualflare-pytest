"""The wire contract, asserted directly on `to_wire()`.

Everything here is covered end-to-end by `test_integration.py` too, but only for
the shapes a real pytest run happens to produce. These pin the rules that are
easy to break and expensive to notice: a `null` that becomes an absent key, an
`attempts` array of one, a `parentIndex` of 0 falling out because it is falsy.
None of those raise -- they produce a report the server accepts and stores
wrongly, which is exactly the class of bug the CLI seam has hit before.
"""

from __future__ import annotations

from qualflare_pytest.wire import (
    Attachment,
    Attempt,
    Case,
    Collect,
    Label,
    Link,
    Metadata,
    Parameter,
    Step,
    Suite,
)


def _metadata() -> Metadata:
    return Metadata(version="0.1.1", timestamp="2026-01-01T00:00:00Z", cli_name="qualflare-pytest")


def _collect(**over) -> Collect:
    kwargs = dict(
        framework="pytest",
        platform="api",
        os="linux",
        browser="",
        environment="development",
        language="en-US",
        metadata=_metadata(),
    )
    kwargs.update(over)
    return Collect(**kwargs)


class TestCollect:
    def test_carries_the_triple_the_cli_detects_the_format_by(self):
        # `qf collect` identifies this format by framework + metadata + suites
        # together. Lose any one and it falls back to filename detection, which
        # routes the file to the CLI's own pytest JUnit parser and misparses it.
        wire = _collect(suites=[]).to_wire()
        assert wire["framework"] == "pytest"
        assert wire["metadata"]
        assert "suites" in wire

    def test_branch_commit_and_milestone_are_present_as_null_never_omitted(self):
        # The server distinguishes "not reported" from "absent". Dropping these
        # with the other empty optionals is silent and looks harmless.
        wire = _collect().to_wire()
        assert wire["branch"] is None
        assert wire["commit"] is None
        assert wire["milestone"] is None

    def test_empty_optional_ci_fields_are_omitted_rather_than_nulled(self):
        wire = _collect().to_wire()
        for key in ("ciProvider", "ciBuildNumber", "ciRunUrl", "ciPrNumber"):
            assert key not in wire

    def test_populated_values_survive(self):
        wire = _collect(
            branch="main", commit="abc123", milestone=7, ci_provider="github", ci_pr_number=42
        ).to_wire()
        assert (wire["branch"], wire["commit"], wire["milestone"]) == ("main", "abc123", 7)
        assert wire["ciProvider"] == "github"
        assert wire["ciPrNumber"] == 42

    def test_properties_are_omitted_when_empty(self):
        assert "properties" not in _collect().to_wire()
        assert _collect(properties={"team": "platform"}).to_wire()["properties"] == {
            "team": "platform"
        }


class TestCase:
    def _case(self, **over) -> Case:
        kwargs = dict(id="t.py::test_a", name="test_a", status="passed", duration=1_000_000)
        kwargs.update(over)
        return Case(**kwargs)

    def test_a_single_attempt_is_omitted_entirely(self):
        # Below two the server persists nothing, so a one-element array is body
        # bytes spent on a row that is discarded.
        wire = self._case(attempts=[Attempt(attempt=1, status="passed")]).to_wire()
        assert "attempts" not in wire

    def test_two_attempts_are_sent_in_full_including_the_final_one(self):
        wire = self._case(
            attempts=[
                Attempt(attempt=1, status="failed", message="boom"),
                Attempt(attempt=2, status="passed"),
            ]
        ).to_wire()
        assert [a["attempt"] for a in wire["attempts"]] == [1, 2]
        assert [a["status"] for a in wire["attempts"]] == ["failed", "passed"]

    def test_a_false_is_flaky_survives_serialisation(self):
        # `_clean` drops None, not falsy. A test that failed after retries must
        # report isFlaky=false rather than saying nothing about flakiness.
        wire = self._case(status="failed", is_flaky=False, retry_count=0).to_wire()
        assert wire["isFlaky"] is False
        assert wire["retryCount"] == 0

    def test_unset_optional_fields_are_absent(self):
        wire = self._case().to_wire()
        for key in ("error", "description", "priority", "retryCount", "isFlaky", "shardIndex"):
            assert key not in wire

    def test_empty_collections_are_omitted(self):
        wire = self._case().to_wire()
        for key in ("properties", "tags", "labels", "links", "steps", "attachments"):
            assert key not in wire

    def test_shard_index_zero_is_kept(self):
        # gw0 is a real shard. Dropping it would silently merge worker 0's cases
        # into "unsharded".
        assert self._case(shard_index=0).to_wire()["shardIndex"] == 0

    def test_nested_members_are_serialised_not_left_as_dataclasses(self):
        wire = self._case(
            labels=[Label(name="team", value="platform")],
            links=[Link(url="https://example.com/1", type="issue", name="QF-1")],
            steps=[Step(name="s", status="passed", duration=5)],
            attachments=[Attachment(name="a", mime_type="text/plain", content="eA==")],
        ).to_wire()
        assert wire["labels"] == [{"name": "team", "value": "platform"}]
        assert wire["links"] == [{"url": "https://example.com/1", "type": "issue", "name": "QF-1"}]
        assert wire["steps"][0]["name"] == "s"
        assert wire["attachments"][0]["content"] == "eA=="


class TestStep:
    def test_parent_index_zero_is_kept(self):
        # THE falsy trap in this file: index 0 is the first step, and a child of
        # it that loses parentIndex is rendered as a sibling.
        assert (
            Step(name="child", status="passed", duration=1, parent_index=0).to_wire()["parentIndex"]
            == 0
        )

    def test_a_top_level_step_has_no_parent_index(self):
        assert "parentIndex" not in Step(name="top", status="passed", duration=1).to_wire()

    def test_parameters_are_omitted_when_empty_and_serialised_when_present(self):
        assert "parameters" not in Step(name="s", status="passed", duration=1).to_wire()
        wire = Step(
            name="s",
            status="passed",
            duration=1,
            parameters=[Parameter(name="sku", value="widget")],
        ).to_wire()
        assert wire["parameters"] == [{"name": "sku", "value": "widget"}]

    def test_a_zero_duration_step_still_reports_its_duration(self):
        assert Step(name="s", status="passed", duration=0).to_wire()["duration"] == 0


class TestParameter:
    def test_a_masked_parameter_carries_no_value(self):
        # The whole point of masking: the secret must not reach the report file.
        wire = Parameter(name="token", value=None, masked=True).to_wire()
        assert wire == {"name": "token", "masked": True}
        assert "value" not in wire

    def test_an_unmasked_parameter_keeps_its_value_and_omits_the_flag(self):
        assert Parameter(name="plan", value="pro").to_wire() == {"name": "plan", "value": "pro"}

    def test_an_empty_string_value_is_preserved(self):
        # Distinct from "no value": the author passed something.
        assert Parameter(name="note", value="").to_wire()["value"] == ""


class TestAttachment:
    def test_an_image_travels_by_path_with_no_inline_content(self):
        wire = Attachment(
            name="shot", mime_type="image/png", local_image_path="ab-shot.png", file_size=12
        ).to_wire()
        assert wire["localImagePath"] == "ab-shot.png"
        assert wire["fileSize"] == 12
        assert "content" not in wire

    def test_step_index_zero_is_kept(self):
        assert Attachment(name="a", step_index=0).to_wire()["stepIndex"] == 0


class TestSuite:
    def test_cases_key_is_always_present_even_when_empty(self):
        wire = Suite(name="tests/test_a.py", duration=0).to_wire()
        assert wire["cases"] == []

    def test_category_is_the_specific_framework_not_the_unit_bucket(self):
        # The server accepts the specific name, and it is what drives the
        # per-tool logo in the UI.
        assert Suite(name="s", duration=0).to_wire()["category"] == "pytest"


class TestMetadata:
    def test_run_id_is_omitted_when_unset(self):
        assert "runId" not in _metadata().to_wire()

    def test_run_id_is_sent_when_present(self):
        meta = _metadata()
        meta.run_id = "build-42"
        assert meta.to_wire()["runId"] == "build-42"


def test_the_whole_payload_is_json_serialisable():
    # A dataclass that leaked into the output would only fail at write time, in
    # sessionfinish, after the whole run has already completed.
    import json

    collect = _collect(
        suites=[
            Suite(
                name="tests/test_a.py",
                duration=10,
                cases=[
                    Case(
                        id="tests/test_a.py::test_a",
                        name="test_a",
                        status="passed",
                        duration=10,
                        labels=[Label(name="team", value="platform")],
                        steps=[Step(name="s", status="passed", duration=1)],
                        attempts=[
                            Attempt(attempt=1, status="failed"),
                            Attempt(attempt=2, status="passed"),
                        ],
                    )
                ],
            )
        ]
    )
    assert json.loads(json.dumps(collect.to_wire()))["suites"][0]["cases"][0]["name"] == "test_a"
