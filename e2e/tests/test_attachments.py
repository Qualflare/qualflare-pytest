import base64

from qualflare_pytest import qualflare

# A real 1x1 PNG, not something merely named one: the upload endpoint
# cross-checks the extension against the MIME type it is handed.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_attaches_a_screenshot(tmp_path):
    shot = tmp_path / "screenshot.png"
    shot.write_bytes(PNG)
    qualflare.attachment_from_file("screenshot", str(shot), mime_type="image/png")
    qualflare.attachment("note", "plain text attachment", mime_type="text/plain")
