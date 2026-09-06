# Known limitations

Things pytest does that this plugin does not capture, or captures only partly.
Each entry says what you lose and what to do about it.

## `xfail` and `xpass` are flattened

pytest distinguishes four outcomes this plugin collapses to two:

| pytest | reported as |
|---|---|
| `xfail` (expected failure, and it failed) | `skipped` |
| `xpass` (expected failure, but it passed) | `passed` |

That second row is the one that costs something. Under `xfail(strict=True)` an
unexpected pass is a **failure** in pytest, and here it appears as an ordinary
pass — so a test that pytest is failing your build over looks green in the report.

Nothing marks a case as expected-to-fail either, so an `xfail` is
indistinguishable from a `skip`.

## `record_property` is ignored

pytest's own per-test metadata fixture is not mapped:

```python
def test_thing(record_property):
    record_property("ticket", "QF-123")   # does not reach the report
```

Values recorded that way land in `TestReport.user_properties` alongside this
plugin's own key and are passed over. Use `qualflare.parameter()` or
`qualflare.label()` instead, which do.

## Captured stdout and stderr are not attached

pytest captures output per test and exposes it on the report, and this plugin does
not forward it — a failing case carries its error and traceback, nothing else.
Attach what you need explicitly with `qualflare.attachment()`.

## Launch-level properties cannot be set

There is no equivalent of `record_testsuite_property`. Even if there were, it
would not survive `pytest-xdist` — pytest#7767 — so anything suite-wide has to be
derived on the controller, and today nothing is.

## Values must survive JSON serialisation

Anything passed to `qualflare.parameter()` that is not a string, number, boolean,
list or dict is replaced by its `repr`. That is lossy on purpose. The alternative
is worse than lossy: pytest serialises `user_properties` when a report crosses the
xdist boundary, and an unserialisable value there kills the worker with an internal
error **while pytest still exits 0** — a green build hiding a dead worker.

## Steps are capped at 300 per attempt

Beyond that, steps are dropped and a warning is logged. The server's own limit is
1000; the lower client cap keeps a runaway loop from filling a report before it
gets there.

## Attachments

Inline content over ~2MB encoded is **dropped, not truncated** — half a base64
payload is not a usable file, and an oversized request body is rejected whole,
which loses the entire launch rather than one attachment.

Files attached with `attachment_from_file()` are copied into `outputDir` and
referenced relatively. This needs `qualflare-cli` v0.1.24+; an older CLI ignores
the reference and the server records the attachment from its name alone, as an
undownloadable placeholder.

## pytest-bdd: doc strings and data tables are not recorded

Gherkin steps carry their keyword, name, status and location. A step's
`docstring` or `datatable` is available on the step object and is not captured, so
a data table appears only as the step name it belongs to.

## Metadata from an abandoned retry is discarded

With `pytest-rerunfailures`, each attempt emits its own metadata and only the
final attempt's labels, steps and attachments are kept. `attempts[]` still records
every attempt's status and error, so the retry history is complete — it is only
the metadata of superseded attempts that is dropped.

## Not limitations

- **`pytest -n auto` is fully supported**, and CI asserts that a run produces the
  same report with and without it.
- **No `timeout` status.** pytest has no distinct timed-out outcome — a timeout
  surfaces as an ordinary failure — so the wire contract's `timeout` value is never
  produced.
- **A fixture failure reports as `error`, not `failed`.** The test never ran;
  `failed` would blame it for someone else's fixture.
