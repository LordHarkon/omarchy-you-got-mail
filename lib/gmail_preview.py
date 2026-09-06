#!/usr/bin/env python3
"""Turn a Gmail API ``format=raw`` response into a safe local preview.

Active content is stripped, then a sandboxed headless browser outside the shell
renders the document to PDF. Quickshell only displays that inert PDF.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path

from common import one_line, write_private


BLOCKED_TAGS = {
    "applet",
    "audio",
    "base",
    "button",
    "embed",
    "form",
    "frame",
    "frameset",
    "iframe",
    "input",
    "link",
    "meta",
    "object",
    "option",
    "script",
    "select",
    "source",
    "textarea",
    "video",
}
BLOCKED_CONTAINER_TAGS = {
    "applet",
    "audio",
    "button",
    "form",
    "frame",
    "frameset",
    "iframe",
    "object",
    "option",
    "script",
    "select",
    "textarea",
    "video",
}
UNWRAPPED_TAGS = {"body", "head", "html", "title"}
VOID_TAGS = {"area", "br", "col", "hr", "img", "param", "track", "wbr"}
URL_ATTRS = {"action", "background", "formaction", "href", "poster", "src", "srcset", "xlink:href"}
REMOTE_FETCH_ATTRS = {"background", "poster", "src", "srcset", "xlink:href"}
SAFE_DATA_IMAGE = re.compile(r"^data:image/(?:gif|jpe?g|png|webp);base64,", re.I)
REMOTE_CONTENT = re.compile(
    r"(?:src|srcset|background|poster)\s*=\s*['\"]?[^'\"]*https?://|url\(\s*['\"]?\s*https?://",
    re.I,
)


def _decode_base64url(raw: str) -> bytes:
    value = (raw or "").encode("ascii", "strict")
    value += b"=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value)


def _text(part: Message) -> str:
    try:
        value = part.get_content()
    except (LookupError, UnicodeDecodeError, ValueError):
        payload = part.get_payload(decode=True) or b""
        value = payload.decode("utf-8", "replace")
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _inline_images(message: Message) -> dict[str, str]:
    images: dict[str, str] = {}
    total = 0
    for part in message.walk():
        mime = part.get_content_type().lower()
        if mime not in {"image/gif", "image/jpeg", "image/png", "image/webp"}:
            continue
        content_id = str(part.get("Content-ID") or "").strip().strip("<>")
        if not content_id:
            continue
        data = part.get_payload(decode=True) or b""
        if not data or len(data) > 2 * 1024 * 1024 or total + len(data) > 8 * 1024 * 1024:
            continue
        total += len(data)
        encoded = base64.b64encode(data).decode("ascii")
        images[content_id] = f"data:{mime};base64,{encoded}"
    return images


def _replace_cid_urls(source: str, images: dict[str, str]) -> str:
    if not images:
        return source

    def replace(match: re.Match[str]) -> str:
        cid = match.group(1).strip().strip("<>")
        return images.get(cid, "")

    return re.sub(r"cid:([^\s'\"<>]+)", replace, source, flags=re.I)


def _safe_url(value: str) -> bool:
    compact = re.sub(r"[\x00-\x20]+", "", html.unescape(value)).lower()
    if compact.startswith(("javascript:", "vbscript:", "file:", "blob:")):
        return False
    if compact.startswith("data:"):
        return bool(SAFE_DATA_IMAGE.match(compact))
    return True


class MailHtmlSanitizer(HTMLParser):
    def __init__(self, *, allow_remote: bool = False) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.blocked_depth = 0
        self.allow_remote = allow_remote

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS:
            if tag in BLOCKED_CONTAINER_TAGS:
                self.blocked_depth += 1
            return
        if self.blocked_depth or tag in UNWRAPPED_TAGS:
            return
        clean = []
        for name, value in attrs:
            name = name.lower()
            value = value or ""
            if name.startswith("on") or name in {"contenteditable", "srcdoc", "target"}:
                continue
            if (
                not self.allow_remote
                and (name in REMOTE_FETCH_ATTRS or (name == "href" and tag in {"image", "use"}))
                and re.search(r"https?://", value, re.I)
            ):
                continue
            if name in URL_ATTRS and not _safe_url(value):
                continue
            clean.append(f' {name}="{html.escape(value, quote=True)}"')
        suffix = " /" if tag in VOID_TAGS else ""
        self.output.append(f"<{tag}{''.join(clean)}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in BLOCKED_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in BLOCKED_TAGS:
            if tag in BLOCKED_CONTAINER_TAGS and self.blocked_depth > 0:
                self.blocked_depth -= 1
            return
        if self.blocked_depth or tag in UNWRAPPED_TAGS or tag in VOID_TAGS:
            return
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.blocked_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.blocked_depth:
            self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return

    def html(self) -> str:
        return "".join(self.output)


def sanitize(source: str, *, allow_remote: bool = False) -> str:
    if not allow_remote:
        source = re.sub(r"url\(\s*(['\"]?)https?://.*?\1\s*\)", "none", source, flags=re.I)
        source = re.sub(r"@import\s+(?:url\()?\s*['\"]?https?://.*?;", "", source, flags=re.I)
    parser = MailHtmlSanitizer(allow_remote=allow_remote)
    parser.feed(source)
    parser.close()
    return parser.html()


def _message_body(message: EmailMessage, *, allow_remote: bool = False) -> tuple[str, bool]:
    candidate = message.get_body(preferencelist=("html", "plain"))
    if candidate is None:
        candidate = message
    is_html = candidate.get_content_type().lower() == "text/html"
    body = _text(candidate)
    if is_html:
        body = _replace_cid_urls(body, _inline_images(message))
        has_remote = bool(REMOTE_CONTENT.search(body))
        return sanitize(body, allow_remote=allow_remote), has_remote
    escaped = html.escape(body)
    return f'<div class="plain">{escaped}</div>', False


def _attachments(message: Message) -> list[dict[str, object]]:
    rows = []
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        rows.append(
            {
                "name": one_line(str(filename), limit=120),
                "mime": part.get_content_type(),
                "size": len(payload),
            }
        )
    return rows[:50]


def render_payload(payload: dict, destination: Path, *, allow_remote: bool = False) -> dict:
    raw = payload.get("raw")
    if not isinstance(raw, str) or not raw:
        raise ValueError("Gmail returned no message body")
    message = BytesParser(policy=policy.default).parsebytes(_decode_base64url(raw))
    if not isinstance(message, EmailMessage):
        raise ValueError("could not parse message body")
    body, has_remote = _message_body(message, allow_remote=allow_remote)
    document = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="color-scheme" content="light">
<style>
  :root { color-scheme: light; }
  html, body { margin: 0; padding: 0; background: #fff; color: #161616; }
  body { font: 15px/1.48 system-ui, sans-serif; overflow-wrap: anywhere; }
  .mail-document { padding: 18px 20px 28px; min-height: 100vh; box-sizing: border-box; }
  .plain { white-space: pre-wrap; font: 14px/1.55 ui-monospace, monospace; }
  img { max-width: 100%; height: auto; }
  table { max-width: 100%; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style></head><body><main class="mail-document">""" + body + "</main></body></html>"
    write_private(destination, document)
    return {
        "ok": True,
        "subject": one_line(str(message.get("Subject") or "(no subject)"), limit=500),
        "from": one_line(str(message.get("From") or ""), limit=500),
        "to": one_line(str(message.get("To") or ""), limit=500),
        "date": one_line(str(message.get("Date") or ""), limit=200),
        "contentPath": str(destination),
        "hasRemoteContent": has_remote,
        "attachments": _attachments(message),
        "unread": "UNREAD" in (payload.get("labelIds") or []),
    }


def render_pdf(source: Path, destination: Path) -> None:
    browser = shutil.which("chromium") or shutil.which("brave") or shutil.which("brave-browser")
    if not browser:
        raise ValueError("Chromium or Brave is required for full message previews")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=destination.parent) as tmp:
        tmpdir = Path(tmp)
        output = tmpdir / "message.pdf"
        profile = tmpdir / "profile"
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-javascript",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={output}",
            source.resolve().as_uri(),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ValueError("could not render the message preview") from exc
        if not output.is_file() or output.stat().st_size == 0:
            raise ValueError("message renderer produced no preview")
        os.chmod(output, 0o600)
        os.replace(output, destination)
        os.chmod(destination, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Gmail returned an invalid message")
        html_path = args.destination.with_suffix(".html")
        result = render_payload(payload, html_path, allow_remote=args.remote)
        render_pdf(html_path, args.destination)
        result["contentPath"] = str(args.destination)
        result["contentType"] = "application/pdf"
    except Exception as exc:
        result = {"ok": False, "error": one_line(str(exc) or "could not render message")}
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
