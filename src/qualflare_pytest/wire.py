"""The Qualflare Collect wire contract.

A faithful port of the shape the six TypeScript reporters emit (see
`qualflare-mocha/src/shared/types.ts`), because `qualflare-cli` identifies this
format by the TRIPLE `framework` + `metadata` + `suites`. Drop any one of those
and `qf collect` falls back to filename detection and misroutes the file.

Three rules are easy to get wrong writing this fresh, and all three are load-bearing:

  * durations are INTEGER NANOSECONDS with no unit marker on the wire;
  * `branch`, `commit` and `milestone` must be PRESENT as value-or-null, never
    omitted -- the server distinguishes "not reported" from "absent";
  * `attempts` carries EVERY attempt including the final one, 1-based, and is
    omitted entirely below two, because fewer than two persists nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drops None-valued keys, so optional fields are absent rather than null.

    The value-or-null fields are handled by their owners, which pass an explicit
    None through `_keep_null` instead of relying on this.
    """
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Parameter:
    name: str
    value: str | None = None
    masked: bool = False

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name}
        if self.value is not None:
            out["value"] = self.value
        if self.masked:
            out["masked"] = True
        return out


@dataclass
class Step:
    name: str
    status: str
    duration: int  # nanoseconds
    keyword: str | None = None
    error: str | None = None
    location: str | None = None
    parent_index: int | None = None
    parameters: list[Parameter] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        out = _clean({
            "name": self.name,
            "status": self.status,
            "duration": self.duration,
            "keyword": self.keyword,
            "error": self.error,
            "location": self.location,
            "parentIndex": self.parent_index,
        })
        if self.parameters:
            out["parameters"] = [p.to_wire() for p in self.parameters]
        return out


@dataclass
class Attachment:
    name: str
    mime_type: str | None = None
    content: str | None = None          # base64
    local_image_path: str | None = None  # relative to outputDir
    file_size: int | None = None
    step_index: int | None = None

    def to_wire(self) -> dict[str, Any]:
        return _clean({
            "name": self.name,
            "mimeType": self.mime_type,
            "content": self.content,
            "localImagePath": self.local_image_path,
            "fileSize": self.file_size,
            "stepIndex": self.step_index,
        })


@dataclass
class Attempt:
    attempt: int  # 1-based; the server drops anything lower
    status: str
    duration: int | None = None  # nanoseconds
    message: str | None = None
    trace: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return _clean({
            "attempt": self.attempt,
            "status": self.status,
            "duration": self.duration,
            "message": self.message,
            "trace": self.trace,
        })


@dataclass
class Label:
    name: str
    value: str

    def to_wire(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


@dataclass
class Link:
    url: str
    type: str = "custom"  # issue | tms | custom
    name: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return _clean({"url": self.url, "type": self.type, "name": self.name})


@dataclass
class Case:
    id: str
    name: str
    status: str
    duration: int  # nanoseconds
    class_name: str | None = None
    error: str | None = None
    description: str | None = None
    priority: str | None = None
    retry_count: int | None = None
    is_flaky: bool | None = None
    shard_index: int | None = None
    started_at: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        out = _clean({
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "duration": self.duration,
            "className": self.class_name,
            "error": self.error,
            "description": self.description,
            "priority": self.priority,
            "retryCount": self.retry_count,
            "isFlaky": self.is_flaky,
            "shardIndex": self.shard_index,
            "startedAt": self.started_at,
        })
        if self.properties:
            out["properties"] = self.properties
        if self.tags:
            out["tags"] = self.tags
        if self.labels:
            out["labels"] = [x.to_wire() for x in self.labels]
        if self.links:
            out["links"] = [x.to_wire() for x in self.links]
        if self.steps:
            out["steps"] = [x.to_wire() for x in self.steps]
        if self.attachments:
            out["attachments"] = [x.to_wire() for x in self.attachments]
        # Below two attempts the server persists nothing, so an array of one is
        # bytes against the body limit for a row that is discarded.
        if len(self.attempts) >= 2:
            out["attempts"] = [x.to_wire() for x in self.attempts]
        return out


@dataclass
class Suite:
    name: str
    duration: int  # nanoseconds
    cases: list[Case] = field(default_factory=list)
    category: str = "pytest"
    properties: dict[str, str] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "duration": self.duration,
            "category": self.category,
            "cases": [c.to_wire() for c in self.cases],
        }
        if self.properties:
            out["properties"] = self.properties
        return out


@dataclass
class Metadata:
    version: str
    timestamp: str
    cli_name: str
    run_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return _clean({
            "version": self.version,
            "timestamp": self.timestamp,
            "cliName": self.cli_name,
            "runId": self.run_id,
        })


@dataclass
class Collect:
    framework: str
    platform: str
    os: str
    browser: str
    environment: str
    language: str
    metadata: Metadata
    suites: list[Suite] = field(default_factory=list)
    # Value-or-null, ALWAYS present. The server treats an absent key differently
    # from an explicit null, so these are never dropped by `_clean`.
    branch: str | None = None
    commit: str | None = None
    milestone: int | None = None
    properties: dict[str, str] = field(default_factory=dict)
    ci_provider: str | None = None
    ci_build_number: str | None = None
    ci_run_url: str | None = None
    ci_pr_number: int | None = None

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "framework": self.framework,
            "platform": self.platform,
            "os": self.os,
            "browser": self.browser,
            "environment": self.environment,
            "language": self.language,
            "metadata": self.metadata.to_wire(),
            "suites": [s.to_wire() for s in self.suites],
            # Explicit null, not omitted -- see the class docstring.
            "branch": self.branch,
            "commit": self.commit,
            "milestone": self.milestone,
        }
        out.update(_clean({
            "ciProvider": self.ci_provider,
            "ciBuildNumber": self.ci_build_number,
            "ciRunUrl": self.ci_run_url,
            "ciPrNumber": self.ci_pr_number,
        }))
        if self.properties:
            out["properties"] = self.properties
        return out
