# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HadarTracker scrapes a specific trader's ("Hadar", `UserId=5609`) public forum posts on the
Israeli trading site Sponser (sponser.co.il), stores them in SQLite, and sends Telegram
notifications for new posts (subject, ticker tags, reply/thread context, body, and any attached
picture). Phase 1 (scrape → store → notify) and Phase 2 (LLM trade-signal classification via
OpenRouter, `hadar_tracker/signal.py`) are both live. A structural notification filter
(`hadar_tracker/notify_filter.py`) sits on top of both, validated against a manual-labeling pass
over 90 days of real posts (see `docs/superpowers/specs/` for that analysis): a post Hadar starts
himself always notifies; a reply elsewhere with an image or ticker tag always notifies; everything
else defers to the LLM signal, fail-open (sends) if classification is unavailable. Notifications
are also gated to 09:30-17:30 Israel time — a post found outside that window is held and flushed,
labeled "🌙 After Hours", on the next run inside the window (see `check.py`'s `_flush_pending`).

The full design history is in `docs/superpowers/specs/2026-07-21-phase1-tracker-design.md`
(the authoritative spec — read it before making architectural changes) and
`docs/superpowers/plans/2026-07-21-phase1-tracker-v2.md` (the implementation plan most of the
current code was built from).

## Commands

```bash
# Setup (Windows; use ./.venv/bin/... on Linux/the VPS)
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt

# Run all tests
./.venv/Scripts/python.exe -m pytest -v

# Run a single test file / test
./.venv/Scripts/python.exe -m pytest tests/test_parse.py -v
./.venv/Scripts/python.exe -m pytest tests/test_parse.py::test_parse_filters_to_hadar_only -v

# Run the live incremental check (requires .env with Telegram credentials)
./.venv/Scripts/python.exe -m hadar_tracker.check

# Run historical backfill (does NOT require Telegram credentials to function,
# but load_config() still requires them to be set — see Config below)
./.venv/Scripts/python.exe -m hadar_tracker.backfill --days 30
```

There is no build step, linter, or type checker configured — `pytest` is the only tool in the
loop. Tests are configured via `pyproject.toml` (`pythonpath = ["."]`, `testpaths = ["tests"]`),
so they run from the repo root without installing the package.

## Architecture

**No browser, ever.** The project scrapes two plain-HTTP JSON endpoints directly — there is no
Playwright/Selenium/BeautifulSoup anywhere in the application path. This was a deliberate,
hard-won pivot: headless-browser automation gets blocked by the site's Cloudflare WAF
(`navigator.webdriver`/headless-UA detection), but a plain `requests` call to the *same*
endpoints the page's own JS calls is not blocked. `scripts/inspect_page.py` and
`tests/fixtures/user_messages_page1.html` are leftover artifacts from the original
(abandoned) Playwright investigation — harmless, but not part of the running app.

**Two distinct data sources, both plain HTTP, both handled by `parse_posts`:**

- `hadar_tracker/scraper/client.py` — `POST Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx`
  (`ForumId`, `IsFull`, `UserId`, `m` form fields). This is the **per-user "recent activity"**
  feed used for live tracking (`check.py`). It only covers roughly the last day of activity —
  it is NOT paginated and cannot reach older history.
- `hadar_tracker/scraper/history.py` — `GET Handlers/HD_STREAM_FORUM_MESSAGES.ashx?f={forum}&p={page}`.
  This is the **general forum listing** (all users, not just Hadar), and it IS genuinely paginated:
  page 1 is the forum's oldest messages (~2005), ascending toward the present at `page_id =
  NumberOfPages`. `page_id=0` is a special "recently bumped" bucket (mixed dates — threads
  resurface when they get new replies) and should only be used to read `Info.NumberOfPages`
  and as a bonus coverage pass, never for date-ordering logic. This is what `backfill.py` walks
  backward through, filtering to `UserId == 5609` via the same `parse_posts` used everywhere
  else, to pull historical data the per-user endpoint can't reach.

Both endpoints return the same JSON item shape (`MsgId`, `User.UserId`, `Level`, `L1`, `subject`,
`Msg`, `Tags`, `DateCreated`, `HasImages`, `MsgFileName`), which is why one parser
(`hadar_tracker/scraper/parse.py::parse_posts`) serves both call sites. `Tags` entries are
`{"Name": "תדיראן גרופ", "Symbol": "258012"}` — `Symbol` is Sponser's internal numeric security id,
not a ticker, so on its own it's meaningless to a reader; `extract_tags` renders `"{Name}
({Symbol})"` so both are visible.

**Thread/reply resolution:** each item has `Level` (1 = root post, 2+ = a reply/comment) and `L1`
(a thread-group id — *not* a `MsgId`). `parse_posts` resolves what a reply is commenting on by
scanning the *entire* payload (not just the user-filtered subset) for the `Level == 1` sibling
sharing the same `L1`, since the thread's root post can belong to a completely different user
than the one being filtered for. Any change to this filtering logic must preserve that
full-payload scan — narrowing it to already-filtered items silently breaks reply context for
threads Hadar didn't start (see `tests/test_parse.py::test_parse_reply_resolves_root_subject_when_root_is_another_user`,
which exists specifically to catch that regression).

**Two independent image sources**, both plain HTTP downloads via `hadar_tracker/images.py`
(no browser/screenshot needed for either):
- Manually attached pictures: `HasImages`/`MsgFileName` → `https://www.sponser.co.il/ForumFiles/{MsgFileName}`.
- Ticker hover-popover charts (`chart.bursagraph.co.il`, driven by `Tags`/`data-symbol`) are
  deliberately NOT fetched — out of scope; only the ticker symbols are stored/displayed.

`images.download_image` sanitizes `msg_file_name` to a bare basename before building the local
write path (the value is externally-sourced/scraped data) — the remote fetch URL still uses the
original filename. Don't remove this sanitization; it closes a path-traversal gap found during
review.

**Module map** (`hadar_tracker/`):
- `models.py` — the `Post` dataclass, the one shared shape passed scraper → check/backfill → db/notifier.
- `config.py` — `Config`/`load_config()`, reads env vars (see `.env.example`); raises `ConfigError`
  loudly if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are missing, even for code paths (like
  backfill) that don't use Telegram — construct a `Config` directly in a script if you need to
  bypass this for a Telegram-free run. `OPENROUTER_MODEL` defaults to `anthropic/claude-sonnet-4.5`
  in code, but this deployment's `.env` overrides it to `deepseek/deepseek-v4-flash`.
  `telegram_extra_chat_ids` (from the comma-separated `TELEGRAM_EXTRA_CHAT_IDS`) are additional
  recipients for POST notifications only — see `check.py`'s `_notify_chat_ids`; error alerts
  always go to `telegram_chat_id` alone, never these.
- `db.py` — all SQLite access (single-writer, single-file). `insert_post` is `INSERT OR IGNORE`
  returning whether a row was actually new — this is what makes both `check.py` and `backfill.py`
  idempotent/resumable; there is no separate upsert path. The `notified` column (default 1) backs
  the trading-hours hold queue: a row inserted with `notified=False` is picked up by
  `fetch_pending_posts`/`mark_notified` on a later run once the market-hours window reopens. A
  small `meta` key-value table (`get_meta`/`set_meta`) holds run-level state that isn't a post —
  currently just `notify_filter`'s off-hours-check throttle timestamp.
- `scraper/client.py`, `scraper/history.py`, `scraper/parse.py` — see Architecture above.
- `images.py` — attachment download.
- `notify_filter.py` — decides whether/when a post actually reaches Telegram.
  `classify_bucket` sorts a post into own-thread-root / reply-to-his-own-thread /
  reply-to-someone-else's-thread (from `thread_transcript` when the root was in the same scrape
  payload, else a DB lookup via `db.thread_has_root`). `should_notify` gates on that bucket plus
  the LLM `Signal` — an own root always passes, a reply with an image or ticker tag always passes,
  everything else defers to the signal and fails open (sends) if classification didn't run.
  `is_after_hours`/`is_market_hours_now` implement the 09:30-17:30 Israel-time window: the former
  is a pure per-post label (posted_at is already naive Israel-local, see `scraper/parse.py`), the
  latter reads the real clock via `zoneinfo` (`tzdata` is a hard dependency — Windows has no system
  IANA tz database) and drives the hold/flush decision in `check.py`. `should_run_offhours_check`/
  `mark_offhours_check_ran` (backed by `db.get_meta`/`set_meta`) throttle off-hours work to once per
  `OFFHOURS_CHECK_INTERVAL_SECONDS` (1 hour) — see check.py's `run_check` for why this lives in code
  rather than a second cron/systemd schedule.
- `notifier.py` — Telegram sending, via HTML parse mode (required for the bold labels below).
  `format_message` (pure) builds the text layout (🌙 after-hours label → **הגיב ל:** reply-context
  (bold, when present) → **כותרת:** title (bold) → blank line → **תוכן:** label → body → blank
  line → 🏷 tags → 🤖 signal section). Every section is explicitly labeled in Hebrew rather than
  left positionally implicit, and reply-context comes BEFORE title — you read what a post is
  responding to before its own title. Tags and the signal deliberately sit in a footer AFTER body,
  not between title and reply-context — a tag can be a real stock that isn't actually what's being
  discussed (a real live example: an idiom containing "שמיים" (heaven) tagged an unrelated stock
  by that name), and having it sit in the middle broke up the reply-context→title→body reading
  flow right when a reader needs that context most. Signal conviction renders as a ball emoji
  (🟢/🟡/🔴 for high/medium/low), not text. `_replace_emoji_codes` converts
  the forum's raw `|NN|` smiley placeholders (the site resolves these client-side via a
  `var ICONS` table to `<img>` tags — `https://www.sponser.co.il/Images/{filename}` — that the
  JSON API never does) into real emoji, hand-mapped from the actual smiley images; unrecognized
  codes are dropped rather than left as literal `|NN|` text. Every message ends with an invisible
  trailing line (`_RLM`, a zero-width Right-to-Left Mark) — found via live debugging that Telegram
  misrenders a short Hebrew line ending in Latin digits (e.g. a stop-loss price like "סטופ 4230")
  as left-aligned specifically when it's the message's literal last line; two bidi-control-character
  approaches (leading RLM, then full RLE...PDF embedding) were tried first and had zero effect —
  the real fix has nothing to do with direction marks, just ensuring the body is never terminal.
  In practice a real `thread_url` (see `build_thread_url` — Sponser's own permalink pattern,
  `Forum.aspx?ForumId={forum_id}&MsgId={msg_id}`; note `PageId` must be omitted, it causes an
  infinite redirect loop) renders as a clickable "🔗 Link" line and does this job instead, since
  it's real useful content rather than an invisible character; `_RLM` is only the fallback when no
  `thread_url` is given. Dynamic content is HTML-escaped (`_esc`, which unescapes first — Sponser's
  raw text sometimes contains an already-literal entity like `&nbsp;`, and escaping that straight
  through would double-encode it into visible `&nbsp;` text) since the message is sent as HTML.
  `send_post`/`send_alert` are sync wrappers around `python-telegram-bot`'s async `Bot` API.
- `check.py` — the live incremental job. `process_new_posts` sends the Telegram notification
  **before** persisting to the DB (not the other way around) — if `send_post` raises, the post is
  deliberately left unmarked-as-seen so it's retried next run instead of the notification being
  silently and permanently lost. `_notify_chat_ids` fans a post notification out to
  `config.telegram_chat_id` plus every `telegram_extra_chat_ids` (deduplicated) — used both here
  and in `_flush_pending`; `run_check`'s error-alert path deliberately does NOT use this and only
  ever targets `telegram_chat_id`, so subscribing via an extra chat id gets Hadar's posts without
  also getting woken up by an admin-only scraper failure. A post that `should_notify` but arrives
  while `market_open` is False is held (`notified=False`) instead of sent; `_flush_pending` sends
  every held post, each labeled after-hours, at the start of the next run where the market is
  open. `run_check` computes
  `market_open` from `notify_filter.is_market_hours_now()` and wraps DB setup, the scrape call,
  *and* `process_new_posts` each in the same fail-loud contract (log + Telegram alert + non-zero
  exit) — this covers the whole run, not just the scrape step, since a Telegram/download error on a
  genuinely new post is the most likely real-world failure mode. When `market_open` is False,
  `run_check` also calls `notify_filter.should_run_offhours_check` right after DB setup and returns
  0 immediately (no scrape at all) unless an hour has passed since the last off-hours check — see
  "Timing/scheduling" below for why the interval itself lives here, not in the scheduler.
- `backfill.py` — walks `scraper/history.py` backward from the current page, stopping once a
  page's oldest item crosses the `--days` cutoff (default 30). Never sends Telegram notifications
  (it's a historical import, not a live alert stream — dumping months of backfilled posts as
  Telegram messages would be spam). Safe to interrupt and rerun.

**Testing discipline:** every test suite (`tests/test_*.py`) monkeypatches at the network/Telegram
boundary (`requests`, `notifier.Bot`, or the injected `download`/`send_post`/`fetch_page`
callables) — none hit the live site or Telegram. `tests/fixtures/sample_stream.json` is the
hand-authored payload shape used across parser/client/check tests; keep it in sync with the real
API shape if the site changes. `tests/test_check.py::test_run_check_end_to_end_through_real_parser`
is the one test that drives the real parser + real check pipeline together (only the HTTP/Telegram
boundary is faked) — it exists to catch cross-module shape mismatches that isolated unit tests
would miss.

**Deployment** (`deploy/`): target is a systemd timer (or cron) on an Oracle Cloud VPS running
`python -m hadar_tracker.check` every 10–15 minutes, **all day, unchanged** — the 09:30-17:30 gate
is enforced in code (`notify_filter`/`check.py`), not by narrowing the timer's schedule. The
scraper still needs to run continuously so the hold queue gets flushed promptly at the next
in-window run rather than sitting stale. See `deploy/README.md` for the full walkthrough.

**Timing/scheduling — where each interval actually lives:**
- **In-hours check interval** (how often `check.py` runs 09:30-17:30): purely a scheduler setting,
  not in the code at all. Edit `OnUnitActiveSec=` in `deploy/hadar-tracker.timer` (systemd) or the
  `*/N * * * *` in the cron line in `deploy/README.md`. Faster (e.g. every 1 min) means quicker
  Telegram alerts but ~10x more requests to Sponser's own server during its busiest hours — the
  project exists because their WAF already blocks bot-like traffic once (see Architecture above),
  so this is a real (if unquantified) risk, partially offset by `run_check`'s existing fail-loud
  alerting surfacing any scrape breakage immediately rather than silently.
- **Off-hours check interval** (17:30-09:30): deliberately NOT a second scheduler entry — the same
  timer/cron keeps firing on its normal in-hours cadence all day, and `notify_filter
  .OFFHOURS_CHECK_INTERVAL_SECONDS` (currently 3600 = 1 hour) makes `run_check` skip the actual
  scrape+process on every off-hours invocation except the first one per hour (see
  `should_run_offhours_check`/`mark_offhours_check_ran`, backed by `db`'s `meta` table). Change the
  cadence by editing that constant, not a schedule file.
