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

## 3. Make the wrapper executable and smoke-test

```bash
chmod +x deploy/run_check.sh
./deploy/run_check.sh
```

Expected: exit code 0, a log line `check complete: N new post(s)`, and — on the
first run against the live feed — Telegram messages for the recent posts
(subject, 🏷 tickers, ↩️ reply-context where applicable, body, and the attached
picture when one is present).

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

## 5. Historical backfill — NOT available yet

`python -m hadar_tracker.backfill` is currently a **stub**: it logs that the
history-crawl mechanism is undetermined and exits with code 2. The live
endpoint only covers ~1 day of activity; reaching Hadar's full archive needs a
follow-up investigation (see the design spec's "Open items"). Backfill is not
required for Phase 1 launch — only before Phase 2 analysis.

## 6. Tuning

Once real posting cadence is known, adjust the interval (`OnUnitActiveSec` in
the timer, or the cron `*/N`) toward the 10–15 min target.
