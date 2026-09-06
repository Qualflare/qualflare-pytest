import pytest

# A flaky test that ENDS GREEN. The suite must contain no failing tests.
_attempts = {"count": 0}


@pytest.mark.flaky(reruns=1)
def test_fails_once_then_passes():
    _attempts["count"] += 1
    if _attempts["count"] < 2:
        # pytest supplies each attempt's traceback with no opt-in; the verifier
        # asserts this message survived into attempts[0].
        raise AssertionError("dogfood-intentional-retry")
