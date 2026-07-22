# Deploying HadarTracker to the Oracle Cloud VPS

Phase 1 is a plain-HTTP JSON client — **no browser, no Chromium**. Build and
test locally first (`python -m pytest` must be green). Then, on the VPS:

## 1. Clone and set up

```bash
cd ~
git clone <repo-url> HadarTracker
cd HadarTracker
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

That is the whole install — `requests`, `python-telegram-bot`, and `pytest`.
There is no `playwright install` step (the old browser-based design was
dropped after the site's JSON endpoint proved reachable with plain HTTP).

## 2. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
chmod 600 .env
```

Get a bot token from @BotFather; get your chat id by messaging the bot and
reading `https://api.telegram.org/bot<TOKEN>/getUpdates`.

Also set `OPENROUTER_API_KEY` (and optionally `OPENROUTER_MODEL`, default
`anthropic/claude-sonnet-4.5` — this deployment uses `deepseek/deepseek-v4-flash`)
to enable Phase 2 LLM trade-signal classification. Without a key, classification
is simply skipped (`signal=None`) and every post still gets scraped, stored,
and — subject to the notification filter below — notified.

**Never commit real secrets into `.env.example`** — it's tracked by git
(unlike `.env`, which is gitignored); it should only ever contain empty
placeholders.

## 3. Make the wrapper executable and smoke-test

```bash
chmod +x deploy/run_check.sh
./deploy/run_check.sh
```

Expected: exit code 0, a log line `check complete: N new post(s)`, and — on the
first run against the live feed — Telegram messages for the recent posts
(subject, 🏷 tickers, ↩️ reply-context where applicable, body, and the attached
picture when one is present). Not every "new post" necessarily produces a
message, though — see the notification filter below.

## 3.5. What actually gets notified

Not every scraped post reaches Telegram. `hadar_tracker/notify_filter.py`
gates on the post's thread bucket: a thread Hadar started always notifies; a
reply (his own thread or someone else's) with an image or ticker tag always
notifies; a reply with neither defers to the Phase 2 LLM signal, and sends
anyway if classification is unavailable (fail-open — a classifier hiccup must
never look like a silently dropped post).

Notifications are also held to **09:30-17:30 Israel time**. A post that
should notify but is found outside that window is stored (not sent) and
flushed — labeled 🌙 **After Hours** — at the start of the next run where the
window is open. This is enforced in code, not by narrowing the timer/cron
schedule below — **keep the job running on its normal 10-15 min cadence all
day**, otherwise the hold queue won't get flushed promptly at 09:30.

## 4. Schedule it — choose ONE of the two options below

### Option A: systemd timer (recommended)

Edit `User` and `WorkingDirectory` in `deploy/hadar-tracker.service` to match
your path, then:

```bash
sudo cp deploy/hadar-tracker.service /etc/systemd/system/
sudo cp deploy/hadar-tracker.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hadar-tracker.timer
systemctl list-timers hadar-tracker.timer
journalctl -u hadar-tracker.service -n 50 --no-pager
```

### Option B: cron

```bash
crontab -e
```

Add (every 10 minutes; adjust to 15 once cadence is known):

```
*/10 * * * * /home/ubuntu/HadarTracker/deploy/run_check.sh >> /home/ubuntu/HadarTracker/data/check.log 2>&1
```

`check.py` exits non-zero and sends a Telegram alert on failure, so both the
log file / `journalctl` and Telegram surface problems — no silent misses.

## 5. Historical backfill

`python -m hadar_tracker.backfill --days N` is implemented: it walks the
general forum listing (`scraper/history.py`) backward from the current page,
filtering to Hadar's posts, until it crosses the `--days` cutoff. It never
sends Telegram notifications (a historical import isn't a live alert stream)
and is safe to interrupt and rerun. `load_config()` still requires
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` to be set even though backfill doesn't
use them — construct a `Config` directly (see `scripts/run_backfill_no_telegram.py`)
to run it without real Telegram credentials.

## 6. Tuning

Once real posting cadence is known, adjust the interval (`OnUnitActiveSec` in
the timer, or the cron `*/N`) toward the 10–15 min target.
