"""CI provider detection.

Only providers whose variables are unambiguous are matched. A wrong branch name
is worse than no branch name, because the server groups history by it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CIInfo:
    provider: str | None = None
    build_number: str | None = None
    run_url: str | None = None
    pr_number: int | None = None
    branch: str | None = None
    commit: str | None = None
    run_id: str | None = None


def _int_or_none(raw: str | None) -> int | None:
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def detect_ci() -> CIInfo:
    env = os.environ

    if env.get("GITHUB_ACTIONS") == "true":
        repo = env.get("GITHUB_REPOSITORY", "")
        run = env.get("GITHUB_RUN_ID", "")
        # GITHUB_HEAD_REF is set only on pull_request events and holds the SOURCE
        # branch; GITHUB_REF_NAME on a PR is the merge ref, which is not a branch
        # anyone recognises.
        branch = env.get("GITHUB_HEAD_REF") or env.get("GITHUB_REF_NAME")
        pr = None
        ref = env.get("GITHUB_REF", "")
        if ref.startswith("refs/pull/"):
            pr = _int_or_none(ref.split("/")[2] if len(ref.split("/")) > 2 else None)
        return CIInfo(
            provider="github",
            build_number=env.get("GITHUB_RUN_NUMBER"),
            run_url=f"https://github.com/{repo}/actions/runs/{run}" if repo and run else None,
            pr_number=pr,
            branch=branch,
            commit=env.get("GITHUB_SHA"),
            # Attempt is included so a re-run is its own launch rather than
            # merging into the previous one.
            run_id=f"gh-{run}-{env.get('GITHUB_RUN_ATTEMPT', '1')}" if run else None,
        )

    if env.get("GITLAB_CI") == "true":
        return CIInfo(
            provider="gitlab",
            build_number=env.get("CI_PIPELINE_IID"),
            run_url=env.get("CI_PIPELINE_URL"),
            pr_number=_int_or_none(env.get("CI_MERGE_REQUEST_IID")),
            branch=env.get("CI_COMMIT_REF_NAME"),
            commit=env.get("CI_COMMIT_SHA"),
            run_id=f"gl-{env['CI_PIPELINE_ID']}" if env.get("CI_PIPELINE_ID") else None,
        )

    if env.get("CIRCLECI") == "true":
        return CIInfo(
            provider="circleci",
            build_number=env.get("CIRCLE_BUILD_NUM"),
            run_url=env.get("CIRCLE_BUILD_URL"),
            branch=env.get("CIRCLE_BRANCH"),
            commit=env.get("CIRCLE_SHA1"),
            run_id=f"circle-{env['CIRCLE_WORKFLOW_ID']}" if env.get("CIRCLE_WORKFLOW_ID") else None,
        )

    if env.get("JENKINS_URL"):
        return CIInfo(
            provider="jenkins",
            build_number=env.get("BUILD_NUMBER"),
            run_url=env.get("BUILD_URL"),
            branch=env.get("GIT_BRANCH"),
            commit=env.get("GIT_COMMIT"),
            run_id=f"jenkins-{env['BUILD_TAG']}" if env.get("BUILD_TAG") else None,
        )

    return CIInfo()
