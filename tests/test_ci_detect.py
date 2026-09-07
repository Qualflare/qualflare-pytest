"""CI provider detection.

Only providers whose variables are unambiguous are matched, because a wrong
branch name is worse than no branch name -- the server groups history by it.

The whole environment is cleared before each case. Detection reads `os.environ`
directly, so without that these pass locally and behave differently on Actions,
where the real GITHUB_* variables are already set.
"""

from __future__ import annotations

import pytest

from qualflare_pytest.ci_detect import CIInfo, detect_ci

TOUCHED = [
    "GITHUB_ACTIONS",
    "GITHUB_REPOSITORY",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_NUMBER",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_REF",
    "GITHUB_REF_NAME",
    "GITHUB_HEAD_REF",
    "GITHUB_SHA",
    "GITLAB_CI",
    "CI_PIPELINE_IID",
    "CI_PIPELINE_ID",
    "CI_PIPELINE_URL",
    "CI_MERGE_REQUEST_IID",
    "CI_COMMIT_REF_NAME",
    "CI_COMMIT_SHA",
    "CIRCLECI",
    "CIRCLE_BUILD_NUM",
    "CIRCLE_BUILD_URL",
    "CIRCLE_BRANCH",
    "CIRCLE_SHA1",
    "CIRCLE_WORKFLOW_ID",
    "JENKINS_URL",
    "BUILD_NUMBER",
    "BUILD_URL",
    "BUILD_TAG",
    "GIT_BRANCH",
    "GIT_COMMIT",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in TOUCHED:
        monkeypatch.delenv(name, raising=False)


def test_nothing_detected_outside_ci():
    assert detect_ci() == CIInfo()


class TestGitHubActions:
    @pytest.fixture(autouse=True)
    def _actions(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_REPOSITORY", "Qualflare/qualflare-pytest")
        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        monkeypatch.setenv("GITHUB_RUN_NUMBER", "42")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        monkeypatch.setenv("GITHUB_REF_NAME", "main")

    def test_a_push_build_is_described_fully(self):
        info = detect_ci()
        assert info.provider == "github"
        assert info.build_number == "42"
        assert info.run_url == "https://github.com/Qualflare/qualflare-pytest/actions/runs/12345"
        assert info.branch == "main"
        assert info.commit == "abc123"
        assert info.pr_number is None

    def test_a_pull_request_reports_the_source_branch_not_the_merge_ref(self, monkeypatch):
        # GITHUB_REF_NAME on a PR is "7/merge", which is not a branch anyone
        # recognises; GITHUB_HEAD_REF holds the branch the author pushed.
        monkeypatch.setenv("GITHUB_REF_NAME", "7/merge")
        monkeypatch.setenv("GITHUB_HEAD_REF", "feature/checkout")
        monkeypatch.setenv("GITHUB_REF", "refs/pull/7/merge")
        info = detect_ci()
        assert info.branch == "feature/checkout"
        assert info.pr_number == 7

    def test_a_non_pull_ref_yields_no_pr_number(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        assert detect_ci().pr_number is None

    def test_a_malformed_pull_ref_degrades_rather_than_raising(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REF", "refs/pull/not-a-number/merge")
        assert detect_ci().pr_number is None

    def test_the_run_id_includes_the_attempt_so_a_rerun_is_its_own_launch(self, monkeypatch):
        assert detect_ci().run_id == "gh-12345-1"
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
        assert detect_ci().run_id == "gh-12345-3"

    def test_no_run_url_is_invented_from_half_the_inputs(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY")
        assert detect_ci().run_url is None

    def test_actions_set_to_anything_but_true_is_not_matched(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "false")
        assert detect_ci().provider is None


class TestGitLab:
    def test_a_pipeline_is_described(self, monkeypatch):
        monkeypatch.setenv("GITLAB_CI", "true")
        monkeypatch.setenv("CI_PIPELINE_IID", "17")
        monkeypatch.setenv("CI_PIPELINE_ID", "9001")
        monkeypatch.setenv("CI_PIPELINE_URL", "https://gitlab.com/x/-/pipelines/9001")
        monkeypatch.setenv("CI_COMMIT_REF_NAME", "main")
        monkeypatch.setenv("CI_COMMIT_SHA", "def456")
        monkeypatch.setenv("CI_MERGE_REQUEST_IID", "5")
        info = detect_ci()
        assert info.provider == "gitlab"
        assert (info.build_number, info.branch, info.commit) == ("17", "main", "def456")
        assert info.pr_number == 5
        assert info.run_id == "gl-9001"

    def test_a_pipeline_without_an_id_reports_no_run_id(self, monkeypatch):
        monkeypatch.setenv("GITLAB_CI", "true")
        assert detect_ci().run_id is None


class TestCircleCI:
    def test_a_build_is_described(self, monkeypatch):
        monkeypatch.setenv("CIRCLECI", "true")
        monkeypatch.setenv("CIRCLE_BUILD_NUM", "88")
        monkeypatch.setenv("CIRCLE_BUILD_URL", "https://circleci.com/gh/x/88")
        monkeypatch.setenv("CIRCLE_BRANCH", "main")
        monkeypatch.setenv("CIRCLE_SHA1", "aaa111")
        monkeypatch.setenv("CIRCLE_WORKFLOW_ID", "wf-1")
        info = detect_ci()
        assert info.provider == "circleci"
        assert (info.build_number, info.branch, info.commit) == ("88", "main", "aaa111")
        assert info.run_id == "circle-wf-1"


class TestJenkins:
    def test_a_build_is_described(self, monkeypatch):
        # Jenkins is matched on the presence of JENKINS_URL rather than a literal
        # "true", because it carries a URL.
        monkeypatch.setenv("JENKINS_URL", "https://ci.example.com/")
        monkeypatch.setenv("BUILD_NUMBER", "31")
        monkeypatch.setenv("BUILD_URL", "https://ci.example.com/job/x/31/")
        monkeypatch.setenv("BUILD_TAG", "jenkins-x-31")
        monkeypatch.setenv("GIT_BRANCH", "origin/main")
        monkeypatch.setenv("GIT_COMMIT", "bbb222")
        info = detect_ci()
        assert info.provider == "jenkins"
        assert (info.build_number, info.branch, info.commit) == ("31", "origin/main", "bbb222")
        assert info.run_id == "jenkins-jenkins-x-31"


class TestPrecedenceBetweenProviders:
    def test_github_wins_when_more_than_one_looks_present(self, monkeypatch):
        # Jenkins agents running Actions-like jobs, and self-hosted runners, can
        # set both. Matching the first is deterministic; matching neither loses
        # the data.
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("JENKINS_URL", "https://ci.example.com/")
        assert detect_ci().provider == "github"
