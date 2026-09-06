"""Replays the runtime's message stream onto the fields of one Case.

The messages arrive in emission order, which is what makes steps reconstructable:
`step_start` pushes onto a stack, `step_stop` pops, and a parameter emitted while
a step is open belongs to that step rather than to the case.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from .constants import MAX_PARAMETERS_PER_STEP, MAX_STEPS_PER_TEST_ATTEMPT
from .wire import Attachment, Label, Link, Parameter, Step

_PRIORITIES = {"low", "medium", "high", "critical"}


@dataclass
class Replayed:
    labels: list[Label] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    case_parameters: list[Parameter] = field(default_factory=list)
    description: str | None = None
    priority: str | None = None


def replay(messages: list[dict[str, Any]]) -> Replayed:
    out = Replayed()
    open_steps: list[int] = []
    dropped_steps = False

    for message in messages:
        kind = message.get("kind")

        if kind == "label":
            out.labels.append(Label(name=message["name"], value=message["value"]))

        elif kind == "link":
            out.links.append(
                Link(
                    url=message["url"],
                    type=message.get("type") or "custom",
                    name=message.get("name"),
                )
            )

        elif kind == "tag":
            out.tags.extend(message.get("tags") or [])

        elif kind == "description":
            out.description = message.get("text")

        elif kind == "priority":
            value = message.get("value")
            # Unrecognised values are dropped rather than sent: the server
            # normalises them away anyway, and a bad value is not worth a row.
            if value in _PRIORITIES:
                out.priority = value

        elif kind == "parameter":
            param = Parameter(
                name=message["name"],
                value=None if message.get("masked") else message.get("value"),
                masked=bool(message.get("masked")),
            )
            if param.value is not None:
                param.value = str(param.value)
            if open_steps:
                step = out.steps[open_steps[-1]]
                if len(step.parameters) < MAX_PARAMETERS_PER_STEP:
                    step.parameters.append(param)
            else:
                out.case_parameters.append(param)

        elif kind == "step_start":
            if len(out.steps) >= MAX_STEPS_PER_TEST_ATTEMPT:
                dropped_steps = True
                continue
            step = Step(name=message.get("name") or "step", status="passed", duration=0)
            if open_steps:
                step.parent_index = open_steps[-1]
            out.steps.append(step)
            open_steps.append(len(out.steps) - 1)

        elif kind == "step_stop":
            if not open_steps:
                continue
            step = out.steps[open_steps.pop()]
            step.status = message.get("status") or "passed"
            step.duration = int(message.get("duration") or 0)
            if message.get("error"):
                step.error = message["error"]

        elif kind in ("attachment", "attachment_from_file"):
            out.attachments.append(_attachment(message))

    if dropped_steps:
        from .log import warn

        warn(
            f"a test produced more than {MAX_STEPS_PER_TEST_ATTEMPT} steps; the rest were dropped."
        )
    return out


def _attachment(message: dict[str, Any]) -> Attachment:
    name = message.get("name") or "attachment"
    mime = message.get("mimeType")
    if message.get("kind") == "attachment_from_file":
        # Only the path travelled; the plugin resolves it against the report.
        return Attachment(name=name, mime_type=mime, local_image_path=message.get("path"))
    content = message.get("content") or ""
    if message.get("encoding") != "base64":
        content = base64.b64encode(str(content).encode("utf-8")).decode("ascii")
    return Attachment(name=name, mime_type=mime, content=content)
