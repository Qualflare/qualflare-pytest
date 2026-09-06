# Changelog

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
