from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import orchestrate
from support import capture_json, message


def _account(acc_id: str, provider: str, label: str) -> dict:
    return {"id": acc_id, "provider": provider, "label": label}


class PaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["YOU_GOT_MAIL_MAX"] = "25"

    def tearDown(self) -> None:
        os.environ.pop("YOU_GOT_MAIL_MAX", None)
        os.environ.pop("YOU_GOT_MAIL_FETCH", None)

    def test_merged_next_page_follows_unread_total(self) -> None:
        accounts = [_account("gmail", "gmail", "Gmail")]
        rows = [message(f"m{i}", 1000 - i) for i in range(25)]

        def run(acc: dict, args: list[str]) -> dict:
            self.assertIn("--limit", args)
            return {"ok": True, "unread": 100, "messages": rows, "searchUrl": "https://mail.google.com"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unread"], 100)
        self.assertEqual(len(payload["messages"]), 25)
        self.assertEqual(payload["nextPage"], "25")

    def test_second_page_fetches_offset_plus_page_size(self) -> None:
        accounts = [_account("gmail", "gmail", "Gmail")]
        seen = {}

        def run(acc: dict, args: list[str]) -> dict:
            limit = int(args[args.index("--limit") + 1])
            seen["limit"] = limit
            rows = [message(f"m{i}", 2000 - i) for i in range(limit)]
            return {"ok": True, "unread": 80, "messages": rows}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "25")
        self.assertEqual(seen["limit"], 50)
        self.assertEqual(payload["thisPage"], "25")
        self.assertEqual(payload["messages"][0]["id"].startswith("gmail:"), True)
        self.assertEqual(len(payload["messages"]), 25)
        self.assertEqual(payload["nextPage"], "50")

    def test_multi_account_newest_first(self) -> None:
        accounts = [
            _account("a", "gmail", "Gmail"),
            _account("b", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            limit = int(args[args.index("--limit") + 1])
            if acc["id"] == "a":
                rows = [message(f"a{i}", 100 - i) for i in range(limit)]
                return {"ok": True, "unread": 40, "messages": rows}
            rows = [message(f"b{i}", 500 - i) for i in range(limit)]
            return {"ok": True, "unread": 40, "messages": rows}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertEqual(payload["unread"], 80)
        self.assertEqual(payload["accountCount"], 2)
        first_ids = [m["id"].split(":")[0] for m in payload["messages"]]
        self.assertTrue(all(acc == "b" for acc in first_ids))
        self.assertEqual(payload["nextPage"], "25")

    def test_no_empty_page_past_fetch_cap(self) -> None:
        os.environ["YOU_GOT_MAIL_MAX"] = "50"
        accounts = [_account("gmail", "gmail", "Gmail")]

        def run(acc: dict, args: list[str]) -> dict:
            limit = int(args[args.index("--limit") + 1])
            rows = [message(f"m{i}", 3000 - i) for i in range(limit)]
            return {"ok": True, "unread": 1000, "messages": rows}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "150")
        self.assertEqual(len(payload["messages"]), 50)
        self.assertEqual(payload["nextPage"], "")

    def test_partial_failure_sets_warning(self) -> None:
        accounts = [
            _account("a", "gmail", "Gmail"),
            _account("b", "hey", "HEY"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            if acc["id"] == "b":
                return {"ok": False, "error": "b failed"}
            return {
                "ok": True,
                "unread": 2,
                "messages": [message("1", 1), message("2", 2)],
                "searchUrl": "https://mail.google.com",
            }

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accountCount"], 2)
        self.assertEqual(payload["unread"], 2)
        self.assertEqual(payload["warning"], "b: b failed")
        self.assertEqual(len(payload["messages"]), 2)

    def test_empty_success_plus_auth_failure_is_warning(self) -> None:
        accounts = [
            _account("gmail", "gmail", "Gmail"),
            _account("outlook", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            if acc["id"] == "gmail":
                return {
                    "ok": False,
                    "error": (
                        "Authentication failed: Failed to get token: Server error: "
                        "invalid_grant: Token has been expired or revoked."
                    ),
                }
            return {"ok": True, "unread": 0, "messages": [], "searchUrl": "https://outlook.live.com/mail/inbox"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unread"], 0)
        self.assertEqual(payload["messages"], [])
        self.assertIn("gmail: Gmail sign-in expired", payload["warning"])
        self.assertIn("gws auth login", payload["warning"])
        self.assertNotIn("invalid_grant", payload["warning"])

    def test_all_accounts_fail_list_is_error(self) -> None:
        accounts = [
            _account("gmail", "gmail", "Gmail"),
            _account("outlook", "outlook", "Outlook"),
        ]

        def run(acc: dict, args: list[str]) -> dict:
            return {"ok": False, "error": acc["id"] + " down"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_list, "")
        self.assertFalse(payload["ok"])
        self.assertIn("all accounts failed", payload["error"])
        self.assertIn("gmail: gmail down", payload["error"])
        self.assertIn("outlook: outlook down", payload["error"])


class ReadAllTests(unittest.TestCase):
    def test_full_success_sums_marked(self) -> None:
        accounts = [_account("a", "gmail", "Gmail"), _account("b", "hey", "HEY")]
        seen = []

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            seen.append((acc["id"], args, timeout))
            return {"ok": True, "marked": 3 if acc["id"] == "a" else 2}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertEqual(payload, {"ok": True, "marked": 5})
        self.assertEqual({row[0] for row in seen}, {"a", "b"})
        self.assertTrue(all(row[1] == ["read-all"] for row in seen))
        self.assertTrue(all(row[2] == orchestrate.READ_ALL_TIMEOUT for row in seen))

    def test_partial_account_failure_keeps_warning_and_marks(self) -> None:
        accounts = [_account("a", "gmail", "Gmail"), _account("b", "hey", "HEY")]

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            if acc["id"] == "b":
                return {"ok": False, "marked": 1, "error": "b failed"}
            return {"ok": True, "marked": 4}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["marked"], 5)
        self.assertEqual(payload["warning"], "b: b failed")

    def test_all_accounts_fail_includes_partial_marks(self) -> None:
        accounts = [_account("a", "gmail", "Gmail"), _account("b", "hey", "HEY")]

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            return {"ok": False, "marked": 2 if acc["id"] == "a" else 0, "error": acc["id"] + " failed"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["marked"], 2)
        self.assertIn("all accounts failed", payload["error"])

    def test_timeout_uses_read_all_budget(self) -> None:
        accounts = [_account("a", "gmail", "Gmail")]

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            self.assertEqual(timeout, 120)
            return {"ok": False, "error": "a: timed out"}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_read_all)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["marked"], 0)
        self.assertEqual(payload["error"], "a: timed out")


class PreviewTests(unittest.TestCase):
    def test_gmail_preview_routes_read_only_command_and_keeps_opaque_id(self) -> None:
        accounts = [_account("gmail", "gmail", "Gmail")]
        opaque = "gmail:bXNnLTE"

        def run(acc: dict, args: list[str], timeout: int = 45) -> dict:
            self.assertEqual(args, ["preview", "msg-1"])
            self.assertEqual(timeout, orchestrate.PREVIEW_TIMEOUT)
            return {"ok": True, "contentPath": "/tmp/preview.html", "unread": True}

        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider", side_effect=run
        ):
            payload = capture_json(orchestrate.cmd_preview, opaque)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["unread"])
        self.assertEqual(payload["id"], opaque)

    def test_non_gmail_preview_does_not_call_provider(self) -> None:
        accounts = [_account("work", "outlook", "Work")]
        with patch.object(orchestrate, "load_accounts", return_value=accounts), patch.object(
            orchestrate, "_run_provider"
        ) as run:
            payload = capture_json(orchestrate.cmd_preview, "work:bXNnLTE")
        self.assertFalse(payload["ok"])
        self.assertIn("currently available for Gmail", payload["error"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
