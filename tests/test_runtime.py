"""The author-facing API, and the coercion that keeps xdist alive.

`_json_safe` is the load-bearing part. Values placed on `TestReport.user_properties`
must be JSON-serialisable; that is undocumented, unenforced, and fails
ASYMMETRICALLY -- measured on pytest 9.1.1 with one bad value attached:

    serial  -> exit 1, TypeError in the output, loud
    -n 2    -> exit 0, xdist INTERNALERROR, worker dead, BUILD GREEN

A user passing an arbitrary object to `qualflare.parameter()` would therefore
turn a parallel run green while silently losing a worker's results. These pin the
coercion that prevents it, which is why they assert `json.dumps` round-trips
rather than merely checking a type.
"""

from __future__ import annotations

import json

import pytest

from qualflare_pytest import runtime
from qualflare_pytest.runtime import _json_safe, qualflare


@pytest.fixture
def bucket():
    """Binds a fresh message bucket, the way the plugin does per test."""
    store: dict = {}
    runtime._bind(store)
    yield store
    runtime._unbind()


def messages(store: dict) -> list[dict]:
    return store.get("messages", [])


class Unserialisable:
    """Stands in for whatever a user actually passes: a model, a mock, a file."""

    def __repr__(self) -> str:
        return "<Unserialisable object>"


class TestJsonSafe:
    @pytest.mark.parametrize("value", [None, "text", 3, 3.5, True])
    def test_primitives_pass_through_unchanged(self, value):
        assert _json_safe(value) == value

    def test_an_arbitrary_object_becomes_its_repr(self):
        # Lossy but honest, and it cannot kill a worker.
        assert _json_safe(Unserialisable()) == "<Unserialisable object>"

    def test_containers_are_walked_not_merely_accepted(self):
        # The trap: a list or dict is itself JSON-serialisable, so a shallow check
        # passes and the payload explodes at the process boundary instead.
        result = _json_safe({"outer": [Unserialisable(), {"inner": Unserialisable()}]})
        assert result == {
            "outer": ["<Unserialisable object>", {"inner": "<Unserialisable object>"}]
        }

    def test_a_tuple_becomes_a_list(self):
        assert _json_safe((1, 2)) == [1, 2]

    def test_non_string_dict_keys_are_stringified(self):
        # json.dumps would accept an int key by coercing it, but not a tuple one.
        assert _json_safe({1: "a", (2, 3): "b"}) == {"1": "a", "(2, 3)": "b"}

    @pytest.mark.parametrize(
        "value",
        [
            Unserialisable(),
            {"k": Unserialisable()},
            [Unserialisable()],
            {"deep": [{"deeper": Unserialisable()}]},
            {(1, 2): Unserialisable()},
        ],
    )
    def test_the_result_always_survives_json_dumps(self, value):
        # The property that actually matters. Asserting the type would miss a
        # container whose contents are still unserialisable.
        json.dumps(_json_safe(value))


class TestEmissionRequiresATest:
    def test_metadata_outside_a_test_is_dropped_not_misattributed(self):
        # Module scope, a session fixture, or the plugin never loaded. Attaching
        # it to whichever test runs next is silent wrong data, which is worse
        # than absent data.
        runtime._unbind()
        qualflare.label("team", "platform")  # must not raise
        assert runtime._current is None

    def test_calls_outside_a_test_never_raise(self):
        # Fire-and-forget: a metadata problem must never fail somebody's run.
        runtime._unbind()
        qualflare.tag("a")
        qualflare.priority("high")
        qualflare.parameter("k", "v")
        qualflare.attachment("n", "c")
        with qualflare.step("s"):
            pass


class TestMessages:
    def test_a_label_is_recorded_with_its_kind(self, bucket):
        qualflare.label("team", "platform")
        assert messages(bucket) == [{"name": "team", "value": "platform", "kind": "label"}]

    def test_a_link_defaults_to_the_custom_type(self, bucket):
        qualflare.link("https://example.com/1")
        assert messages(bucket)[0]["type"] == "custom"

    def test_a_link_keeps_an_explicit_type_and_name(self, bucket):
        qualflare.link("https://example.com/1", type="issue", name="QF-1")
        message = messages(bucket)[0]
        assert (message["type"], message["name"]) == ("issue", "QF-1")

    def test_tags_are_recorded_together(self, bucket):
        qualflare.tag("smoke", "checkout")
        assert messages(bucket)[0]["tags"] == ["smoke", "checkout"]

    def test_tagging_with_nothing_emits_nothing(self, bucket):
        qualflare.tag()
        assert messages(bucket) == []

    def test_description_and_priority_are_recorded(self, bucket):
        qualflare.description("why this matters")
        qualflare.priority("high")
        assert [m["kind"] for m in messages(bucket)] == ["description", "priority"]

    def test_non_string_arguments_are_coerced(self, bucket):
        qualflare.label(1, 2)
        assert messages(bucket)[0] == {"name": "1", "value": "2", "kind": "label"}


class TestParameter:
    def test_a_plain_parameter_keeps_its_value(self, bucket):
        qualflare.parameter("plan", "pro")
        message = messages(bucket)[0]
        assert message["value"] == "pro"
        assert message["masked"] is False

    def test_masking_drops_the_value_at_the_source(self, bucket):
        # The wire contract treats `masked` as a display hint -- the server does
        # not redact -- so dropping it here is the only thing that protects it.
        qualflare.parameter("token", "s3cret", masked=True)
        message = messages(bucket)[0]
        assert message["masked"] is True
        assert message["value"] is None
        assert "s3cret" not in json.dumps(bucket)

    def test_an_unserialisable_value_cannot_reach_user_properties(self, bucket):
        # The exact call that turned a parallel run green while killing a worker.
        qualflare.parameter("model", Unserialisable())
        assert messages(bucket)[0]["value"] == "<Unserialisable object>"
        json.dumps(bucket)

    def test_a_masked_unserialisable_value_is_still_dropped(self, bucket):
        qualflare.parameter("model", Unserialisable(), masked=True)
        assert messages(bucket)[0]["value"] is None


class TestAttachments:
    def test_inline_content_records_its_encoding(self, bucket):
        qualflare.attachment("note", "hello", mime_type="text/plain")
        message = messages(bucket)[0]
        assert (message["kind"], message["mimeType"], message["encoding"]) == (
            "attachment",
            "text/plain",
            "utf8",
        )

    def test_a_file_attachment_carries_only_the_path(self, bucket):
        qualflare.attachment_from_file("shot", "/tmp/shot.png", mime_type="image/png")
        message = messages(bucket)[0]
        assert message["kind"] == "attachment_from_file"
        assert message["path"] == "/tmp/shot.png"
        assert "content" not in message


class TestStep:
    def test_a_step_brackets_its_body_with_start_and_stop(self, bucket):
        with qualflare.step("add to cart"):
            pass
        kinds = [m["kind"] for m in messages(bucket)]
        assert kinds == ["step_start", "step_stop"]
        assert messages(bucket)[0]["name"] == "add to cart"
        assert messages(bucket)[1]["status"] == "passed"

    def test_nesting_produces_the_order_the_replayer_expects(self, bucket):
        # The nesting IS the subject here. Collapsing it into a single `with`
        # would emit the same messages, but the test would no longer say that a
        # step opened inside another step is what produces them.
        with qualflare.step("outer"):  # noqa: SIM117
            with qualflare.step("inner"):
                pass
        assert [m["kind"] for m in messages(bucket)] == [
            "step_start",
            "step_start",
            "step_stop",
            "step_stop",
        ]

    def test_a_failing_step_is_recorded_as_failed_with_its_error(self, bucket):
        # `raises` has to wrap the step rather than sit beside it: the assertion
        # is that the step records the failure AND still lets it through.
        with pytest.raises(ValueError):  # noqa: SIM117
            with qualflare.step("explodes"):
                raise ValueError("boom")
        stop = messages(bucket)[-1]
        assert stop["status"] == "failed"
        assert stop["error"] == "boom"

    def test_the_users_exception_is_never_swallowed(self, bucket):
        # __exit__ must return None, never True. Suppressing here would turn a
        # failing test green -- the worst thing a reporter can do.
        with pytest.raises(ValueError):  # noqa: SIM117
            with qualflare.step("explodes"):
                raise ValueError("boom")

    def test_a_step_records_a_duration(self, bucket):
        with qualflare.step("work"):
            sum(range(10_000))
        assert messages(bucket)[-1]["duration"] >= 0

    def test_a_parameter_inside_a_step_is_emitted_between_its_boundaries(self, bucket):
        # Ordering is what makes the replayer able to attribute it to the step;
        # there is no step id on the message.
        with qualflare.step("outer"):
            qualflare.parameter("sku", "widget")
        assert [m["kind"] for m in messages(bucket)] == ["step_start", "parameter", "step_stop"]


def test_binding_a_new_test_does_not_inherit_the_previous_one_s_messages():
    first: dict = {}
    runtime._bind(first)
    qualflare.label("a", "1")
    second: dict = {}
    runtime._bind(second)
    qualflare.label("b", "2")
    runtime._unbind()
    assert [m["name"] for m in first["messages"]] == ["a"]
    assert [m["name"] for m in second["messages"]] == ["b"]
