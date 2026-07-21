# HadarTracker — Phase 1 Design: Scrape → Store → Notify

**Date:** 2026-07-21
**Status:** Approved (revised same-day after live investigation — see Revision History)

## Revision History

- **v1 (approved):** Assumed post content required a headless-browser (Playwright) scrape of
  rendered HTML.
- **v2 (this version):** Superseded by a live investigation (see "Confirmed during scoping"
  below). The site's own page loads posts via a plain JSON AJAX endpoint, and that endpoint is
  **not** subject to the bot-detection block that headless Playwright hits. This removes the
  browser entirely from the scraping path: Phase 1 is now a plain-HTTP JSON client, not a
  browser-automation project. This revision updates Architecture, the data model, and
  Notification format accordingly. Goals, Non-goals, and error-handling philosophy are
  unchanged.

## Context

Hadar is a professional trader active on the Israeli market whose forum posts on Sponser
(https://www.sponser.co.il/) are well-regarded for accuracy. His profile/message feed:
`https://www.sponser.co.il/ForumViewUserMessages.aspx?UserId=5609&ForumId=1&IsFull=1`

Goal of the overall project: track his posts, get notified when he posts, and eventually
understand his trader-specific language well enough to classify which posts represent real
trading actions vs. noise.

This spec covers **Phase 1 only**: reliably scraping his posts, storing them, and notifying
the user (Telegram) when he posts something new. Phase 2 (language/action analysis) is a
separate, later spec, to be designed once we have real historical post data to work against.

Confirmed during live investigation against the real site:

- **No login required.** The feed is fully readable anonymously — full post bodies, no
  truncation, no session/cookies needed.
- **Posts are loaded via a plain JSON AJAX endpoint**, not embedded in static HTML:
  `POST https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx`
  with form body `ForumId=1&IsFull=1&UserId=5609&m=0`. Hitting this endpoint directly with an
  ordinary HTTP client returns the same data the page itself renders — no HTML parsing needed.
- **Headless Playwright is blocked by Cloudflare (HTTP 403)** — `navigator.webdriver` and the
  `HeadlessChrome` UA string are detected. A plain HTTP request to the *same* JSON endpoint,
  from the same network, is **not** blocked (HTTP 200), because it carries none of those
  automation fingerprints. Conclusion: **do not use a browser at all** for scraping — it is
  both unnecessary and actively the thing that gets blocked.
- **This endpoint returns recent activity, not full history.** One live call returned 81 of
  Hadar's own posts spanning roughly 24 hours (2026-07-20 10:32 to 2026-07-21 14:03), with the
  server reporting `NumberOfPages: 0` / `IsMoreMsg: 0` (i.e., "this is everything," for the
  time window it covers) — it is **not** his multi-year archive. A different mechanism will be
  needed for full historical backfill; see "Open items."
- **Two independent image sources exist**, both plain HTTP downloads (no browser/screenshot
  needed for either):
  - **Manually attached pictures** ("the pictures he uploads"): JSON fields `HasImages` +
    `MsgFileName` (e.g. `c310bc13-....gif`); download from
    `https://www.sponser.co.il/ForumFiles/{MsgFileName}`. Confirmed working — downloaded a real
    Bursagraph-branded Tel Aviv-35 chart he'd attached to a comment.
  - **Ticker hover-popover charts**: a post can tag stock tickers (`Tags`), each rendered as a
    `data-symbol`-carrying link; hovering builds a `chart.bursagraph.co.il/graphSponser.php?s=
    {symbol}&...` URL client-side. This is a live, symbol-driven chart, not something Hadar
    uploaded — Phase 1 uses the ticker **symbols** (for message formatting/storage) but does
    not fetch this chart image (no request for it; can be added later if wanted).
- **Posts can be replies/comments, not just root posts.** Each item has `Level` (1 = root post,
  2+ = a reply/comment) and `L1` (a thread-group id — not a MsgId). Items sharing the same `L1`
  belong to one thread; the item with `Level: 1` in that group is the thread's root. Since a
  single API response already contains every item in the batch (root and replies alike, no
  separate "tree" fetch needed), resolving "what is Hadar commenting on" is a local lookup
  within the same response: group by `L1`, find the `Level: 1` sibling. This works whether the
  root post is his own or someone else's.

## Goals

- Detect new posts from Hadar within ~10–15 minutes of them appearing.
- Store every post (subject, body, timestamp, tags/tickers, thread context, attached image if
  present) durably, deduplicated by `MsgId`.
- Notify the user via Telegram for each new post: text (including tickers and, if it's a
  reply, what it's replying to) plus the attached image if present.
- Support a decoupled, resumable backfill of his historical post archive (not required for
  initial launch, but required before Phase 2 analysis can begin). **Open item:** the mechanism
  for this is not yet known — see "Open items."
- Run continuously on the user's Oracle Cloud VPS; built and tested locally first.

## Non-goals (Phase 1)

- No language/NLP analysis of post content — that's Phase 2.
- No multi-user support, no web dashboard/UI.
- No handling of any Sponser account other than passive, logged-out reading.
- No fetching of the live ticker hover-popover chart image (Phase 1 stores the ticker symbols
  only; the chart itself is a nice-to-have, not requested).

## Architecture

A single Python project with three pieces sharing one HTTP-based scraping client (**no browser,
no Playwright, no HTML parsing** — this is a plain JSON API client):

```text
hadar_tracker/
  scraper/         # plain-HTTP JSON client (shared core) — requests, no browser
  backfill.py       # one-off/rerunnable historical crawl (mechanism: open item)
  check.py          # cron-invoked incremental check
  notifier.py       # Telegram sending
  db.py             # SQLite access
  data/
    hadar.sqlite3
    images/          # downloaded attached pictures
```

### Scraping client (`scraper/`)

- Issues a plain HTTP POST (e.g. via the `requests` library) to
  `https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx` with body
  `ForumId=1&IsFull=1&UserId=5609&m=0`, using an ordinary desktop User-Agent (not spoofing
  anything exotic — this is the same request the page's own JS makes).
- Parses the JSON response's `Data` array; filters to `User.UserId == 5609` (Hadar's own posts,
  root or comment).
- For each matching item, extracts: `MsgId`, `DateCreated`, `Level`, `L1`, `subject`, `Msg`
  (body), `Tags` (tickers), `HasImages`, `MsgFileName`.
- Resolves thread context: for `Level > 1` items, finds the sibling in the same response with
  matching `L1` and `Level == 1`, and records its subject as the reply's context.
- No pagination logic for this endpoint — one call returns its complete result set for the
  window it covers (`IsMoreMsg: 0`). The historical-backfill mechanism is a separate open item,
  not paging through this endpoint.

### `check.py` (incremental tracking — the cron job)

1. Call the scraper client for the latest batch.
2. Diff against SQLite by `MsgId`.
3. For each new post: insert into DB; if `HasImages`, download the attachment to
   `data/images/` from `https://www.sponser.co.il/ForumFiles/{MsgFileName}`; send a Telegram
   notification (formatted text + image if present).
4. On failure (site unreachable, response shape changed, etc.), log the error clearly and exit
   non-zero so cron/systemd logs capture it, AND send a Telegram alert
   ("scraper run failed: ...") so failures aren't silently missed.
5. Scheduled via cron/systemd timer on the VPS. Start at every 10–15 minutes; adjust once real
   posting cadence is known from backfilled data.

### `backfill.py` (historical crawl — decoupled, run on demand)

- Same upsert-by-`MsgId` idempotent/resumable contract as before.
- **Mechanism not yet determined** — the live endpoint used for `check.py` only covers ~1 day
  of activity, not Hadar's full archive back to 2005. Before this task is implemented, a
  follow-up investigation is needed (e.g., does the `m` parameter accept a cursor/offset? Is
  there a separate paginated per-user history endpoint, distinct from this "real-time" one,
  similar to how the general forum listing uses `PageId`?). Not required before Phase 1 goes
  live; required before Phase 2 (language analysis) begins.

### Storage (`db.py`, SQLite)

Single-file SQLite database on the VPS (single writer, no concurrent-access needs).

`posts` table:

| column | type | notes |
|---|---|---|
| msg_id | TEXT, primary key | `MsgId` from the JSON |
| posted_at | TEXT (ISO timestamp) | parsed from `DateCreated` (`DD/MM/YY \| HH:MM`, Israel local time) |
| level | INTEGER | 1 = root post, 2+ = reply/comment |
| thread_group | TEXT | `L1` — groups posts/replies in the same thread |
| root_subject | TEXT, nullable | resolved subject of the thread's `Level: 1` post, when this row is itself `Level > 1` |
| subject | TEXT | `subject` field |
| body | TEXT | `Msg` field |
| tags | TEXT | stock tickers mentioned, stored as a delimited/JSON list |
| image_file_name | TEXT, nullable | `MsgFileName`, when `HasImages` is true |
| image_local_path | TEXT, nullable | path under `data/images/` once downloaded |
| scraped_at | TEXT (ISO timestamp) | when *we* first saw it |

### Notification (`notifier.py`)

- A Telegram bot (via `python-telegram-bot`), sending to the user's personal chat.
- One message per new post, formatted to surface the parts that matter for a trading feed:
  - Subject line
  - Tickers/tags, if any (e.g. `🏷 TEVA, ICL`) — the user specifically wants tickers visible in
    the Telegram message, not just stored
  - Thread context line if this is a reply (`↩️ Replying to: <root_subject>`)
  - Body text
  - The attached picture, sent as a photo (downloaded from `ForumFiles`), if `HasImages` is true
    — the user specifically wants to see uploaded pictures in Telegram, not just a flag that one
    exists
- Also used to send scrape-failure alerts (same as `check.py` above).

## Data flow

```text
cron (every N min) → check.py
  → scraper POSTs to HD_STREAM_FORUM_USER_MESSAGES.ashx, filters to UserId 5609
  → diff against SQLite by msg_id
  → new rows inserted; attached image downloaded to disk if HasImages
  → Telegram message sent per new post (subject, tags, thread context, body, image)
  → on failure: log + Telegram alert
```

```text
backfill.py (run manually, whenever; mechanism TBD — see Open items)
  → crawls historical posts via whatever mechanism the follow-up investigation finds
  → each post upserted into same SQLite table (idempotent, resumable)
```

## Error handling

- Every `check.py` run either succeeds cleanly or fails loudly (non-zero exit + log + Telegram
  alert) — no silent failures.
- Backfill is idempotent/resumable by design (upsert on `msg_id`).
- If the API response shape changes (missing expected keys, empty `Data` where posts were
  expected), this should surface as a scrape failure, not a silently-empty success.

## Testing

- Unit tests for the JSON-parsing/filtering/thread-resolution logic against saved sample JSON
  fixtures, independent of live network calls (so tests don't depend on Sponser being up).
- Manual smoke test against the live endpoint before deploying each change to the VPS.

## Open items to resolve during implementation (not blockers for Phase 1 launch)

1. **Backfill mechanism.** The live endpoint only covers ~1 day of activity. Needs a follow-up
   investigation into how to reach older history (cursor via `m`? a separate paginated
   endpoint?) before `backfill.py` can be built for real.
2. Real posting cadence beyond the ~1 day sample, to tune the polling interval sensibly.
3. Whether the `.ashx` endpoint itself has any rate-limiting under sustained polling (the single
   test call was not blocked, but repeated polling behavior over time is unverified).

## Tooling decision (for reference)

Originally evaluated Firecrawl, Browser Use, Crawl4AI, Scrapy, ScrapeGraphAI, Puppeteer,
Crawlee, Colly, Playwright, and Scrapling, and chose Playwright as a headless-browser engine.
**Live investigation overturned that choice**: the site's own page is powered by a plain JSON
AJAX endpoint, and hitting that endpoint directly with a plain HTTP client (Python `requests`)
works and is not blocked, while headless Playwright *is* blocked (Cloudflare bot-management
detects `navigator.webdriver`/headless UA signatures). Net result: **no browser library is
needed at all** — Phase 1 is a plain HTTP JSON client. This also drops the BeautifulSoup4
dependency (no HTML to parse) and removes the Scrapling-as-fallback contingency (nothing to
fall back from, since there's no browser in the path to begin with).
