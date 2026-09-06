"""Caps the Qualflare wire contract and server enforce.

Ported verbatim from the sibling reporters' `shared/constants.ts`, which are in
turn derived from `api-service`'s `launch.go`. Keep the numbers identical across
packages: a report that is valid from one reporter must be valid from all of them.
"""

MAX_SUITES_PER_LAUNCH = 2000
MAX_CASES_PER_SUITE = 5000

# The server's hard cap is 1000 steps per case. The client stops at 300 per
# attempt and warns, so a runaway suite is bounded before it reaches the body
# limit rather than being silently truncated on write.
MAX_STEPS_PER_CASE = 1000
MAX_STEPS_PER_TEST_ATTEMPT = 300
MAX_PARAMETERS_PER_STEP = 50

MAX_ATTACHMENTS_PER_CASE = 50
MAX_LABELS_PER_CASE = 100
MAX_LINKS_PER_CASE = 20
MAX_TAGS_PER_CASE = 64
MAX_TAG_LENGTH = 255

MAX_ATTEMPTS_PER_CASE = 50
MAX_ATTEMPT_MESSAGE_RUNES = 8192
MAX_ATTEMPT_TRACE_RUNES = 32768
MAX_ATTEMPT_SNIPPET_RUNES = 4096
MAX_ATTEMPT_OUTPUT_RUNES = 16384
MAX_ATTEMPT_OUTPUT_LINES = 200

# Truncated server-side rather than rejected, so the full text is sent and the
# server decides. Kept here only to size the client's own guard rails.
MAX_CASE_ERROR_RUNES = 65536

MAX_ATTACHMENT_INLINE_CHARS = 2_097_152

# The key this plugin owns inside `TestReport.user_properties`. A single reserved
# key keeps our payload out of the way of the user's own `record_property()`
# calls, which land in the same list.
USER_PROPERTY_KEY = "__qualflare__"
