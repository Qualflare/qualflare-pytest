"""The pytest plugin: hooks, report collection, and the single report write.

WHERE THIS RUNS, WHICH DECIDES EVERYTHING ELSE

Under `pytest-xdist`, workers execute tests and send serialised reports back; the
CONTROLLER forwards them to `pytest_runtest_logreport`. So this plugin observes
every result on the controller and writes exactly ONE report file per run --
unlike the JavaScript reporters, which write one file per process and let
`qf collect` merge them.

Metadata still originates in the worker, and rides `TestReport.user_properties`,
which pytest serialises with the report. `PYTEST_XDIST_WORKER` is readable ONLY in
the worker (measured: it is unset on every controller-side report), so the shard
index is captured there and travels the same way.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from .case_builder import build_case
from .config import ReporterConfig, resolve_config
from .constants import MAX_CASES_PER_SUITE, MAX_SUITES_PER_LAUNCH, USER_PROPERTY_KEY
from .log import info, warn
from .replay import replay
from .runtime import _bind, _unbind
from .wire import Case, Collect, Metadata, Suite

__version__ = "0.1.0"


def pytest_addoption(parser: Any) -> None:
    parser.addini("qualflare_output_dir", "Directory for Qualflare report files", default="")
    parser.addini("qualflare_environment", "Qualflare environment name", default="")
    parser.addini("qualflare_language", "BCP-47 language tag", default="")
    parser.addini("qualflare_framework", "Framework name reported to Qualflare", default="")
    parser.addini("qualflare_platform", "Platform: api, web, desktop, android, ios", default="")
    parser.addini("qualflare_milestone", "Milestone id", default="")
    parser.addini("qualflare_branch", "Override the detected branch", default="")
    parser.addini("qualflare_enabled", "Set false to disable the reporter", default="")


class QualflarePlugin:
    def __init__(self, config: Any) -> None:
        self.config: ReporterConfig = resolve_config(config)
        self._rootdir = Path(str(config.rootdir))
        # Keyed by nodeid: report arrival order is interleaved under -n, so
        # nothing here may depend on sequence.
        self._phases: dict[str, dict[str, dict[str, Any]]] = {}
        self._reruns: dict[str, list[dict[str, Any]]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._files: dict[str, str] = {}

    # -- worker side --------------------------------------------------------

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any) -> Any:
        outcome = yield
        report = outcome.get_result()
        bucket = getattr(item, "_qualflare_bucket", None)
        if bucket is None:
            return
        if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
            # execution_count is set only by pytest-rerunfailures, and only on the
            # tests it manages -- absent everywhere else.
            bucket["execution_count"] = getattr(item, "execution_count", None)
            payload = dict(bucket)
            payload["messages"] = list(bucket.get("messages") or [])
            report.user_properties.append((USER_PROPERTY_KEY, payload))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: Any, nextitem: Any) -> Any:
        bucket: dict[str, Any] = {
            "messages": [],
            "class_name": _class_name(item),
            "tags": _marker_tags(item),
            # Readable only here; the controller sees it unset.
            "shard_index": _shard_index(),
        }
        item._qualflare_bucket = bucket
        _bind(bucket)
        try:
            yield
        finally:
            _unbind()

    # -- controller side ----------------------------------------------------

    def pytest_runtest_logreport(self, report: Any) -> None:
        nodeid = report.nodeid
        meta = _extract_meta(report)
        if meta:
            existing = self._meta.setdefault(nodeid, {})
            # A retried test reports several times; the LAST attempt's metadata
            # wins, matching the final-attempt-wins rule the siblings document.
            existing.update(meta)

        entry = {
            "outcome": report.outcome,
            "longrepr": report.longrepr,
            "duration_ns": int(getattr(report, "duration", 0.0) * 1_000_000_000),
        }

        if report.outcome == "rerun":
            self._reruns.setdefault(nodeid, []).append(
                {**entry, "execution_count": (meta or {}).get("execution_count")}
            )
            return

        self._phases.setdefault(nodeid, {})[report.when] = entry
        if report.fspath:
            self._files[nodeid] = str(report.fspath)

    def pytest_sessionfinish(self, session: Any, exitstatus: Any) -> None:
        # A worker must not write: the controller already saw every result, so a
        # per-worker file would double-count the whole run.
        if hasattr(session.config, "workeroutput"):
            return
        if not self.config.enabled:
            return
        self._write_report()

    # -- report -------------------------------------------------------------

    def _write_report(self) -> None:
        cases_by_file: dict[str, list[Case]] = {}
        for nodeid, phases in self._phases.items():
            raw_file = self._files.get(nodeid) or nodeid.split("::", 1)[0]
            rel = _relativize(raw_file, self._rootdir)
            case = build_case(
                nodeid=nodeid,
                file_path=rel,
                phases=phases,
                reruns=self._reruns.get(nodeid, []),
                meta=self._meta.get(nodeid, {}),
                replay=replay,
            )
            if case is not None:
                cases_by_file.setdefault(rel, []).append(case)

        suites = [
            Suite(
                name=path,
                duration=sum(c.duration for c in cases),
                cases=cases[:MAX_CASES_PER_SUITE],
            )
            for path, cases in sorted(cases_by_file.items())
        ][:MAX_SUITES_PER_LAUNCH]

        if not suites:
            info("no test results were captured this run — skipping file write.")
            return

        collect = Collect(
            framework=self.config.framework,
            platform=self.config.platform_name,
            os=self.config.os_name,
            browser=self.config.browser,
            environment=self.config.environment,
            language=self.config.language,
            metadata=Metadata(
                version=__version__,
                timestamp=datetime.now(timezone.utc).isoformat(),
                cli_name="qualflare-pytest",
                run_id=self.config.run_id,
            ),
            suites=suites,
            branch=self.config.branch,
            commit=self.config.commit,
            milestone=self.config.milestone,
        )

        try:
            out_dir = Path(self.config.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            target = out_dir / f"qualflare-pytest-{os.getpid()}-{uuid.uuid4()}.json"
            target.write_text(json.dumps(collect.to_wire()), encoding="utf-8")
            info(f"wrote {sum(len(s.cases) for s in suites)} case(s) to {target}")
        except OSError as err:
            warn(f"could not write the report: {err}")


# -- helpers ---------------------------------------------------------------


def _extract_meta(report: Any) -> Optional[dict[str, Any]]:
    for key, value in getattr(report, "user_properties", []):
        if key == USER_PROPERTY_KEY and isinstance(value, dict):
            return value
    return None


def _class_name(item: Any) -> Optional[str]:
    cls = getattr(item, "cls", None)
    return cls.__name__ if cls is not None else None


def _marker_tags(item: Any) -> list[str]:
    """Every marker becomes a tag, so suites already using markers for selection
    get metadata with no code change.

    pytest's own control markers are excluded: they describe how the test runs,
    not what it covers, and would be noise on every case.
    """
    skip = {"parametrize", "usefixtures", "filterwarnings", "skip", "skipif", "xfail", "flaky"}
    try:
        return [m.name for m in item.iter_markers() if m.name not in skip]
    except Exception:
        return []


def _shard_index() -> Optional[int]:
    """The xdist worker index, read where it is actually available.

    `PYTEST_XDIST_WORKER` is "gw0", "gw1", ... in a worker and unset on the
    controller, so this only returns a value from inside a worker -- which is why
    it is captured during the test protocol and shipped with the metadata.
    """
    raw = os.environ.get("PYTEST_XDIST_WORKER")
    if not raw or not raw.startswith("gw"):
        return None
    try:
        return int(raw[2:])
    except ValueError:
        return None


def _relativize(path: str, rootdir: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(rootdir.resolve()))
    except (ValueError, OSError):
        return str(path)


def pytest_configure(config: Any) -> None:
    config.pluginmanager.register(QualflarePlugin(config), "qualflare-pytest-plugin")
