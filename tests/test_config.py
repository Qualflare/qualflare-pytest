"""Configuration precedence, and the detection it falls back to.

Documented order, highest first: pytest ini option -> `QUALFLARE_*` env ->
auto-detection (CI/git) -> hardcoded default. The same order the six JavaScript
reporters document, so one mental model covers every package -- which only holds
if it is actually true here.

CI variables are cleared for every test in this module. Otherwise the suite
passes locally and fails on GitHub Actions, where `GITHUB_REF_NAME` is set and
quietly wins over the default these assert.
"""

from __future__ import annotations

import pytest

from qualflare_pytest.config import DEFAULT_OUTPUT_DIR, resolve_config
from qualflare_pytest.git_detect import GitInfo, detect_git


class FakeIni:
    """Stands in for pytest's Config: `getini` raises for names it does not know,
    which is exactly what the real one does for an unregistered option."""

    def __init__(self, values: dict | None = None):
        self._values = values or {}

    def getini(self, name):
        if name not in self._values:
            raise ValueError(name)
        return self._values[name]


CI_VARS = [
    "QUALFLARE_OUTPUT_DIR",
    "QUALFLARE_ENVIRONMENT",
    "QUALFLARE_LANGUAGE",
    "QUALFLARE_PLATFORM",
    "QUALFLARE_MILESTONE",
    "QUALFLARE_BRANCH",
    "QUALFLARE_COMMIT",
    "QUALFLARE_RUN_ID",
    "QUALFLARE_ENABLED",
    "GITHUB_ACTIONS",
    "GITHUB_REF_NAME",
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_NUMBER",
    "GITHUB_SERVER_URL",
    "GITHUB_REPOSITORY",
    "GITHUB_REF",
    "GITLAB_CI",
    "CI_COMMIT_REF_NAME",
    "CI_COMMIT_SHA",
    "CI_PIPELINE_ID",
    "CIRCLECI",
    "CIRCLE_BRANCH",
    "CIRCLE_SHA1",
    "CIRCLE_BUILD_NUM",
    "JENKINS_URL",
    "GIT_BRANCH",
    "GIT_COMMIT",
    "BUILD_NUMBER",
    "BUILD_URL",
    "CI",
]


@pytest.fixture(autouse=True)
def _no_ambient_ci(monkeypatch):
    for name in CI_VARS:
        monkeypatch.delenv(name, raising=False)
    # git detection shells out; pin it so these assert configuration rather than
    # whatever branch this repo happens to be on. Patched on `git_detect`, not on
    # `config`: resolve_config imports the name inside the function body, so it
    # resolves against the defining module at call time.
    monkeypatch.setattr("qualflare_pytest.git_detect.detect_git", lambda: GitInfo())


class TestDefaults:
    def test_the_documented_defaults_apply_with_nothing_configured(self):
        config = resolve_config(FakeIni())
        assert config.output_dir == DEFAULT_OUTPUT_DIR
        assert config.environment == "development"
        assert config.language == "en-US"
        assert config.framework == "pytest"
        assert config.platform_name == "api"
        assert config.enabled is True

    def test_branch_and_commit_stay_none_when_nothing_reports_them(self):
        # The wire contract wants an explicit null, not a guess.
        config = resolve_config(FakeIni())
        assert config.branch is None
        assert config.commit is None

    def test_a_run_id_is_always_produced(self):
        # Shards group on it, so it can never be empty.
        assert resolve_config(FakeIni()).run_id


class TestPrecedence:
    def test_env_beats_the_default(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_OUTPUT_DIR", "from-env")
        assert resolve_config(FakeIni()).output_dir == "from-env"

    def test_ini_beats_env(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_OUTPUT_DIR", "from-env")
        assert resolve_config(FakeIni({"qualflare_output_dir": "from-ini"})).output_dir == (
            "from-ini"
        )

    def test_the_same_order_holds_for_environment(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_ENVIRONMENT", "from-env")
        assert resolve_config(FakeIni()).environment == "from-env"
        assert resolve_config(FakeIni({"qualflare_environment": "staging"})).environment == (
            "staging"
        )

    def test_an_empty_ini_value_falls_through_rather_than_winning(self):
        # getini returns "" for a declared-but-unset option; treating that as a
        # value would override the env with nothing.
        assert resolve_config(FakeIni({"qualflare_output_dir": ""})).output_dir == (
            DEFAULT_OUTPUT_DIR
        )

    def test_an_empty_env_value_falls_through_too(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_ENVIRONMENT", "")
        assert resolve_config(FakeIni()).environment == "development"

    def test_branch_prefers_explicit_configuration_over_detection(self, monkeypatch):
        monkeypatch.setattr(
            "qualflare_pytest.git_detect.detect_git", lambda: GitInfo(branch="from-git")
        )
        monkeypatch.setenv("QUALFLARE_BRANCH", "from-env")
        assert resolve_config(FakeIni()).branch == "from-env"
        assert resolve_config(FakeIni({"qualflare_branch": "from-ini"})).branch == "from-ini"

    def test_git_supplies_branch_when_nothing_else_does(self, monkeypatch):
        monkeypatch.setattr(
            "qualflare_pytest.git_detect.detect_git",
            lambda: GitInfo(branch="feature/x", commit="abc123"),
        )
        config = resolve_config(FakeIni())
        assert config.branch == "feature/x"
        assert config.commit == "abc123"


class TestMilestone:
    def test_a_numeric_milestone_is_parsed(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_MILESTONE", "7")
        assert resolve_config(FakeIni()).milestone == 7

    def test_a_non_numeric_milestone_degrades_to_none(self, monkeypatch):
        # Rather than raising: a typo in an ini file must not fail the run.
        monkeypatch.setenv("QUALFLARE_MILESTONE", "next-release")
        assert resolve_config(FakeIni()).milestone is None

    def test_ini_beats_env_for_the_milestone_too(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_MILESTONE", "1")
        assert resolve_config(FakeIni({"qualflare_milestone": "9"})).milestone == 9


class TestEnabled:
    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "FALSE", "Off"])
    def test_falsey_spellings_disable_the_plugin(self, monkeypatch, raw):
        monkeypatch.setenv("QUALFLARE_ENABLED", raw)
        assert resolve_config(FakeIni()).enabled is False

    @pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE"])
    def test_truthy_spellings_enable_it(self, monkeypatch, raw):
        monkeypatch.setenv("QUALFLARE_ENABLED", raw)
        assert resolve_config(FakeIni()).enabled is True

    def test_an_unrecognised_value_disables_rather_than_crashing(self, monkeypatch):
        monkeypatch.setenv("QUALFLARE_ENABLED", "maybe")
        assert resolve_config(FakeIni()).enabled is False


class TestGitDetect:
    def test_a_detached_head_is_not_reported_as_a_branch(self, monkeypatch):
        # `git rev-parse --abbrev-ref HEAD` returns the literal "HEAD" when
        # detached, which is not a branch name -- and CI checkouts are routinely
        # detached, so this is the common case rather than an edge one.
        monkeypatch.setattr(
            "qualflare_pytest.git_detect._run",
            lambda args: "HEAD" if "--abbrev-ref" in args else "abc123",
        )
        info = detect_git()
        assert info.branch is None
        assert info.commit == "abc123"

    def test_a_normal_checkout_reports_both(self, monkeypatch):
        monkeypatch.setattr(
            "qualflare_pytest.git_detect._run",
            lambda args: "main" if "--abbrev-ref" in args else "abc123",
        )
        assert detect_git() == GitInfo(branch="main", commit="abc123")

    def test_no_git_available_degrades_to_nothing(self, monkeypatch):
        # A reporter must never be the reason a test run fails.
        monkeypatch.setattr("qualflare_pytest.git_detect._run", lambda args: None)
        assert detect_git() == GitInfo(branch=None, commit=None)
