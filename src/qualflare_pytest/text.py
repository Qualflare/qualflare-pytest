"""Text clamping helpers.

Every limit here is measured in CHARACTERS, matching the server's rune counting
for the BMP; Python strings are already code points, so `len()` is the right
measure and no encoding round-trip is needed.
"""

from __future__ import annotations

from .constants import MAX_ATTEMPT_OUTPUT_LINES, MAX_ATTEMPT_OUTPUT_RUNES


def truncate(value: str | None, max_chars: int) -> str | None:
    """Clamps to `max_chars`, returning None for empty input so the key can be omitted."""
    if not value:
        return None
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def clamp_output(lines: list[str] | None) -> list[str] | None:
    """Bounds captured output by LINES first, then by total characters.

    The order matters and matches the server: line-clamp first so the head of the
    output survives, then character-clamp so one pathological line cannot blow the
    budget on its own.
    """
    if not lines:
        return None
    clipped = lines[:MAX_ATTEMPT_OUTPUT_LINES]
    out: list[str] = []
    total = 0
    for line in clipped:
        if total >= MAX_ATTEMPT_OUTPUT_RUNES:
            break
        room = MAX_ATTEMPT_OUTPUT_RUNES - total
        piece = line[:room]
        total += len(piece)
        out.append(piece)
    return out or None
