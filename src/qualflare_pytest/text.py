"""Text clamping helpers.

Every limit here is measured in CHARACTERS, matching the server's rune counting
for the BMP; Python strings are already code points, so `len()` is the right
measure and no encoding round-trip is needed.
"""

from __future__ import annotations


def truncate(value: str | None, max_chars: int) -> str | None:
    """Clamps to `max_chars`, returning None for empty input so the key can be omitted."""
    if not value:
        return None
    if len(value) <= max_chars:
        return value
    return value[:max_chars]
