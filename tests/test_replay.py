"""Replaying the runtime message stream onto one Case.

The step stack is the part worth pinning. Messages arrive in emission order, so
`step_start` pushes and `step_stop` pops -- and the interesting behaviour is what
happens once the per-attempt cap is crossed, which a normal suite never reaches.
"""

from __future__ import annotations

import base64

from qualflare_pytest.constants import (
    MAX_ATTACHMENT_INLINE_CHARS,
    MAX_PARAMETERS_PER_STEP,
    MAX_STEPS_PER_TEST_ATTEMPT,
)
from qualflare_pytest.replay import replay


def start(name, **over):
    return {"kind": "step_start", "name": name, **over}


def stop(status="passed", duration=0, **over):
    return {"kind": "step_stop", "status": status, "duration": duration, **over}


class TestSteps:
    def test_a_single_step_records_its_status_and_duration(self):
        out = replay([start("outer"), stop("passed", 5_000_000)])
        assert len(out.steps) == 1
        assert out.steps[0].name == "outer"
        assert out.steps[0].status == "passed"
        assert out.steps[0].duration == 5_000_000

    def test_a_nested_step_points_at_its_parent(self):
        out = replay([start("outer"), start("inner"), stop(), stop()])
        assert out.steps[0].parent_index is None
        assert out.steps[1].parent_index == 0

    def test_siblings_share_a_parent(self):
        out = replay([start("outer"), start("a"), stop(), start("b"), stop(), stop()])
        assert [s.name for s in out.steps] == ["outer", "a", "b"]
        assert [s.parent_index for s in out.steps] == [None, 0, 0]

    def test_a_failing_step_carries_its_error(self):
        out = replay([start("outer"), stop("failed", 1, error="AssertionError: boom")])
        assert out.steps[0].status == "failed"
        assert out.steps[0].error == "AssertionError: boom"

    def test_an_unmatched_stop_is_ignored_rather_than_crashing(self):
        # A reporter must never be the reason a test run dies.
        assert replay([stop()]).steps == []

    def test_a_step_left_open_still_appears(self):
        # Its stop never arrived (the test died mid-step); losing the step
        # entirely would hide where it got to.
        out = replay([start("outer"), start("inner"), stop()])
        assert [s.name for s in out.steps] == ["outer", "inner"]

    def test_keyword_and_location_are_carried_through(self):
        out = replay([start("Given a user", keyword="Given", location="features/a.feature:3")])
        assert out.steps[0].keyword == "Given"
        assert out.steps[0].location == "features/a.feature:3"


class TestStepCap:
    def _overflowing(self):
        # One legitimate outer step wrapping far more children than the cap
        # allows, with a real duration on its own stop.
        messages = [start("outer")]
        for i in range(MAX_STEPS_PER_TEST_ATTEMPT + 100):
            messages += [start(f"s{i}"), stop("passed", 1)]
        messages.append(stop("passed", 50_000_000))
        return replay(messages)

    def test_the_step_list_stops_at_the_cap(self):
        assert len(self._overflowing().steps) == MAX_STEPS_PER_TEST_ATTEMPT

    def test_the_outer_step_keeps_its_own_duration_once_the_cap_is_crossed(self):
        # THE regression this sentinel exists for. A dropped step's matching
        # step_stop still arrives; with nothing to pop it closes whichever step
        # is legitimately open, overwriting that step's status and duration and
        # then discarding its real stop because the stack is empty. Measured
        # before the fix: an outer step wrapping a 50ms sleep reported 0.000ms.
        out = self._overflowing()
        assert out.steps[0].name == "outer"
        assert out.steps[0].duration == 50_000_000

    def test_the_steps_kept_are_the_first_ones_not_a_scrambled_selection(self):
        out = self._overflowing()
        assert [s.name for s in out.steps[:3]] == ["outer", "s0", "s1"]


class TestParameters:
    def test_a_parameter_outside_any_step_belongs_to_the_case(self):
        out = replay([{"kind": "parameter", "name": "plan", "value": "pro"}])
        assert [p.name for p in out.case_parameters] == ["plan"]
        assert out.case_parameters[0].value == "pro"

    def test_a_parameter_inside_a_step_belongs_to_that_step(self):
        out = replay(
            [start("outer"), {"kind": "parameter", "name": "sku", "value": "widget"}, stop()]
        )
        assert out.case_parameters == []
        assert [p.name for p in out.steps[0].parameters] == ["sku"]

    def test_a_parameter_lands_on_the_innermost_open_step(self):
        out = replay(
            [
                start("outer"),
                start("inner"),
                {"kind": "parameter", "name": "sku", "value": "widget"},
                stop(),
                stop(),
            ]
        )
        assert out.steps[0].parameters == []
        assert [p.name for p in out.steps[1].parameters] == ["sku"]

    def test_a_masked_parameter_drops_its_value_at_the_source(self):
        # The channel is a file on disk; the secret must never be written.
        out = replay([{"kind": "parameter", "name": "token", "value": "s3cret", "masked": True}])
        assert out.case_parameters[0].masked is True
        assert out.case_parameters[0].value is None

    def test_a_non_string_value_is_coerced(self):
        out = replay([{"kind": "parameter", "name": "count", "value": 3}])
        assert out.case_parameters[0].value == "3"

    def test_parameters_per_step_are_capped(self):
        messages = [start("outer")]
        messages += [
            {"kind": "parameter", "name": f"p{i}", "value": "v"}
            for i in range(MAX_PARAMETERS_PER_STEP + 20)
        ]
        messages.append(stop())
        out = replay(messages)
        assert len(out.steps[0].parameters) == MAX_PARAMETERS_PER_STEP


class TestSimpleMetadata:
    def test_labels_links_and_tags_accumulate(self):
        out = replay(
            [
                {"kind": "label", "name": "team", "value": "platform"},
                {"kind": "tag", "tags": ["smoke", "checkout"]},
                {"kind": "link", "url": "https://example.com/1", "type": "issue", "name": "QF-1"},
            ]
        )
        assert (out.labels[0].name, out.labels[0].value) == ("team", "platform")
        assert out.tags == ["smoke", "checkout"]
        assert (out.links[0].url, out.links[0].type) == ("https://example.com/1", "issue")

    def test_a_link_without_a_type_defaults_to_custom(self):
        out = replay([{"kind": "link", "url": "https://example.com/1"}])
        assert out.links[0].type == "custom"

    def test_the_last_description_wins(self):
        out = replay(
            [{"kind": "description", "text": "first"}, {"kind": "description", "text": "second"}]
        )
        assert out.description == "second"

    def test_a_recognised_priority_is_kept(self):
        assert replay([{"kind": "priority", "value": "high"}]).priority == "high"

    def test_an_unrecognised_priority_is_dropped_rather_than_sent(self):
        # The server normalises it away anyway, so it is not worth a row.
        assert replay([{"kind": "priority", "value": "URGENT!"}]).priority is None

    def test_an_unknown_message_kind_is_ignored(self):
        assert replay([{"kind": "something-future"}]).steps == []


class TestAttachments:
    def test_text_content_is_base64_encoded(self):
        out = replay([{"kind": "attachment", "name": "note", "content": "hello"}])
        assert out.attachments[0].content == base64.b64encode(b"hello").decode()

    def test_content_already_encoded_is_passed_through(self):
        payload = base64.b64encode(b"hello").decode()
        out = replay(
            [
                {
                    "kind": "attachment",
                    "name": "note",
                    "content": payload,
                    "encoding": "base64",
                }
            ]
        )
        assert out.attachments[0].content == payload

    def test_an_oversized_inline_attachment_is_dropped_not_truncated(self):
        # Half a base64 payload is not a usable file, and an oversized body is
        # rejected whole -- losing the launch rather than this one attachment.
        out = replay(
            [
                {
                    "kind": "attachment",
                    "name": "huge",
                    "content": "A" * (MAX_ATTACHMENT_INLINE_CHARS + 10),
                    "encoding": "base64",
                }
            ]
        )
        assert out.attachments[0].name == "huge"
        assert out.attachments[0].content is None

    def test_a_file_is_copied_into_the_output_dir_and_referenced_relatively(self, tmp_path):
        # `localImagePath` is defined relative to outputDir, which is what the
        # CLI uploads. An absolute path cannot be resolved there, and it leaks
        # the CI agent's directory layout into the report.
        source = tmp_path / "shot.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n fake")
        out_dir = tmp_path / "results"
        out = replay(
            [
                {
                    "kind": "attachment_from_file",
                    "name": "shot",
                    "path": str(source),
                    "mimeType": "image/png",
                }
            ],
            out_dir,
        )
        attachment = out.attachments[0]
        assert attachment.local_image_path is not None
        assert "/" not in attachment.local_image_path
        assert attachment.local_image_path.endswith("-shot.png")
        assert (out_dir / attachment.local_image_path).read_bytes() == source.read_bytes()
        assert attachment.file_size == source.stat().st_size
        assert attachment.content is None

    def test_two_files_with_the_same_name_do_not_collide(self, tmp_path):
        # The uuid prefix earns its keep here: two tests each attaching
        # "screenshot.png" would otherwise overwrite one another in outputDir.
        first = tmp_path / "a" / "shot.png"
        second = tmp_path / "b" / "shot.png"
        for path, payload in ((first, b"one"), (second, b"two")):
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
        out_dir = tmp_path / "results"
        out = replay(
            [
                {"kind": "attachment_from_file", "name": "s1", "path": str(first)},
                {"kind": "attachment_from_file", "name": "s2", "path": str(second)},
            ],
            out_dir,
        )
        names = [a.local_image_path for a in out.attachments]
        assert names[0] != names[1]
        assert (out_dir / names[0]).read_bytes() == b"one"
        assert (out_dir / names[1]).read_bytes() == b"two"

    def test_a_missing_file_degrades_to_a_bare_attachment(self, tmp_path):
        out = replay(
            [{"kind": "attachment_from_file", "name": "gone", "path": str(tmp_path / "nope.png")}],
            tmp_path / "results",
        )
        assert out.attachments[0].name == "gone"
        assert out.attachments[0].local_image_path is None

    def test_no_output_dir_degrades_rather_than_raising(self, tmp_path):
        source = tmp_path / "shot.png"
        source.write_bytes(b"x")
        out = replay([{"kind": "attachment_from_file", "name": "shot", "path": str(source)}], None)
        assert out.attachments[0].local_image_path is None
