# Metadata API

```python
from qualflare_pytest import qualflare
```

Every call is fire-and-forget and fail-open: a metadata problem must never fail
somebody's test run. A call made outside a running test — in a session fixture or
at module scope — is discarded rather than attached to whichever test runs next.

## How it reaches the report

pytest gives a test body no direct line to a reporting plugin, but it does give a
supported channel: `TestReport.user_properties`, which pytest serialises with the
report. Under `pytest-xdist` that carries metadata from the worker to the
controller, where the report is built — so nothing here needs a side channel.

**Values must survive JSON serialisation.** That is a pytest constraint, not ours,
and it is enforced asymmetrically: serially an unserialisable value raises, but
under `-n` it kills the worker with an internal error while pytest still exits 0.
Everything passed to these functions is therefore coerced before it is attached —
containers are walked, and anything else becomes its `repr`.

## Reference

### `qualflare.label(name, value)`

Allure-style name/value metadata. `epic`, `feature`, `story`, `owner` and
`severity` are conventions, not special cases. Max 100 per case.

### `qualflare.link(url, type="custom", name=None)`

`type` is `issue`, `tms` or `custom`. Unknown values are passed through and
rejected server-side rather than silently rewritten. Max 20 per case.

### `qualflare.tag(*tags)`

Free-form tags, max 64 per case, 255 characters each.

**Markers become tags automatically.** `@pytest.mark.smoke` produces the tag
`smoke` with no code change, so a suite already using markers for selection gets
that dimension for free. pytest's own control markers — `parametrize`,
`usefixtures`, `skip`, `skipif`, `xfail`, `filterwarnings`, `flaky` — are excluded:
they describe how a test runs, not what it covers.

### `qualflare.priority(value)`

`low`, `medium`, `high` or `critical`. Anything else is dropped.

### `qualflare.description(text)`

Free text shown on the case.

### `qualflare.parameter(name, value=None, masked=False)`

A case-level parameter, or a step-level one when called inside a `step()` block.

**`masked=True` drops the value at the source**, before anything is serialised, so
the secret never reaches the report file or the server. This matters because the
wire format treats `masked` as a display hint only — the server does not redact —
so masking anywhere later would not actually protect it.

### `qualflare.step(name)`

A context manager:

```python
with qualflare.step("add to cart"):
    qualflare.parameter("sku", "widget")
```

Steps nest, and a parameter emitted inside one belongs to that step rather than to
the case. The test's own exception is always re-raised untouched — only the
bookkeeping is wrapped, so this can never swallow a failure. A failing step is
recorded as failed and the test fails as it otherwise would.

Capped at 300 steps per attempt, with a warning; the server's own limit is 1000.

### `qualflare.attachment(name, content, mime_type=None, encoding="utf8")`

Attaches in-memory content. Pass `encoding="base64"` if it is already encoded.
Oversized content is dropped with a warning rather than truncated — half a base64
payload is not a usable file, and an oversized request body is rejected whole,
which would lose the entire launch rather than one attachment.

### `qualflare.attachment_from_file(name, path, mime_type=None)`

Copies the file into `outputDir` under a collision-proof name and references it
relatively, which is what lets the CLI upload it out of band. Needs
`qualflare-cli` v0.1.24+; an older CLI ignores the reference and the server records
the attachment from its name alone.

## pytest-bdd

When `pytest-bdd` is installed, Gherkin steps are recorded automatically with
their keyword (`Given`/`When`/`Then`) and their `feature:line` location. Nothing
needs enabling, and manual `qualflare.step()` calls compose with them.
