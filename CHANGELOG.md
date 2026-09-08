# Changelog

## 0.1.2

Documentation and package metadata — no code change, and nothing to do if you
are already on 0.1.1.

**The quickstart told you to `pip install qualflare-cli`.** That package does not
exist: `qualflare-cli` is a standalone Go binary, distributed through Homebrew,
npm and the release page. Anyone following the README verbatim hit a dead end at
step two. The quickstart now shows the real install and says plainly why pip is
not one of the options.

`Homepage` now points at https://qualflare.com/pytest-test-reporting/ rather than
the repository, and `keywords` matches the rest of the reporter family —
`flaky-tests` and `test-reporter` added, the bare `reporter` dropped.

Also internal: unit coverage for the metadata API, CI detection and the report
builders in isolation, plus a dogfood suite that uploads this package's own
results to Qualflare on every merge.

## 0.1.1

Identical in behaviour to 0.1.0, which never became installable: the upload was
accepted by PyPI but the project was not served from the index, and a consumed
version number cannot be reused. This is that release under a version that works.

## 0.1.0

First release of `qualflare-pytest` — a native pytest plugin for Qualflare.
Withdrawn; see above.

Captures what `--junitxml` cannot: per-attempt retry history with each attempt's
error, flakiness, steps, attachments, and the author-facing metadata API (labels,
links, tags, priority, parameters).

The plugin makes no network calls. It writes a report directory that
`qualflare-cli collect` uploads.

`pytest -n auto` is fully supported and needs no configuration — metadata attached
in a worker travels to the controller on the test report, and CI asserts a run
produces the same report with and without `-n`. The xdist worker index becomes
each case's shard index.

`pytest-xdist`, `pytest-rerunfailures` and `pytest-bdd` are optional. A CI leg
installs none of them and asserts the report is still correct. When `pytest-bdd`
is present, Gherkin steps are recorded with their keyword and `feature:line`
location.

Requires Python 3.9+ and pytest 7.0+, both proven by the CI matrix rather than
asserted.
