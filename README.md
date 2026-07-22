<p align="center">
  <img src="assets/sponser_bot_icon.png" alt="HadarTracker" width="120">
</p>

<h1 align="center">HadarTracker</h1>

<p align="center">
  Tracks one trader's forum posts on <a href="https://www.sponser.co.il">Sponser</a> and turns them into filtered, LLM-classified Telegram alerts.
</p>

---

## What it does

HadarTracker watches a specific trader's ("Hadar") public forum posts, stores them in SQLite,
and sends a Telegram notification for the ones that actually matter — not every single post.

- **Scrapes** the forum's own JSON endpoints directly (no browser, no Playwright — see
  [CLAUDE.md](CLAUDE.md) for why that pivot happened).
- **Classifies** each post with an LLM (via OpenRouter) into a structured trade signal —
  action, ticker, conviction — routing text-only posts to a fast text model and posts with an
  attached chart to a vision-capable model.
- **Filters** what actually reaches Telegram: a thread he started always notifies; a reply
  elsewhere with a chart or ticker tag always notifies; everything else defers to the LLM
  signal and fails open (sends) if classification is unavailable.
- **Gates on trading hours** (09:30–17:30 Israel time): a post found outside that window is
  held and flushed — labeled 🌙 *After Hours* — the next time the window is open.
- **Formats for Telegram**: real emoji instead of the forum's raw `|NN|` smiley codes, a bold
  reply-context label, ticker names alongside their internal IDs, and a link back to the
  original thread on Sponser.

## Setup

```bash
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # ./.venv/bin/... on Linux/the VPS

cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and (optionally) OPENROUTER_API_KEY
```

## Commands

```bash
# Run all tests
./.venv/Scripts/python.exe -m pytest -v

# Run the live incremental check (requires .env)
./.venv/Scripts/python.exe -m hadar_tracker.check

# Backfill historical posts (does not require Telegram credentials to function)
./.venv/Scripts/python.exe -m hadar_tracker.backfill --days 30
```

## Documentation

- [CLAUDE.md](CLAUDE.md) — architecture, module map, and the design decisions behind the
  scraping approach, the notification filter, and the trading-hours gate.
- [deploy/README.md](deploy/README.md) — deploying to a VPS via systemd timer or cron.

## Status

Live: scraping, storage, LLM classification, notification filtering, and trading-hours gating
are all implemented and running.
