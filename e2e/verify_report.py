#!/usr/bin/env python3
"""Asserts the dogfood report says what the suite declared.

Runs BEFORE the upload. A report that is structurally fine but semantically wrong
would upload happily and be discovered weeks later in the UI -- which is exactly
how `Case.attempts` went missing for three CLI releases in the sibling packages.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MASKED_SECRET = "qf-dogfood-secret-value"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        failures.append(f"{label}{f' — {detail}' if detail else ''}")


output_dir = Path(os.environ.get("QUALFLARE_OUTPUT_DIR", "e2e-results"))
if not output_dir.is_dir():
    print(f"✗ {output_dir} does not exist. Did the suite run?", file=sys.stderr)
    raise SystemExit(1)

reports = sorted(output_dir.glob("*.json"))
if len(reports) != 1:
    # Two would mean an xdist worker wrote its own, which is the double-count the
    # controller-only write exists to prevent.
    print(f"✗ expected exactly one report in {output_dir}, found {len(reports)}", file=sys.stderr)
    raise SystemExit(1)

raw = reports[0].read_text()
report = json.loads(raw)
cases = {c["name"]: c for s in report["suites"] for c in s["cases"]}

check("framework is correct", report.get("framework") == "pytest", str(report.get("framework")))
check("metadata block present", bool(report.get("metadata")))
check("metadata.runId stamped", bool((report.get("metadata") or {}).get("runId")))
# Value-or-null: the server distinguishes these from absent keys.
check(
    "branch/commit/milestone present",
    all(k in report for k in ("branch", "commit", "milestone")),
)
check("six cases reported", len(cases) == 6, f"got {len(cases)}: {sorted(cases)}")

not_passed = [f"{n}={c['status']}" for n, c in cases.items() if c["status"] != "passed"]
check("every case passed", not not_passed, ", ".join(not_passed))

meta = cases.get("test_records_the_author_facing_metadata_api")
check("metadata case present", meta is not None)
if meta:
    check("label recorded", {"name": "team", "value": "platform"} in (meta.get("labels") or []))
    links = meta.get("links") or []
    check("link recorded", any(x.get("name") == "repository" for x in links))
    check("tag recorded", "dogfood" in (meta.get("tags") or []))
    # Markers become tags with no code change; this asserts that path too.
    check("marker became a tag", "smoke" in (meta.get("tags") or []))
    check("priority recorded", meta.get("priority") == "high")
    check("description recorded", bool(meta.get("description")))
    check("parameter recorded", (meta.get("properties") or {}).get("plan") == "enterprise")

steps = cases.get("test_nests_steps")
if steps:
    inner = next((s for s in (steps.get("steps") or []) if s["name"] == "inner"), None)
    check("inner step recorded", inner is not None)
    check("inner step is nested", inner is not None and inner.get("parentIndex") is not None)

# Asserted over the WHOLE payload: redaction happens at the source, so the only
# convincing proof is that the secret appears nowhere at all.
check("masked value never reaches the report", MASKED_SECRET not in raw)

shot_case = cases.get("test_attaches_a_screenshot")
if shot_case:
    attachments = shot_case.get("attachments") or []
    shot = next((a for a in attachments if a.get("mimeType") == "image/png"), None)
    check("screenshot attachment present", shot is not None)
    if shot:
        check("screenshot is not inlined", "content" not in shot)
        path = shot.get("localImagePath")
        check("screenshot has a relative localImagePath", bool(path) and not os.path.isabs(path))
        if path:
            on_disk = output_dir / path
            check("screenshot file exists in outputDir", on_disk.is_file(), str(on_disk))
            if on_disk.is_file():
                check("screenshot really is a PNG", on_disk.read_bytes()[:8] == PNG_MAGIC)
                check("fileSize matches", shot.get("fileSize") == on_disk.stat().st_size)

flaky = cases.get("test_fails_once_then_passes")
if flaky:
    check("flaky case ended green", flaky["status"] == "passed", flaky["status"])
    check("isFlaky set", flaky.get("isFlaky") is True)
    check("retryCount is 1", flaky.get("retryCount") == 1, str(flaky.get("retryCount")))
    attempts = flaky.get("attempts") or []
    check("two attempts recorded", len(attempts) == 2, str(len(attempts)))
    check(
        "attempts are [failed, passed]",
        [a["status"] for a in attempts] == ["failed", "passed"],
        str([a.get("status") for a in attempts]),
    )
    first = attempts[0].get("message") or "" if attempts else ""
    check("first attempt kept its error", "dogfood-intentional-retry" in first)

if failures:
    print(f"\n✗ {len(failures)} assertion(s) failed against {reports[0].name}:\n", file=sys.stderr)
    for f in failures:
        print(f"    - {f}", file=sys.stderr)
    raise SystemExit(1)

print(
    f"✓ {len(cases)} cases verified in {reports[0].name} — "
    "report matches what the suite declared"
)
