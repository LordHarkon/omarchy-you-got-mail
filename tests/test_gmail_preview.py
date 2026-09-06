from __future__ import annotations

import base64
import struct
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

import gmail_preview
from gmail_preview import png_dimensions, render_image, render_payload, sanitize


def gmail_payload(message: EmailMessage, *, unread: bool = True) -> dict:
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    return {
        "id": "abc123",
        "threadId": "thread123",
        "labelIds": ["INBOX", "UNREAD"] if unread else ["INBOX"],
        "raw": raw,
    }


class GmailPreviewTests(unittest.TestCase):
    def test_png_dimensions_reads_ihdr_without_image_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "preview.png"
            image.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + struct.pack(">I", 13)
                + b"IHDR"
                + struct.pack(">II", 720, 413)
            )
            self.assertEqual(png_dimensions(image), (720, 413))

    def test_html_preview_keeps_layout_and_inlines_cid_image(self) -> None:
        message = EmailMessage()
        message["Subject"] = "A full message"
        message["From"] = "Ada <ada@example.test>"
        message["To"] = "Grace <grace@example.test>"
        message["Date"] = "Sun, 6 Sep 2026 12:00:00 +0300"
        message.set_content("Plain fallback")
        message.add_alternative(
            '<style>.hero{color:blue}</style><table><tr><td class="hero">Hello</td></tr></table>'
            '<img src="cid:logo"><img src="https://images.example.test/pixel.png">'
            '<script>alert(1)</script><iframe src="https://evil.example"></iframe>',
            subtype="html",
        )
        html_part = message.get_payload()[1]
        html_part.add_related(b"\x89PNG\r\n", maintype="image", subtype="png", cid="<logo>")

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "preview.html"
            result = render_payload(gmail_payload(message), destination)
            document = destination.read_text(encoding="utf-8")
            mode = destination.stat().st_mode & 0o777

        self.assertTrue(result["ok"])
        self.assertTrue(result["unread"])
        self.assertTrue(result["hasRemoteContent"])
        self.assertEqual(result["subject"], "A full message")
        self.assertIn("<table>", document)
        self.assertIn(".hero{color:blue}", document)
        self.assertIn("data:image/png;base64,", document)
        self.assertNotIn("https://images.example.test", document)
        self.assertNotIn("<script", document)
        self.assertNotIn("<iframe", document)
        self.assertEqual(mode, 0o600)

    def test_plain_preview_preserves_lines_and_escapes_markup(self) -> None:
        message = EmailMessage()
        message["Subject"] = "Plain"
        message.set_content("first line\n<script>not markup</script>\nthird line")

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "preview.html"
            result = render_payload(gmail_payload(message, unread=False), destination)
            document = destination.read_text(encoding="utf-8")

        self.assertFalse(result["unread"])
        self.assertIn('class="plain"', document)
        self.assertIn("first line\n&lt;script&gt;not markup&lt;/script&gt;\nthird line", document)

    def test_sanitizer_removes_active_attributes_and_schemes(self) -> None:
        cleaned = sanitize(
            '<div onclick="steal()"><a href="javascript:steal()">bad</a>'
            '<img onerror="steal()" src="file:///etc/passwd"><b>safe</b></div>'
        )
        self.assertNotIn("onclick", cleaned)
        self.assertNotIn("onerror", cleaned)
        self.assertNotIn("javascript:", cleaned)
        self.assertNotIn("file:", cleaned)
        self.assertIn("<b>safe</b>", cleaned)

    def test_void_meta_does_not_hide_following_body(self) -> None:
        cleaned = sanitize('<meta charset="utf-8"><p>still visible</p>')
        self.assertEqual(cleaned, "<p>still visible</p>")

    def test_remote_resources_require_explicit_opt_in(self) -> None:
        source = (
            '<picture><source srcset="//images.example.test/a.webp">'
            '<img loading="lazy" decoding="async" src="https://images.example.test/a.png"></picture>'
            '<a href="https://example.test">link</a>'
        )
        blocked = sanitize(source)
        allowed = sanitize(source, allow_remote=True)
        self.assertNotIn("images.example.test", blocked)
        self.assertIn("href=\"https://example.test\"", blocked)
        self.assertIn("images.example.test", allowed)
        self.assertIn("<source", allowed)
        self.assertNotIn("loading=", allowed)
        self.assertNotIn("decoding=", allowed)

    def test_renderer_retries_transient_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            gmail_preview.shutil, "which", side_effect=["/browser", "/magick"]
        ), mock.patch.object(
            gmail_preview,
            "_render_image_once",
            side_effect=[ValueError("transient"), (720, 413)],
        ) as render_once, mock.patch.object(gmail_preview.time, "sleep") as sleep:
            dimensions = render_image(Path(tmp) / "mail.html", Path(tmp) / "mail.png")

        self.assertEqual(dimensions, (720, 413))
        self.assertEqual(render_once.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
