from __future__ import annotations

import json
import math
import unittest

from support import ROOT


class PanelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qml = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_passes_limit_from_widget_settings(self) -> None:
        self.assertIn('setting("max", 25)', self.qml)
        self.assertIn('setting("refreshIntervalSec", 60)', self.qml)
        self.assertIn('"--limit"', self.qml)

    def test_surfaces_partial_warning(self) -> None:
        self.assertIn("property string warningText", self.qml)
        self.assertIn("data.warning", self.qml)
        self.assertIn("partialWarning", self.qml)

    def test_error_banner_wraps_and_empty_state_does_not_repeat(self) -> None:
        self.assertIn("id: staleWarning", self.qml)
        self.assertIn("wrapMode: Text.WordWrap", self.qml)
        self.assertIn(
            '"Fix sign-in from a terminal, then middle-click the icon."',
            self.qml,
        )
        empty = self.qml.split("You're all caught up.")[1].split("textFormat:")[0]
        self.assertNotIn("root.errorText", empty)

    def test_keyboard_and_tooltip(self) -> None:
        self.assertIn("onTabRequested", self.qml)
        self.assertIn('t === "i"', self.qml)
        self.assertIn("tooltipText:", self.qml)
        self.assertIn("Open unread in browser (i)", self.qml)

    def test_chips_are_capped(self) -> None:
        self.assertIn("elide: Text.ElideRight", self.qml)
        self.assertIn("Style.space(64)", self.qml)
        self.assertIn("Math.max(Style.space(40)", self.qml)

    def test_readme_uses_https_install(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/BVisagie/omarchy-you-got-mail.git", readme)
        self.assertIn("omarchy plugin update bvisagie.you-got-mail", readme)
        self.assertIn("omarchy plugin update bvisagie.you-got-mail --yes", readme)
        self.assertIn("`q`", readme)
        self.assertIn("~/.bun/bin", readme)
        self.assertIn("YOU_GOT_MAIL_IMAP_PASSWORD", readme)
        self.assertIn("gws auth setup", readme)
        self.assertIn("accounts login", readme)
        self.assertIn("GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file", readme)
        self.assertIn("No sudo or pkexec is required", readme)
        self.assertNotIn("must be public", readme)
        self.assertTrue((ROOT / "preview.png").is_file(), "marketplace listing wants root preview.png")
        self.assertIn("preview.png", readme)

    def test_changelog_matches_manifest(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {self.manifest['version']}", changelog)

    def test_bar_icon_uses_adaptive_colors(self) -> None:
        self.assertNotIn("active: root.opened", self.qml)
        self.assertIn("color: button.foreground", self.qml)
        self.assertIn("flagColor: button.foreground", self.qml)
        self.assertIn("hasMail: root.hasUnread && root.reachable", self.qml)
        self.assertIn("color: Qt.rgba(button.foreground.r, button.foreground.g,", self.qml)
        self.assertNotIn("button.activeColor", self.qml)
        self.assertNotIn("color: Color.background", self.qml)
        self.assertNotIn(
            "flagColor: (root.hasUnread && root.reachable) ? button.activeColor : button.foreground",
            self.qml,
        )
        self.assertNotIn("color: root.opened ? root.accent : root.foreground", self.qml)
        self.assertNotIn(
            "flagColor: (root.hasUnread && root.reachable) ? root.accent : root.foreground",
            self.qml,
        )

    def test_mark_all_confirm_and_busy(self) -> None:
        self.assertIn("Mark all unread as read (A)", self.qml)
        self.assertIn("Click again to confirm", self.qml)
        self.assertIn("Marking unread mail as read…", self.qml)
        self.assertIn('t === "a"', self.qml)
        self.assertIn('t === "A"', self.qml)
        self.assertIn("function markCursorRead()", self.qml)
        self.assertIn("function enqueueRead(", self.qml)
        self.assertIn("function pumpRead()", self.qml)
        self.assertIn("property var dismissedIds", self.qml)
        self.assertIn("property var readQueue", self.qml)
        self.assertIn("property bool markAllArmed", self.qml)
        self.assertIn("property bool markAllBusy", self.qml)
        self.assertIn("property string actionWarning", self.qml)
        self.assertIn('readAllProc.command = [root.script, "read-all"]', self.qml)
        self.assertIn("applyReadAllPayload", self.qml)
        self.assertIn("root.actionWarning", self.qml)
        self.assertIn("opacity: root.markAllBusy ? 0.4 : 1", self.qml)
        self.assertNotIn("unread = 0", self.qml)
        self.assertNotIn("messages = []", self.qml)
        self.assertRegex(self.qml, r't === "a"\)\s+root\.markCursorRead\(\)')
        self.assertRegex(self.qml, r't === "A"\)\s+root\.requestMarkAll\(\)')
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Header envelope-open or `A`", readme)
        self.assertIn("mark the message under the cursor as read, without opening it", readme)

    def test_gmail_preview_is_in_panel_and_unread_safe(self) -> None:
        self.assertNotIn("import QtQuick.Pdf", self.qml)
        self.assertIn('previewProc.command = [root.script, "preview", message.id]', self.qml)
        self.assertIn("function previewMessage(message)", self.qml)
        self.assertIn("function closeDetail()", self.qml)
        self.assertIn("Flickable", self.qml)
        self.assertIn("previewFrame.fittedImageHeight", self.qml)
        self.assertIn("root.detailMessage.previewHeight", self.qml)
        self.assertNotIn("PdfDocument", self.qml)
        self.assertNotIn("WebEngineView", self.qml)
        self.assertIn('argv.push("--remote")', self.qml)
        self.assertIn("root.previewMessage(row.modelData)", self.qml)
        preview = self.qml.split("function previewMessage(message)")[1].split("function closeDetail()")[0]
        self.assertNotIn("enqueueRead", preview)
        self.assertNotIn("dismissLocal", preview)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("preview the complete message in the panel; it stays unread", readme)
        self.assertIn("Remote images stay blocked", readme)

    def test_ipc_preview_hook_and_current_browser_launcher(self) -> None:
        self.assertIn("manageIpc: false", self.qml)
        self.assertIn("function previewFirst(): string", self.qml)
        self.assertIn('Quickshell.execDetached(["omarchy-launch-browser", url])', self.qml)
        self.assertNotIn("Util.execArgv", self.qml)

    def test_mailbox_is_stroked_and_contained(self) -> None:
        icon = (ROOT / "MailSlotIcon.qml").read_text(encoding="utf-8")
        self.assertIn("ctx.arc(", icon)
        self.assertIn("ctx.lineWidth", icon)
        self.assertIn("flagAmount", icon)
        self.assertIn("up / 1.42", icon)
        self.assertNotIn("layer.enabled", icon)

    def test_flag_poses_stay_inside_canvas(self) -> None:
        for size in (12, 16, 20, 24, 32):
            for dpr in (1.0, 1.5, 2.0):
                geom = mailbox_geometry(size, dpr)
                self.assertGreater(geom["flagLen"], 0, msg=f"size={size} dpr={dpr}")
                self.assertLessEqual(geom["postY"] + geom["postH"], size + 0.51)
                for amount in (0.0, 0.25, 0.5, 0.75, 1.0):
                    for x, y in flag_corners(geom, amount):
                        self.assertGreaterEqual(x, -0.51, msg=f"size={size} t={amount}")
                        self.assertGreaterEqual(y, -0.51, msg=f"size={size} t={amount}")
                        self.assertLessEqual(x, size + 0.51, msg=f"size={size} t={amount}")
                        self.assertLessEqual(y, size + 0.51, msg=f"size={size} t={amount}")


def _snap(value: float, dpr: float) -> float:
    return round(value * dpr) / dpr


def _snap_stroke(value: float, dpr: float) -> float:
    return max(1, round(value * dpr)) / dpr


def mailbox_geometry(icon_size: float, dpr: float = 1.0) -> dict[str, float]:
    stroke = _snap_stroke(max(1.5, icon_size * 0.12), dpr)
    pad = _snap(max(stroke / 2, 0.5), dpr)
    min_flag = stroke * 1.8
    body_w = _snap(min(icon_size * 0.66, icon_size - pad * 2 - min_flag), dpr)
    arch_r = _snap(body_w / 2, dpr)
    post_h = _snap(max(stroke * 1.2, icon_size * 0.14), dpr)
    max_h = icon_size - pad * 2 - post_h - arch_r
    body_rect_h = _snap(max(stroke * 2, min(icon_size * 0.26, max_h)), dpr)
    body_h = _snap(arch_r + body_rect_h, dpr)
    body_x = _snap(pad, dpr)
    body_y = _snap(max(pad, icon_size - pad - post_h - body_h), dpr)
    pivot_x = _snap(body_x + body_w - stroke * 0.2, dpr)
    pivot_y = _snap(body_y + arch_r * 0.42, dpr)
    up = max(0.0, pivot_y - pad)
    right = max(0.0, icon_size - pad - pivot_x)
    left = max(0.0, pivot_x - pad)
    flag_len = _snap(max(0.0, min(icon_size * 0.30, up / 1.42, right, left)), dpr)
    stem_thick = _snap(min(flag_len, max(1.6, min(icon_size * 0.14, flag_len * 0.46))), dpr)
    cloth_thick = _snap(min(flag_len, max(2.0, min(icon_size * 0.18, flag_len * 0.58))), dpr)
    return {
        "size": icon_size,
        "postY": body_y + body_h,
        "postH": post_h,
        "pivotX": pivot_x,
        "pivotY": pivot_y,
        "flagLen": flag_len,
        "stemThick": stem_thick,
        "clothThick": cloth_thick,
    }


def flag_corners(geom: dict[str, float], amount: float) -> list[tuple[float, float]]:
    pivot_x = geom["pivotX"]
    pivot_y = geom["pivotY"]
    stem = geom["flagLen"]
    cloth = geom["flagLen"]
    stem_thick = geom["stemThick"]
    cloth_thick = geom["clothThick"]
    theta = -math.pi / 2 * amount
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    def xform(lx: float, ly: float) -> tuple[float, float]:
        return (
            pivot_x + lx * cos_t - ly * sin_t,
            pivot_y + lx * sin_t + ly * cos_t,
        )

    return [
        xform(0, -stem_thick / 2),
        xform(0, stem_thick / 2),
        xform(stem, -stem_thick / 2),
        xform(stem, stem_thick / 2),
        xform(stem - cloth_thick, -cloth),
        xform(stem, -cloth),
        xform(stem, 0),
        xform(stem - cloth_thick, 0),
    ]


if __name__ == "__main__":
    unittest.main()
