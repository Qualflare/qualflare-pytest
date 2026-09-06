# Configuration

Options go in any file pytest reads — `pytest.ini`, `pyproject.toml`, `setup.cfg`
or `tox.ini`:

```ini
[pytest]
qualflare_environment = staging
qualflare_output_dir = qualflare-results
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
qualflare_environment = "staging"
```

**Precedence, highest first:** the ini option → `QUALFLARE_*` in the environment →
auto-detection (CI variables, then git) → a hardcoded default.

There is **no token option**. This plugin makes no network calls, so it holds no
credential — `qf login` does.

| Option | Environment variable | Default | Meaning |
|---|---|---|---|
| `qualflare_output_dir` | `QUALFLARE_OUTPUT_DIR` | `qualflare-results` | Directory the report is written to. Point every shard at the same one and collect once. |
| `qualflare_environment` | `QUALFLARE_ENVIRONMENT` | `development` | Must already exist on the project. An unknown value is rejected with a 404 and the whole launch is lost — it is matched by uid, not by display name. |
| `qualflare_language` | `QUALFLARE_LANGUAGE` | `en-US` | BCP-47 tag. |
| `qualflare_framework` | — | `pytest` | Reported framework name; also the suite category, which drives the tool logo in the UI. |
| `qualflare_platform` | `QUALFLARE_PLATFORM` | `api` | One of `api`, `web`, `desktop`, `android`, `ios`. |
| `qualflare_milestone` | `QUALFLARE_MILESTONE` | none | Milestone id. Non-numeric values are ignored rather than rejected. |
| `qualflare_branch` | `QUALFLARE_BRANCH` | detected | Overrides CI/git detection. |
| `qualflare_enabled` | `QUALFLARE_ENABLED` | `true` | Set false and no report is written at all. |
| — | `QUALFLARE_COMMIT` | detected | Overrides the detected commit. |
| — | `QUALFLARE_RUN_ID` | detected | Groups the report files of one launch. Derived from the CI build so shards agree without coordinating; random per run locally. |

## What is detected automatically

**CI**: GitHub Actions, GitLab CI, CircleCI and Jenkins are recognised, and each
supplies the provider name, build number, run URL, PR number, branch and commit.
Only providers whose variables are unambiguous are matched — a wrong branch name
is worse than no branch name, because history is grouped by it.

On GitHub Actions the branch comes from `GITHUB_HEAD_REF` on pull requests, not
`GITHUB_REF_NAME`, because the latter is the merge ref on a PR and not a branch
anyone recognises.

**git**: used only when CI variables are absent. A detached HEAD reports no branch
rather than the literal string `HEAD`.

**Shard index**: taken from `PYTEST_XDIST_WORKER` inside each xdist worker, so a
`-n auto` run is attributed per worker with no configuration.
