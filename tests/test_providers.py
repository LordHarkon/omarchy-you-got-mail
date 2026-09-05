from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from support import capture_json, load_provider


class FastmailReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fm = load_provider("fastmail")

    def _read(self, responses: list) -> dict:
        with patch.object(self.fm, "_session", return_value={"primaryAccounts": {"urn:ietf:params:jmap:mail": "acc"}}), patch.object(
            self.fm, "_jmap", return_value=responses
        ):
            return capture_json(self.fm.cmd_read, "token", "msg-1")

    def test_success_requires_updated_id(self) -> None:
        payload = self._read([["Email/set", {"updated": {"msg-1": {}}}, "s"]])
        self.assertEqual(payload, {"ok": True})

    def test_not_updated_is_failure(self) -> None:
        payload = self._read(
            [["Email/set", {"updated": {}, "notUpdated": {"msg-1": {"type": "notFound"}}}, "s"]]
        )
        self.assertFalse(payload["ok"])

    def test_missing_set_result_is_failure(self) -> None:
        payload = self._read([["error", {"description": "nope"}, "s"]])
        self.assertFalse(payload["ok"])


class HeyUnreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hey = load_provider("hey")

    def test_envelope_unseen_count(self) -> None:
        payload_box = {
            "ok": True,
            "data": {
                "unseen_count": 100,
                "app_url": "https://app.hey.com/imbox",
                "postings": [
                    {"id": "1", "account_id": "acc", "seen": False, "name": "One\nline", "created_at": "2026-01-01T00:00:00Z"},
                    {"id": "2", "account_id": "acc", "seen": False, "name": "Two", "created_at": "2026-01-02T00:00:00Z"},
                ],
            },
        }
        with patch.object(self.hey, "_hey", return_value=payload_box):
            out = capture_json(self.hey.cmd_list, {"id": "hey", "label": "HEY"}, 25)
        self.assertTrue(out["ok"])
        self.assertEqual(out["unread"], 100)
        self.assertEqual(len(out["messages"]), 2)
        self.assertEqual(out["messages"][0]["subject"], "One line")

    def test_pages_until_limit_even_with_envelope(self) -> None:
        calls = {"n": 0}

        def fake_hey(acc, args, timeout=40):
            calls["n"] += 1
            page = "2" if "--page" not in args else ""
            return {
                "ok": True,
                "data": {
                    "unseen_count": 80,
                    "next_page": page,
                    "postings": [
                        {
                            "id": f"p{calls['n']}-{i}",
                            "account_id": "acc",
                            "seen": False,
                            "name": f"Msg {i}",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                        for i in range(2)
                    ],
                },
            }

        with patch.object(self.hey, "_hey", side_effect=fake_hey):
            out = capture_json(self.hey.cmd_list, {"id": "hey"}, 3)
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(out["unread"], 80)
        self.assertEqual(len(out["messages"]), 3)


class FastmailReadAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fm = load_provider("fastmail")

    def test_queries_complete_before_sets_and_honours_chunk_size(self) -> None:
        names: list[str] = []

        def fake_jmap(session, token, calls):
            name = calls[0][0]
            names.append(name)
            if name == "Mailbox/get":
                return [["Mailbox/get", {"list": [{"id": "trash", "role": "trash"}]}, "mb"]]
            if name == "Email/query":
                pos = int(calls[0][1].get("position") or 0)
                if pos == 0:
                    return [["Email/query", {"ids": ["a", "b"], "total": 3}, "q"]]
                return [["Email/query", {"ids": ["c"], "total": 3}, "q"]]
            if name == "Email/set":
                update = calls[0][1]["update"]
                return [["Email/set", {"updated": {key: {} for key in update}}, "s"]]
            return []

        session = {
            "primaryAccounts": {"urn:ietf:params:jmap:mail": "acc"},
            "apiUrl": "https://api.fastmail.com/jmap/api",
            "capabilities": {"urn:ietf:params:jmap:core": {"maxObjectsInSet": 2}},
        }
        with patch.object(self.fm, "_session", return_value=session), patch.object(
            self.fm, "QUERY_PAGE", 2
        ), patch.object(self.fm, "_jmap", side_effect=fake_jmap), patch.object(
            self.fm, "_try_jmap", side_effect=lambda s, t, c: (fake_jmap(s, t, c), "")
        ):
            payload = capture_json(self.fm.cmd_read_all, "token")
        self.assertEqual(payload, {"ok": True, "marked": 3})
        self.assertLess(names.index("Email/query"), names.index("Email/set"))
        self.assertEqual(names.count("Email/query"), 2)
        self.assertEqual(names.count("Email/set"), 2)

    def test_not_updated_is_partial_failure(self) -> None:
        def fake_jmap(session, token, calls):
            name = calls[0][0]
            if name == "Mailbox/get":
                return [["Mailbox/get", {"list": []}, "mb"]]
            if name == "Email/query":
                return [["Email/query", {"ids": ["a", "b"], "total": 2}, "q"]]
            return [["Email/set", {"updated": {"a": {}}, "notUpdated": {"b": {"type": "notFound"}}}, "s"]]

        session = {"primaryAccounts": {"urn:ietf:params:jmap:mail": "acc"}, "apiUrl": "https://x"}
        with patch.object(self.fm, "_session", return_value=session), patch.object(
            self.fm, "_jmap", side_effect=fake_jmap
        ), patch.object(self.fm, "_try_jmap", side_effect=lambda s, t, c: (fake_jmap(s, t, c), "")):
            payload = capture_json(self.fm.cmd_read_all, "token")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["marked"], 1)


class OutlookReadAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.out = load_provider("outlook")

    def test_folder_ids_skip_junk(self) -> None:
        inbox = "inbox-id"
        junk = "junk-id"

        def fake_http(method, url, token, payload=None, extra_headers=None):
            if "childFolders" in url:
                return {"value": []}
            return {"value": [{"id": inbox}, {"id": junk}]}

        with patch.object(self.out, "_http", side_effect=fake_http):
            ids = self.out._unread_folder_ids("tok", {junk})
        self.assertEqual(ids, [inbox])

    def test_batch_partial_failure_counts_successes(self) -> None:
        def fake_try_http(method, url, token, payload=None, extra_headers=None):
            self.assertEqual(url, self.out.GRAPH + "/$batch")
            self.assertEqual(len(payload["requests"]), 2)
            return {
                "responses": [
                    {"id": "0", "status": 200},
                    {"id": "1", "status": 500},
                ]
            }, ""

        with patch.object(self.out, "_try_http", side_effect=fake_try_http), patch.object(
            self.out, "BATCH_SIZE", 20
        ):
            marked, err = self.out._batch_mark_read("tok", ["m1", "m2"], deadline=1e18)
        self.assertEqual(marked, 1)
        self.assertEqual(err, "could not mark as read")

    def test_chunked_respects_batch_size(self) -> None:
        chunks = self.out._chunked([f"m{i}" for i in range(25)], 20)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 20)
        self.assertEqual(len(chunks[1]), 5)


class ImapReadAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.imap = load_provider("imap")

    def test_snapshots_unseen_then_stores_in_chunks(self) -> None:
        stored = []
        searches = []

        class FakeClient:
            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

            def select(self, folder, readonly=False):
                return "OK", []

            def uid(self, cmd, *args):
                if cmd == "search":
                    searches.append(args)
                    return "OK", [b"1 2 3"]
                if cmd == "store":
                    stored.append(args)
                    return "OK", []
                raise AssertionError(cmd)

            def logout(self):
                return "OK", []

        fake = FakeClient()
        with patch.object(self.imap, "_connect", return_value=fake), patch.object(
            self.imap, "UID_CHUNK", 2
        ):
            payload = capture_json(
                self.imap.cmd_read_all, {"host": "h", "user": "u"}, "pw"
            )
        self.assertEqual(payload, {"ok": True, "marked": 3})
        self.assertEqual(searches, [(None, "UNSEEN")])
        self.assertEqual([row[0] for row in stored], ["1,2", "3"])
        self.assertTrue(all(row[1] == "+FLAGS" for row in stored))

    def test_read_all_uses_configured_folders(self) -> None:
        listed = []
        selected = []

        class FakeClient:
            def list(self):
                listed.append(True)
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

            def select(self, folder, readonly=False):
                selected.append(folder)
                return "OK", []

            def uid(self, cmd, *args):
                if cmd == "search":
                    return "OK", [b"9"]
                if cmd == "store":
                    return "OK", []
                raise AssertionError(cmd)

            def logout(self):
                return "OK", []

        fake = FakeClient()
        with patch.object(self.imap, "_connect", return_value=fake):
            payload = capture_json(
                self.imap.cmd_read_all,
                {"host": "h", "user": "u", "folders": ["INBOX/Work"]},
                "pw",
            )
        self.assertEqual(payload, {"ok": True, "marked": 1})
        self.assertEqual(listed, [])
        self.assertEqual(selected, ["INBOX/Work", "INBOX/Work"])


class ImapFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.imap = load_provider("imap")

    def _client(self, rows: list[bytes]):
        class FakeClient:
            def list(inner_self):
                return "OK", rows

        return FakeClient()

    def test_english_names_are_skipped(self) -> None:
        client = self._client(
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Trash"',
                b'(\\HasNoChildren) "/" "Junk"',
                b'(\\HasNoChildren) "/" "Drafts"',
                b'(\\HasNoChildren) "/" "Sent"',
            ]
        )
        self.assertEqual(self.imap._folders(client), ["INBOX"])

    def test_special_use_skipped_when_name_would_not_match(self) -> None:
        client = self._client(
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren \\All) "/" "[Gmail]/Todos os e-mails"',
                b'(\\HasNoChildren \\Flagged) "/" "[Gmail]/Com estrela"',
                b'(\\HasNoChildren \\Important) "/" "[Gmail]/Importante"',
                b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Lixeira"',
                b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
            ]
        )
        self.assertEqual(self.imap._folders(client), ["INBOX"])

    def test_inbox_and_user_folder_are_kept(self) -> None:
        client = self._client(
            [
                b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "INBOX/Work"',
                '(\\HasNoChildren) "/" "Promoções"'.encode(),
            ]
        )
        self.assertEqual(
            self.imap._folders(client), ["INBOX", "INBOX/Work", "Promoções"]
        )

    def test_configured_folders_are_authoritative(self) -> None:
        class Boom:
            def list(self):
                raise AssertionError("LIST must not run when folders is set")

        acc = {"folders": ["INBOX", "INBOX/Work", "Trash"]}
        self.assertEqual(
            self.imap._folders(Boom(), acc), ["INBOX", "INBOX/Work", "Trash"]
        )

    def test_missing_or_empty_folders_falls_through_to_discovery(self) -> None:
        client = self._client(
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Trash"',
            ]
        )
        self.assertEqual(self.imap._folders(client), ["INBOX"])
        self.assertEqual(self.imap._folders(client, {}), ["INBOX"])
        self.assertEqual(self.imap._folders(client, {"folders": []}), ["INBOX"])
        self.assertEqual(self.imap._folders(client, {"folders": ["  "]}), ["INBOX"])
        self.assertEqual(self.imap._folders(client, {"folders": "INBOX"}), ["INBOX"])

    def test_connect_passes_socket_timeout(self) -> None:
        fake = MagicMock()
        with patch.object(self.imap.imaplib, "IMAP4_SSL", return_value=fake) as ctor:
            client = self.imap._connect(
                {"host": "imap.example.test", "port": 993, "user": "u"}, "pw"
            )
        self.assertIs(client, fake)
        self.assertEqual(self.imap.SOCKET_TIMEOUT, 30)
        kwargs = ctor.call_args.kwargs
        self.assertEqual(kwargs.get("timeout"), 30)
        fake.login.assert_called_once_with("u", "pw")


class HeyReadAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hey = load_provider("hey")

    def test_collects_pages_before_seen_and_dedupes(self) -> None:
        boxes = [
            {
                "ok": True,
                "data": {
                    "next_page": "2",
                    "postings": [
                        {"id": "1", "account_id": "acc", "seen": False},
                        {"id": "2", "account_id": "acc", "seen": False},
                    ],
                },
            },
            {
                "ok": True,
                "data": {
                    "postings": [
                        {"id": "2", "account_id": "acc", "seen": False},
                        {"id": "3", "account_id": "acc", "seen": False},
                    ],
                },
            },
        ]
        seen_calls = []

        def fake_hey(acc, args, timeout=40):
            if args[0] == "box":
                return boxes.pop(0)
            seen_calls.append(args[1])
            return {"ok": True}

        with patch.object(self.hey, "_hey", side_effect=fake_hey), patch.object(
            self.hey, "_try_hey", side_effect=lambda acc, args, timeout=40: (fake_hey(acc, args, timeout), "")
        ):
            payload = capture_json(self.hey.cmd_read_all, {"id": "hey"})
        self.assertEqual(payload, {"ok": True, "marked": 3})
        self.assertEqual(seen_calls, ["1", "2", "3"])

    def test_repeated_page_token_fails_before_seen(self) -> None:
        def fake_hey(acc, args, timeout=40):
            self.assertEqual(args[0], "box")
            return {"ok": True, "data": {"next_page": "same", "postings": [{"id": "1", "seen": False}]}}

        with patch.object(self.hey, "_hey", side_effect=fake_hey):
            payload = capture_json(self.hey.cmd_read_all, {"id": "hey"})
        self.assertFalse(payload["ok"])
        self.assertIn("repeated a page token", payload["error"])


class GmailScriptTests(unittest.TestCase):
    def test_counts_matching_ids_not_size_estimate(self) -> None:
        from support import ROOT

        script = (ROOT / "providers" / "gmail").read_text(encoding="utf-8")
        self.assertIn("unread_total", script)
        self.assertNotIn("unread_estimate", script)
        self.assertNotIn("resultSizeEstimate", script)
        # Display pages stay small; a 500-wide list is only the count path.
        self.assertIn('--argjson n 500', script)
        self.assertIn("mkdir -p --", script)
        self.assertNotIn("mkdir -p -m", script)
        self.assertIn("gmail_error", script)
        self.assertIn("gws_list", script)
        self.assertNotIn('gws gmail "$@" 2>/dev/null', script)
        self.assertIn("gws auth login -s gmail", script)
        import subprocess

        subprocess.check_call(["bash", "-n", str(ROOT / "providers" / "gmail")])

    def test_read_all_uses_same_query_and_batch_modify(self) -> None:
        from support import ROOT

        script = (ROOT / "providers" / "gmail").read_text(encoding="utf-8")
        self.assertIn("cmd_read_all()", script)
        self.assertIn("users messages batchModify", script)
        self.assertIn('read-all) cmd_read_all', script)
        self.assertIn("$QUERY", script)
        self.assertIn("fail_read_all", script)
        self.assertNotIn("users messages modify", script.split("cmd_read_all()")[1].split("case ")[0])

    def test_preview_fetches_raw_without_modifying_unread(self) -> None:
        from support import ROOT

        script = (ROOT / "providers" / "gmail").read_text(encoding="utf-8")
        preview = script.split("cmd_preview() {")[1].split("fail_read_all()", 1)[0]
        self.assertIn("users messages get", preview)
        self.assertIn('format:"raw"', preview)
        self.assertIn("gmail_preview.py", preview)
        self.assertNotIn("users messages modify", preview)


class OutlookUnreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.out = load_provider("outlook")

    def test_folder_unread_skips_junk(self) -> None:
        inbox = "inbox-id"
        junk = "junk-id"

        def fake_http(method, url, token, payload=None, extra_headers=None):
            if "childFolders" in url:
                return {"value": []}
            return {
                "value": [
                    {"id": inbox, "unreadItemCount": 90},
                    {"id": junk, "unreadItemCount": 12},
                ]
            }

        with patch.object(self.out, "_http", side_effect=fake_http):
            total = self.out._folder_unread_total("tok", {junk})
        self.assertEqual(total, 90)

    def test_one_line_preview(self) -> None:
        self.assertEqual(self.out.one_line("Hi\r\nthere"), "Hi there")

    def test_token_refresh_uses_lock_and_maps_auth(self) -> None:
        from support import ROOT

        source = (ROOT / "providers" / "outlook").read_text(encoding="utf-8")
        self.assertIn("fcntl.flock", source)
        self.assertIn(".lock", source)
        self.assertIn("account_error", source)
        self.assertIn("load_secret", source)

    def test_cache_uses_write_private(self) -> None:
        from support import ROOT

        source = (ROOT / "providers" / "outlook").read_text(encoding="utf-8")
        self.assertIn("write_private(_cache_dir(account_id)", source)
        self.assertNotIn('path.name + ".tmp"', source)
        self.assertNotIn("tmp.write_text", source)

    def test_cache_uses_read_owned_file(self) -> None:
        from support import ROOT

        source = (ROOT / "providers" / "outlook").read_text(encoding="utf-8")
        self.assertIn("read_owned_file(path)", source)
        self.assertIn("O_NOFOLLOW", (ROOT / "lib" / "common.py").read_text(encoding="utf-8"))
        self.assertNotIn("path.read_text", source)

    def test_read_cache_skips_symlink_fifo_and_oversize(self) -> None:
        import json
        import os
        import shutil
        import tempfile
        from pathlib import Path

        from support import ROOT

        root = ROOT / ".test-tmp"
        root.mkdir(exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=root))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        limit = self.out.read_owned_file.__defaults__[0]
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp / "cache")}):
            real = self.out._cache_dir("work") / "outlook.json"
            payload = {"email": "a@b.test", "email_at": 1}
            real.write_text(json.dumps(payload), encoding="utf-8")
            os.chmod(real, 0o600)
            self.assertEqual(self.out._read_cache("work")["email"], "a@b.test")

            real.unlink()
            target = real.parent / "other.json"
            target.write_text(json.dumps(payload), encoding="utf-8")
            os.chmod(target, 0o600)
            real.symlink_to(target)
            self.assertEqual(self.out._read_cache("work"), {})
            real.unlink()

            os.mkfifo(real)
            self.assertEqual(self.out._read_cache("work"), {})
            real.unlink()

            real.write_bytes(b"{" + b"x" * (limit + 1) + b"}")
            os.chmod(real, 0o600)
            self.assertEqual(self.out._read_cache("work"), {})


class BoundedHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.out = load_provider("outlook")
        cls.fm = load_provider("fastmail")

    def _resp(self, data: bytes, content_length: str | None = None):
        import io

        class Resp:
            def __init__(self) -> None:
                self._buf = io.BytesIO(data)
                self.headers = {}
                if content_length is not None:
                    self.headers["Content-Length"] = content_length

            def read(self, n: int = -1) -> bytes:
                return self._buf.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *args) -> bool:
                return False

        return Resp()

    def test_outlook_rejects_oversized_body(self) -> None:
        huge = b"{" + b"x" * (self.out.read_http_body.__defaults__[0] + 1)
        with patch.object(self.out.urllib.request, "urlopen", return_value=self._resp(huge)):
            data, err = self.out._try_http("GET", "https://graph.microsoft.com/v1.0/me", "tok")
        self.assertIsNone(data)
        self.assertEqual(err, "response too large")

    def test_fastmail_rejects_oversized_body(self) -> None:
        huge = b"{" + b"x" * (self.fm.read_http_body.__defaults__[0] + 1)
        with patch.object(self.fm.urllib.request, "urlopen", return_value=self._resp(huge)):
            data, err = self.fm._try_request("https://api.fastmail.com/jmap/session", "tok")
        self.assertIsNone(data)
        self.assertEqual(err, "response too large")

    def test_outlook_auth_rejects_oversized_body(self) -> None:
        import outlook_auth

        huge = b"{" + b"x" * (outlook_auth.read_http_body.__defaults__[0] + 1)
        with patch.object(outlook_auth.urllib.request, "urlopen", return_value=self._resp(huge)):
            with self.assertRaises(RuntimeError) as caught:
                outlook_auth._post("https://login.microsoftonline.com/common/oauth2/v2.0/token", {})
        self.assertIn("too large", str(caught.exception))

    def test_outlook_auth_rejects_oversized_error_body(self) -> None:
        import io
        import outlook_auth
        import urllib.error

        fp = io.BytesIO(b"x" * (outlook_auth.MAX_HTTP_ERROR + 1))
        err = urllib.error.HTTPError(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            400,
            "bad",
            hdrs=None,
            fp=fp,
        )
        with patch.object(outlook_auth.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as caught:
                outlook_auth._post("https://login.microsoftonline.com/common/oauth2/v2.0/token", {})
        self.assertIn("too large", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
