"""Git fallback for branch and commit, used only when CI variables are absent.

Two short subprocesses, each guarded: a reporter must never be the reason a test
run fails, and a shallow or detached checkout is normal in CI rather than an
error worth surfacing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class GitInfo:
    branch: str | None = None
    commit: str | None = None


def _run(args: list[str]) -> str | None:
    try:
        out = subprocess.run(
            args, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    value = out.stdout.strip()
    return value or None


def detect_git() -> GitInfo:
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    # A detached HEAD reports the literal "HEAD", which is not a branch name.
    if branch == "HEAD":
        branch = None
    return GitInfo(branch=branch, commit=_run(["git", "rev-parse", "HEAD"]))
