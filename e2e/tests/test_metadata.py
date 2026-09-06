import pytest

from qualflare_pytest import qualflare


@pytest.mark.smoke
def test_records_the_author_facing_metadata_api():
    qualflare.label("team", "platform")
    qualflare.link(
        "https://github.com/Qualflare/qualflare-pytest", type="custom", name="repository"
    )
    qualflare.tag("dogfood")
    qualflare.priority("high")
    qualflare.description(
        "Exercises every metadata call in one case, so the verifier can assert them together."
    )
    qualflare.parameter("plan", "enterprise")


def test_nests_steps():
    # Nested deliberately: this is what produces a step with a parentIndex, which
    # the verifier asserts. Collapsing it into one `with` would silently remove
    # the only nesting coverage in the dogfood suite.
    with qualflare.step("outer"):  # noqa: SIM117
        with qualflare.step("inner"):
            qualflare.parameter("sku", "widget")


def test_masks_a_parameter():
    # The verifier asserts this string appears NOWHERE in the payload. Masking
    # happens at the source, so absence from the whole file is the only real
    # proof that it worked.
    qualflare.parameter("token", "qf-dogfood-secret-value", masked=True)


def test_reports_a_plain_passing_test():
    """The baseline: a case carrying no metadata at all must still land."""
