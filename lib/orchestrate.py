"""Fan out list/read across configured accounts and merge unread mail."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import (
    FETCH_CAP,
    account_error,
    decode_id,
    die,
    emit,
    encode_id,
    load_accounts,
    max_messages,
    provider_path,
    secret_path,
)

LIST_TIMEOUT = 45
READ_ALL_TIMEOUT = 120
PREVIEW_TIMEOUT = 45


def _run_provider(account: dict, args: list[str], timeout: int = LIST_TIMEOUT) -> dict:
    provider = account["provider"]
    env = os.environ.copy()
    env["YOU_GOT_MAIL_ACCOUNT_ID"] = account["id"]
    env["YOU_GOT_MAIL_ACCOUNT_JSON"] = json.dumps(account, separators=(",", ":"))
    env["YOU_GOT_MAIL_SECRET_FILE"] = str(secret_path(account["id"]))
    env["YOU_GOT_MAIL_MAX"] = os.environ.get("YOU_GOT_MAIL_MAX", str(max_messages()))
    env["YOU_GOT_MAIL_FETCH"] = os.environ.get("YOU_GOT_MAIL_FETCH", env["YOU_GOT_MAIL_MAX"])
    try:
        proc = subprocess.run(
            [str(provider_path(provider)), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{account['id']}: timed out"}
    except OSError as exc:
        return {"ok": False, "error": f"{account['id']}: {exc}"}
    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip()
        return {"ok": False, "error": f"{account['id']}: {err or 'no output'}"}
    try:
        payload = json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": f"{account['id']}: provider returned invalid JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": f"{account['id']}: provider returned invalid JSON"}
    return payload


def _tag_messages(account: dict, payload: dict) -> list[dict]:
    label = str(account.get("label") or account["id"])
    tagged = []
    for msg in payload.get("messages") or []:
        if not isinstance(msg, dict) or not msg.get("id"):
            continue
        item = dict(msg)
        item["id"] = encode_id(account["id"], str(msg["id"]))
        item["account"] = label
        item["previewAvailable"] = account.get("provider") == "gmail"
        tagged.append(item)
    return tagged


def cmd_list(page_token: str) -> None:
    accounts = load_accounts()
    page = 0
    if page_token:
        try:
            page = int(page_token)
        except ValueError:
            page = 0
        if page < 0:
            page = 0
    per = max_messages()
    start = page
    needed = start + per
    fetch = str(min(FETCH_CAP, max(per, needed)))
    os.environ["YOU_GOT_MAIL_FETCH"] = fetch

    errors = []
    merged: list[dict] = []
    unread = 0
    emails = []
    payloads: dict[str, dict] = {}

    def work(acc: dict) -> tuple[dict, dict]:
        return acc, _run_provider(acc, ["list", "--limit", fetch])

    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
        futures = [pool.submit(work, acc) for acc in accounts]
        for fut in as_completed(futures):
            acc, payload = fut.result()
            if not payload.get("ok"):
                errors.append(account_error(acc, str(payload.get("error") or "failed")))
                continue
            payloads[acc["id"]] = payload
            unread += int(payload.get("unread") or 0)
            if payload.get("email"):
                emails.append(str(payload["email"]))
            merged.extend(_tag_messages(acc, payload))

    if not payloads and errors:
        die(errors[0] if len(errors) == 1 else "all accounts failed: " + "; ".join(errors))

    merged.sort(key=lambda m: int(m.get("ts") or 0), reverse=True)
    chunk = merged[start : start + per]
    # A message in the global top N must be in each account's top N, so
    # fetching `start + per` from every provider is enough for this page.
    # Do not offer a page past FETCH_CAP — that offset would be empty.
    next_start = start + per
    capped_total = min(max(len(merged), unread), FETCH_CAP)
    next_page = str(next_start) if next_start < capped_total else ""

    inboxes = []
    for acc in accounts:
        payload = payloads.get(acc["id"])
        if not payload:
            continue
        inboxes.append(
            {
                "account": str(acc.get("label") or acc["id"]),
                "unread": int(payload.get("unread") or 0),
                "searchUrl": str(payload.get("searchUrl") or ""),
            }
        )

    email = emails[0] if len(emails) == 1 else ""
    search_url = ""
    if len(accounts) == 1 and inboxes:
        search_url = str(inboxes[0].get("searchUrl") or "")

    out = {
        "ok": True,
        "email": email,
        "unread": unread,
        "searchUrl": search_url,
        "inboxes": inboxes,
        "nextPage": next_page,
        "thisPage": str(start),
        "accountCount": len(accounts),
        "messages": chunk,
    }
    if errors:
        out["warning"] = "; ".join(errors)
    emit(out)


def cmd_read(opaque: str) -> None:
    account_id, local_id = decode_id(opaque)
    accounts = {a["id"]: a for a in load_accounts()}
    acc = accounts.get(account_id)
    if not acc:
        die("unknown account")
    payload = _run_provider(acc, ["read", local_id])
    if not payload.get("ok"):
        die(str(payload.get("error") or "could not mark as read"))
    emit({"ok": True})


def cmd_preview(opaque: str, *, remote: bool = False) -> None:
    account_id, local_id = decode_id(opaque)
    accounts = {a["id"]: a for a in load_accounts()}
    acc = accounts.get(account_id)
    if not acc:
        die("unknown account")
    if acc.get("provider") != "gmail":
        die("in-panel preview is currently available for Gmail")
    args = ["preview", local_id]
    if remote:
        args.append("--remote")
    payload = _run_provider(acc, args, timeout=PREVIEW_TIMEOUT)
    if not payload.get("ok"):
        die(str(payload.get("error") or "could not load message"))
    payload["id"] = opaque
    emit(payload)


def cmd_read_all() -> None:
    accounts = load_accounts()
    errors: list[str] = []
    marked = 0
    succeeded = 0

    def work(acc: dict) -> tuple[dict, dict]:
        return acc, _run_provider(acc, ["read-all"], timeout=READ_ALL_TIMEOUT)

    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as pool:
        futures = [pool.submit(work, acc) for acc in accounts]
        for fut in as_completed(futures):
            acc, payload = fut.result()
            marked += int(payload.get("marked") or 0)
            if payload.get("ok"):
                succeeded += 1
                continue
            errors.append(account_error(acc, str(payload.get("error") or "failed")))

    if succeeded == 0:
        err = errors[0] if len(errors) == 1 else "all accounts failed: " + "; ".join(errors)
        emit({"ok": False, "error": err, "marked": marked})
        return

    out: dict = {"ok": True, "marked": marked}
    if errors:
        out["warning"] = "; ".join(errors)
    emit(out)
