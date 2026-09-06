"""Replays the runtime's message stream onto the fields of one Case.

The messages arrive in emission order, which is what makes steps reconstructable:
`step_start` pushes onto a stack, `step_stop` pops, and a parameter emitted while
a step is open belongs to that step rather than to the case.
"""

from __future__ import annotations

import base64
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import (
    MAX_ATTACHMENT_INLINE_CHARS,
    MAX_PARAMETERS_PER_STEP,
    MAX_STEPS_PER_TEST_ATTEMPT,
)
from .log import warn
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


def replay(messages: list[dict[str, Any]], output_dir: Path | None = None) -> Replayed:
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
            target = next((i for i in reversed(open_steps) if i >= 0), None)
            if target is not None:
                step = out.steps[target]
                if len(step.parameters) < MAX_PARAMETERS_PER_STEP:
                    step.parameters.append(param)
            else:
                out.case_parameters.append(param)

        elif kind == "step_start":
            if len(out.steps) >= MAX_STEPS_PER_TEST_ATTEMPT:
                dropped_steps = True
                # A sentinel, NOT a bare `continue`. The dropped step's matching
                # step_stop still arrives, and without something to pop it would
                # close whichever step is legitimately open -- overwriting that
                # step's status and duration, and then discarding its real stop
                # because the stack is empty. Measured: an outer step wrapping a
                # 50ms sleep reported 0.000ms once the cap was crossed.
                open_steps.append(-1)
                continue
            step = Step(name=message.get("name") or "step", status="passed", duration=0)
            parent = next((i for i in reversed(open_steps) if i >= 0), None)
            if parent is not None:
                step.parent_index = parent
            out.steps.append(step)
            open_steps.append(len(out.steps) - 1)

        elif kind == "step_stop":
            if not open_steps:
                continue
            index = open_steps.pop()
            if index < 0:
                # The sentinel for a step dropped at the cap: consumed, ignored.
                continue
            step = out.steps[index]
            step.status = message.get("status") or "passed"
            step.duration = int(message.get("duration") or 0)
            if message.get("error"):
                step.error = message["error"]

        elif kind in ("attachment", "attachment_from_file"):
            out.attachments.append(_attachment(message, output_dir))

    if dropped_steps:
        from .log import warn

        warn(
            f"a test produced more than {MAX_STEPS_PER_TEST_ATTEMPT} steps; the rest were dropped."
        )
    return out


def _attachment(message: dict[str, Any], output_dir: Path | None) -> Attachment:
    name = message.get("name") or "attachment"
    mime = message.get("mimeType")

    if message.get("kind") == "attachment_from_file":
        return _from_file(name, str(message.get("path") or ""), mime, output_dir)

    content = message.get("content") or ""
    if message.get("encoding") != "base64":
        content = base64.b64encode(str(content).encode("utf-8")).decode("ascii")
    if len(content) > MAX_ATTACHMENT_INLINE_CHARS:
        # Dropped rather than truncated: half a base64 payload is not a usable
        # file, and an oversized body is rejected whole, losing the entire launch
        # rather than this one attachment.
        warn(
            f'skipping attachment "{name}": {len(content)} encoded bytes exceeds the '
            f"{MAX_ATTACHMENT_INLINE_CHARS} inline cap."
        )
        return Attachment(name=name, mime_type=mime)
    return Attachment(name=name, mime_type=mime, content=content)


def _from_file(
    name: str, source: str, mime: str | None, output_dir: Path | None
) -> Attachment:
    """Copies the file into `outputDir` and references it RELATIVELY.

    `localImagePath` is defined as a filename relative to `outputDir`, which is
    the directory the CLI uploads. Passing the user's own path through -- which
    this used to do -- produced an absolute path the CLI could not resolve, so the
    server stored the attachment from its name alone as an undownloadable
    placeholder, and the report leaked the CI agent's directory layout.
    """
    src = Path(source)
    if output_dir is None or not src.is_file():
        warn(f'skipping attachment "{name}": {source} is not a readable file.')
        return Attachment(name=name, mime_type=mime)
    try:
        size = src.stat().st_size
        output_dir.mkdir(parents=True, exist_ok=True)
        # A uuid prefix so two tests attaching "screenshot.png" cannot collide.
        target_name = f"{uuid.uuid4().hex}-{src.name}"
        shutil.copyfile(src, output_dir / target_name)
    except OSError as err:
        warn(f'skipping attachment "{name}": could not copy {source}: {err}')
        return Attachment(name=name, mime_type=mime)
    return Attachment(
        name=name, mime_type=mime, local_image_path=target_name, file_size=size
    )
