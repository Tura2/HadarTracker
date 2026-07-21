# HadarTracker — Phase 1 Design: Scrape → Store → Notify

**Date:** 2026-07-21
**Status:** Approved

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

Confirmed during scoping:
- The profile page is publicly viewable — no login required (to be confirmed once we're
  actually in the browser; if wrong, this is a small addition, not a redesign).
- Post content loads dynamically (JS/AJAX), not present in static HTML — requires a real
  browser to scrape, not plain HTTP + HTML parsing.
- Posts sometimes include embedded charts (e.g. from `chart.bursagraph.co.il`) that should be
  archived as images, since the live chart source can change after the fact.

## Goals

- Detect new posts from Hadar within ~10–15 minutes of them appearing.
- Store every post (text, timestamp, chart image if present) durably, deduplicated.
- Notify the user via Telegram for each new post (text + chart image if present).
- Support a decoupled, resumable backfill of his historical post archive (not required for
  initial launch, but required before Phase 2 analysis can begin).
- Run continuously on the user's Oracle Cloud VPS; built and tested locally first.

## Non-goals (Phase 1)

- No language/NLP analysis of post content — that's Phase 2.
- No multi-user support, no web dashboard/UI.
- No handling of any Sponser account other than passive, logged-out reading.

## Architecture

A single Python project with three pieces sharing one scraping engine:

```
hadar_tracker/
  scraper/         # Playwright-based extraction engine (shared core)
  backfill.py       # one-off/rerunnable historical crawl
  check.py          # cron-invoked incremental check
  notifier.py       # Telegram sending
  db.py             # SQLite access
  data/
    hadar.sqlite3
    charts/          # saved chart screenshots
```

### Scraping engine (`scraper/`)

- Uses Playwright (Python) to load the profile/forum page in a headless browser.
- Extracts, per post: a stable unique post identifier, timestamp, raw text, and whether a
  chart/image is attached (and if so, a selector/region to screenshot).
- Supports paging backward through history (used by both backfill and, if needed, catching up
  after downtime).
- First implementation task: open the page in a real (non-headless, for inspection) Playwright
  session and inspect the network tab / DOM to determine the actual mechanism used to load and
  paginate posts. This determines whether we can hit an underlying data endpoint directly
  (faster, more robust) or must drive the rendered DOM.

### `check.py` (incremental tracking — the cron job)

1. Load the newest post(s) via the scraper.
2. Diff against SQLite by post identifier.
3. For each new post: insert into DB, screenshot any attached chart to `data/charts/`, send a
   Telegram notification (text + image if present).
4. On failure (site unreachable, layout changed, etc.), log the error clearly and exit non-zero
   so cron/systemd logs capture it, AND send a Telegram alert ("scraper run failed: ...") so
   failures aren't silently missed.
5. Scheduled via cron/systemd timer on the VPS. Start at every 10–15 minutes; adjust once real
   posting cadence is known from backfilled data.

### `backfill.py` (historical crawl — decoupled, run on demand)

- Pages backward through Hadar's full post history via the same scraper engine.
- Upserts into the same `posts` table, skipping any post ID already present — safe to
  interrupt and rerun at any time.
- Not required before Phase 1 goes live; needed before Phase 2 (language analysis) begins,
  since that requires a real historical corpus.

### Storage (`db.py`, SQLite)

Single-file SQLite database on the VPS (single writer, no concurrent-access needs — fits this
scale; can graduate to Postgres later if the project ever becomes multi-user/multi-writer).

`posts` table:

| column | type | notes |
|---|---|---|
| post_id | TEXT, primary key | stable identifier scraped from the page |
| posted_at | TEXT (ISO timestamp) | when Hadar posted it |
| raw_text | TEXT | the post content, as scraped |
| chart_image_path | TEXT, nullable | path under `data/charts/` if a chart was attached |
| scraped_at | TEXT (ISO timestamp) | when *we* first saw it |

### Notification (`notifier.py`)

- A Telegram bot (via `python-telegram-bot`), sending to the user's personal chat.
- One message per new post: raw text, plus the chart image as an attachment if present.
- Also used to send scrape-failure alerts (see `check.py` above).

## Data flow

```
cron (every N min) → check.py
  → scraper loads latest post(s)
  → diff against SQLite by post_id
  → new rows inserted; chart screenshotted to disk if present
  → Telegram message sent per new post
  → on failure: log + Telegram alert
```

```
backfill.py (run manually, whenever)
  → scraper pages backward through full history
  → each post upserted into same SQLite table (idempotent, resumable)
```

## Error handling

- Every `check.py` run either succeeds cleanly or fails loudly (non-zero exit + log + Telegram
  alert) — no silent failures.
- Backfill is idempotent/resumable by design (upsert on post_id).
- If the page structure changes and parsing breaks, this should surface as a scrape failure
  (e.g. zero posts found where posts were expected), not as silently-empty results.

## Testing

- Unit tests for the parsing logic against saved HTML/DOM fixtures, independent of live network
  calls (so tests don't depend on Sponser being up or on rate limits).
- Manual smoke test against the live site before deploying each change to the VPS.

## Open items to resolve during implementation (not blockers)

1. The real mechanism the page uses to load/paginate posts (rendered DOM vs. an underlying data
   endpoint) — first thing to check once we're in a real browser session.
2. Confirm the public (logged-out) page truly shows everything needed; add login-handling only
   if this turns out to be false.
3. Real posting cadence, to tune the polling interval sensibly.
4. Whether Sponser has bot-detection/rate-limiting requiring more careful (slower, more
   "human") scraping — escalate to Scrapling's stealth fetcher only if plain Playwright gets
   blocked.

## Tooling decision (for reference)

Evaluated against Firecrawl, Browser Use, Crawl4AI, Scrapy, ScrapeGraphAI, Puppeteer, Crawlee,
Colly, and Scrapling. Chose **Playwright** as the core engine: full deterministic control,
screenshot support, network inspection, mature ecosystem. **Scrapling** held in reserve as a
fallback (adaptive selectors + stealth fetching) if Sponser proves hostile to plain headless
browsing. Everything else was a mismatch — either wrong language (Puppeteer, Colly), wrong
shape (Firecrawl/Crawl4AI are built for LLM-ready bulk content extraction, not precise
structured field extraction), or wrong determinism/scale profile (Browser Use, ScrapeGraphAI
are LLM-agent-driven and non-deterministic; Scrapy/Crawlee are built for large multi-site
crawls with queues/proxies we don't need for monitoring one profile page).
