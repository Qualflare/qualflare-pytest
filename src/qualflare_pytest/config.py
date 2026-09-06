"""Resolved reporter configuration.

Precedence, highest first: the pytest ini option -> `QUALFLARE_*` env ->
auto-detection (CI/git) -> a hardcoded default. That is the same order the six
JavaScript reporters document, so one mental model covers every package.

There is deliberately NO token option. This plugin makes no network calls, so it
has no credential; `qf login` holds it instead.
"""

from __future__ import annotations

import os
import platform
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_OUTPUT_DIR = "qualflare-results"


@dataclass
class ReporterConfig:
    output_dir: str = DEFAULT_OUTPUT_DIR
    environment: str = "development"
    language: str = "en-US"
    framework: str = "pytest"
    platform_name: str = "api"
    os_name: str = field(default_factory=lambda: platform.system().lower())
    browser: str = ""
    milestone: int | None = None
    branch: str | None = None
    commit: str | None = None
    run_id: str = ""
    enabled: bool = True
    debug: bool = False
    properties: dict[str, str] = field(default_factory=dict)


def _ini(config: Any, name: str) -> str | None:
    try:
        value = config.getini(name)
    except (ValueError, KeyError):
        return None
    if value in (None, "", []):
        return None
    return str(value)


def _env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_config(pytest_config: Any) -> ReporterConfig:
    from .ci_detect import detect_ci
    from .git_detect import detect_git

    ci = detect_ci()
    git = detect_git()

    milestone_raw = _ini(pytest_config, "qualflare_milestone") or _env("QUALFLARE_MILESTONE")
    milestone: int | None = None
    if milestone_raw:
        try:
            milestone = int(milestone_raw)
        except ValueError:
            milestone = None

    return ReporterConfig(
        output_dir=(
            _ini(pytest_config, "qualflare_output_dir")
            or _env("QUALFLARE_OUTPUT_DIR")
            or DEFAULT_OUTPUT_DIR
        ),
        environment=(
            _ini(pytest_config, "qualflare_environment")
            or _env("QUALFLARE_ENVIRONMENT")
            or "development"
        ),
        language=(
            _ini(pytest_config, "qualflare_language") or _env("QUALFLARE_LANGUAGE") or "en-US"
        ),
        framework=_ini(pytest_config, "qualflare_framework") or "pytest",
        platform_name=(
            _ini(pytest_config, "qualflare_platform") or _env("QUALFLARE_PLATFORM") or "api"
        ),
        os_name=platform.system().lower(),
        milestone=milestone,
        # branch/commit stay None when nothing reports them: the wire contract
        # wants an explicit null, not a guess.
        branch=(
            _ini(pytest_config, "qualflare_branch")
            or _env("QUALFLARE_BRANCH")
            or ci.branch
            or git.branch
        ),
        commit=_env("QUALFLARE_COMMIT") or ci.commit or git.commit,
        # One run id per launch, shared by every shard so `qf collect` can group
        # the report files it finds. In CI it is derived from the build so all
        # shards agree without coordinating; locally it is random per run.
        run_id=_env("QUALFLARE_RUN_ID") or ci.run_id or str(uuid.uuid4()),
        enabled=_as_bool(
            _ini(pytest_config, "qualflare_enabled") or _env("QUALFLARE_ENABLED"), True
        ),
        debug=_as_bool(_env("QUALFLARE_DEBUG", "QF_DEBUG"), False),
    )
