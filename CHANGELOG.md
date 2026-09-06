# Changelog

Versions match `manifest.json`. Git tags are created at release time.

## 2.7.2

- Wide Gmail layouts are captured beyond the normal 720-pixel canvas and can
  be panned horizontally without shrinking or clipping their content.
- Preview rendering retries transient browser failures up to three times. The
  panel also retries failed requests/image decodes and offers click-to-retry.
- Opted-in remote images load eagerly, including `<picture>/<source>` and
  protocol-relative image URLs, before the inert preview is captured. A clear
  in-panel control replaces the easy-to-miss icon-only prompt.

## 2.7.1

- Gmail previews are cropped to the message's visible height instead of being
  placed on a fixed paper-sized page. The panel now hugs short messages and
  scrolls inside the available screen height for long ones.
- The browser-rendered preview stays inert and unread-safe; only its display
  format changed from PDF to PNG.

## 2.7.0

Gmail messages can now be read inside the panel without changing their unread
state.

- Clicking a Gmail row fetches the RFC 822 message with the read-only Gmail
  `messages.get` endpoint and morphs the panel into a larger detail view.
- HTML, plain text, tables, and inline CID images are rendered by a sandboxed
  headless Chromium/Brave process into an inert PDF that Qt displays in the
  panel. Scripts and active content are stripped; remote resources are opt-in.
- Back, mark-read, open-in-Gmail, and load-images actions have mouse and
  keyboard controls. Other providers retain their browser behavior.
- `you-got-mail preview <id>` exposes the same unread-safe provider contract.

## 2.6.0

Expired mail logins are a warning, not a dead widget, and the panel
tells you the terminal command to sign in again.

- `list` stays `ok` when at least one account answers, even if that
  mailbox is empty. A dead sibling is a `warning`, not a full outage.
- OAuth soup (`invalid_grant`, revoked tokens, HTTP 401) maps to
  `{id}: {provider} sign-in expired. In a terminal: …`.
- `you-got-mail accounts login [id]` re-authenticates in place.
- Gmail keeps `gws` stderr instead of discarding it; Outlook serialises
  token refresh with a lock file so two `list` calls cannot rotate the
  refresh token out from under each other.
- Panel error banner wraps; the empty state no longer repeats the dump.
- Docs: Google OAuth clients in Testing revoke refresh tokens after
  7 days. Publish the Desktop client to Production for personal use.

## 2.5.1

- README: `omarchy plugin update` shows a diff (page, then `q` to leave
  the pager) before confirming; `--yes` skips that review.
- Marketplace and widget copy name Gmail, Outlook, Fastmail, IMAP, and
  HEY.

## 2.5.0

IMAP folder discovery follows SPECIAL-USE attributes, not only English
names, and the panel can mark one row as read from the keyboard.

- IMAP skips `\All`, `\Archive`, `\Sent`, `\Trash`, `\Drafts`, `\Junk`,
  `\Flagged`, and `\Important` on the LIST flag list, then still filters
  English folder names for servers that omit SPECIAL-USE.
- IMAP sockets time out after 30s so a hung login fails in the provider
  instead of eating the orchestrator's 45s budget.
- Optional `folders` on an IMAP account is an allow-list: no LIST, no skip
  filters. Edit `accounts.json`; the add wizard is unchanged.
- Panel: `a` marks the cursor row as read without opening it. `A` and the
  header envelope keep two-press mark-all.

## 2.4.2

- Local config, account, secret, and Outlook-cache reads open the file
  once with `O_NOFOLLOW|O_NONBLOCK`, validate a user-owned regular file
  on that descriptor, and cap the read at 64KiB before decoding.

## 2.4.1

- Opening the panel no longer paints the mailbox with `activeColor`
  (theme urgent/red). The icon stays on the bar foreground like other
  widgets; the shell still marks which panel is open.

## 2.4.0

Unread mail is information, not an alarm. The bar count no longer uses
the urgent/red active colour, and the panel can mark every unread
message as read without opening each row.

- Bar badge and mailbox flag use the bar foreground instead of
  `activeColor` (theme red). The mailbox body still turns active only
  while the panel is open.
- `you-got-mail read-all` fans out to every account. Providers snapshot
  matching unread ids first, then mark them with the same skip rules as
  `list`.
- Panel: envelope action and `a` arm a two-click confirm, then parse the
  JSON result. Partial write failures stay visible after the following
  refresh.
- Bound remote HTTP bodies before decode, and write secrets/cache through
  exclusive same-directory temp files with mode 600, fsync, and atomic
  replace.

## 2.3.0

Unread totals, merged paging, widget settings, and the provider contract
are no longer papered over by a single page of rows.

- Fetch enough provider rows for the requested merged offset (capped at
  200) instead of truncating each account to one page.
- Outlook unread uses folder `unreadItemCount`; HEY uses envelope
  `unseen_count` or extra unseen pages; Gmail counts matching message
  ids (Gmail's `resultSizeEstimate` is a coarse bucket, often 201).
- Surface a partial-failure warning when some accounts succeed.
- Fastmail `read` fails unless the id is in `updated` and not in
  `notUpdated`.
- One secret loader: owner, mode 600, parent 700, no symlinks.
- Outlook access tokens are cached until near expiry; folder and profile
  metadata are reused for six hours.
- Panel page size (`max`) and refresh interval are inline widget
  settings. Keyboard: `i` opens unread inboxes, `Tab` switches panels.
  Bar tooltip and capped chips.
- HTTPS install URL, update command, and this changelog.
- Contract tests and GitHub Actions CI (mocked; no live mailboxes).
- Gmail setup documents the OAuth client `gws` now requires, and
  `GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file` so the bar can read the token.
- Bar mailbox uses Omarchy's adaptive bar colors and a stroked rural
  silhouette so it stays visible on transparent bars and mixed wallpapers.

## 2.2.4

Last release before the contract review. Unread pile across Gmail,
Outlook, Fastmail, IMAP, and HEY.
