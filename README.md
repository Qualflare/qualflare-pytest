# qualflare-pytest

[![PyPI](https://img.shields.io/pypi/v/qualflare-pytest.svg)](https://pypi.org/project/qualflare-pytest/)
[![CI](https://github.com/Qualflare/qualflare-pytest/actions/workflows/ci.yml/badge.svg)](https://github.com/Qualflare/qualflare-pytest/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)

A native pytest plugin for [Qualflare](https://qualflare.com) — captures results
directly from your `pytest` run: status, per-attempt retry history and flakiness,
steps, attachments, and author-facing metadata (labels, links, tags, priority,
custom parameters).

Without it, pytest results reach Qualflare through `--junitxml`, which carries
pass/fail, duration and a class name — no retry history, no attachments, no
metadata.

The plugin makes **no network calls**. It writes a report directory, and
[`qualflare-cli`](https://github.com/Qualflare/qualflare-cli) uploads it.

## Install

```bash
pip install qualflare-pytest
```

Requires Python 3.9+ and pytest 7.0+. It registers itself on install — there is no
`-p` flag to add. `pytest-xdist` and `pytest-rerunfailures` are supported but
optional; the plugin works, and is tested, without either.

## Quickstart

```bash
pytest
pip install qualflare-cli
qf login my-project "$QUALFLARE_TOKEN" --force
qf my-project collect ./qualflare-results
```

Configure it in `pytest.ini`, `pyproject.toml` or `setup.cfg`:

```ini
[pytest]
qualflare_environment = staging
qualflare_output_dir = qualflare-results
```

Every option and environment variable is in
[`docs/CONFIGURATION.md`](./docs/CONFIGURATION.md).

## Parallel runs

`pytest -n auto` is supported and needs no configuration. Metadata attached in a
worker travels to the controller on the test report, and the controller writes one
report for the whole run. The plugin's own CI asserts that `pytest` and
`pytest -n 2` produce the same report.

The xdist worker index is recorded as each case's shard index, so a distributed
run is attributed correctly without the `record_property("shard", …)` workaround
the JUnit path needs.

## Enriching your tests

```python
from qualflare_pytest import qualflare

def test_checks_out():
    qualflare.label("feature", "checkout")
    qualflare.link("https://example.com/issue/42", type="issue", name="QF-42")
    qualflare.tag("smoke")
    qualflare.priority("high")

    with qualflare.step("add to cart"):
        qualflare.parameter("sku", "widget")
        qualflare.parameter("token", os.environ["TOKEN"], masked=True)
```

Markers become tags automatically, so a suite already using `@pytest.mark.smoke`
for selection gets that dimension in Qualflare with no code change. When
`pytest-bdd` is installed, Gherkin steps are recorded with their keyword and
location too.

Full reference in [`docs/METADATA-API.md`](./docs/METADATA-API.md).

## Known limitations

- **`xfail` and `xpass` are flattened** to `skipped` and `passed`. Under
  `xfail(strict=True)` an unexpected pass is a failure in pytest but reads as an
  ordinary pass here.
- **`record_property` is ignored.** Use `qualflare.parameter()` or
  `qualflare.label()`, which do reach the report.
- **Captured stdout/stderr are not attached.** Attach what you need explicitly.

Full details in [`docs/LIMITATIONS.md`](./docs/LIMITATIONS.md).

## License

Apache-2.0 — see [LICENSE](./LICENSE).
