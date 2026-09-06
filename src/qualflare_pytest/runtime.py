"""The author-facing metadata API: `qualflare.label()`, `.step()`, and friends.

HOW METADATA REACHES THE REPORTER

pytest gives a test body no direct line to a plugin's reporting hooks, but it does
give a supported channel: `TestReport.user_properties`. Anything appended there is
serialised with the report, so under `pytest-xdist` it travels from the worker to
the controller -- which is where this plugin builds the report. That is why no
temp-directory side channel is needed here, unlike the Jest and Mocha reporters.

THE CONSTRAINT THAT MAKES `_json_safe` MANDATORY

Values on `user_properties` must be JSON-serialisable. That is undocumented and
unenforced, and the failure is asymmetric -- measured on pytest 9.1.1:

    serial    -> exit 1, TypeError, loud
    -n 2      -> exit 0, xdist INTERNALERROR, worker dead, BUILD GREEN

So an unserialisable value a user passes to `qualflare.parameter()` would turn a
parallel run green while silently losing a worker. Everything is coerced here,
before it is ever attached.

Every call is fire-and-forget and fail-open: a metadata problem must never fail
somebody's test run.
"""

from __future__ import annotations

import time
from typing import Any

from .constants import USER_PROPERTY_KEY

# Set by the plugin for the duration of each test. Module state is safe here in a
# way it was not for the JS packages: pytest runs one test at a time per process,
# and the runtime and the plugin are the same import in the same interpreter.
_current: dict[str, Any] | None = None
_open_steps: list[int] = []


def _bind(bucket: dict[str, Any]) -> None:
    global _current
    _current = bucket
    _open_steps.clear()


def _unbind() -> None:
    global _current
    _current = None
    _open_steps.clear()


def _json_safe(value: Any) -> Any:
    """Coerces a value into something that survives xdist's report serialisation.

    Containers are walked so a dict of dicts is not silently accepted and then
    exploded at the process boundary. Anything else becomes its `repr`, which is
    lossy but honest, and cannot crash a worker.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return repr(value)


def _emit(kind: str, payload: dict[str, Any]) -> None:
    if _current is None:
        # Outside a test body -- a session fixture, module scope, or the plugin
        # was never loaded. Dropped rather than attributed to whichever test runs
        # next; silent misattribution is worse than absent data.
        return
    payload = {str(k): _json_safe(v) for k, v in payload.items()}
    payload["kind"] = kind
    _current.setdefault("messages", []).append(payload)


class _Qualflare:
    """The object exported as `qualflare`."""

    def label(self, name: str, value: str) -> None:
        """Allure-style name/value metadata (epic, feature, story, owner, ...)."""
        _emit("label", {"name": str(name), "value": str(value)})

    def link(self, url: str, type: str = "custom", name: str | None = None) -> None:
        """An external link. `type` is issue/tms/custom; unknown values are
        rejected server-side rather than rewritten, so it is passed through."""
        _emit("link", {"url": str(url), "type": str(type), "name": name})

    def tag(self, *tags: str) -> None:
        if tags:
            _emit("tag", {"tags": [str(t) for t in tags]})

    def description(self, text: str) -> None:
        _emit("description", {"text": str(text)})

    def priority(self, value: str) -> None:
        _emit("priority", {"value": str(value)})

    def parameter(self, name: str, value: Any = None, masked: bool = False) -> None:
        """A case- or step-level parameter.

        MASKING DROPS THE VALUE HERE, before anything is serialised, so a secret
        never reaches the report file or the server. The wire contract treats
        `masked` as a display hint only -- the server does not redact -- so doing
        it at the source is the only thing that actually protects the value.
        """
        _emit(
            "parameter",
            {"name": str(name), "value": None if masked else value, "masked": bool(masked)},
        )

    def attachment(
        self, name: str, content: str, mime_type: str | None = None, encoding: str = "utf8"
    ) -> None:
        """Attaches in-memory content. Images are offloaded to `outputDir` by the
        plugin, which owns that directory."""
        _emit(
            "attachment",
            {"name": str(name), "content": content, "mimeType": mime_type, "encoding": encoding},
        )

    def attachment_from_file(
        self, name: str, path: str, mime_type: str | None = None
    ) -> None:
        """Attaches a file by path. Only the path travels; the plugin reads it."""
        _emit("attachment_from_file", {"name": str(name), "path": str(path), "mimeType": mime_type})

    def step(self, name: str) -> _Step:
        """Records a named step. Use as a context manager:

            with qualflare.step("add to cart"):
                ...

        The user's exception is always re-raised untouched; only the bookkeeping
        is wrapped, so this can never swallow or alter a test's own failure.
        """
        return _Step(name)


class _Step:
    def __init__(self, name: str) -> None:
        self._name = name
        self._started = 0.0

    def __enter__(self) -> _Step:
        self._started = time.perf_counter()
        _emit("step_start", {"name": self._name})
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        duration_ns = int((time.perf_counter() - self._started) * 1_000_000_000)
        _emit(
            "step_stop",
            {
                "status": "failed" if exc_type is not None else "passed",
                "error": str(exc) if exc is not None else None,
                "duration": duration_ns,
            },
        )
        # Returns None, never True: this must never suppress the test's own
        # exception. Typing it as bool would tell callers it might.


qualflare = _Qualflare()

__all__ = ["qualflare", "USER_PROPERTY_KEY"]
