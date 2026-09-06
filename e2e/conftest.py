"""Dogfood configuration.

The suite reports through the plugin under test, then the PUBLISHED
`qualflare-cli` uploads the result. That seam is the point: every other suite in
this repo stops at the report file on disk, so nothing exercises the
plugin/CLI pairing. In the JavaScript siblings it broke twice — `Case.attempts`
was silently discarded by the CLI's parser for three releases, and
`localImagePath` needed a CLI floor nothing enforced.

The suite contains NO failing tests by construction. Status mapping for
failures is `tests/`'s job; a red run here should mean the seam broke, not that a
fixture failed on purpose.
"""
