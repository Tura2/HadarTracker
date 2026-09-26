from __future__ import annotations

import dataclasses
import json
import logging
import sys
from datetime import datetime, timedelta

from hadar_tracker import db, images, notifier, notify_filter
from hadar_tracker.config import Config, load_config
from hadar_tracker.models import Post, Signal
from hadar_tracker.scraper import client
from hadar_tracker.signal import classify_post
from hadar_tracker.util import now_iso

# Back-off after Sponser's Cloudflare front returns 403. Retrying every run
# while blocked keeps the block alive and used to send one admin alert per
# run (~1,400/day at a 1-minute timer), so instead: alert once, try only
# every 2 hours while blocked, and alert once more when a scrape succeeds
# again — at which point the normal timer cadence resumes on its own. State
# lives in the meta table so it survives across the independent
# systemd-triggered runs.
BLOCK_RETRY_MINUTES = 120
_BLOCK_STREAK_KEY = "block_streak"
_BLOCKED_SINCE_KEY = "blocked_since"
_BLOCKED_UNTIL_KEY = "blocked_until"


def _record_block(conn, now: datetime) -> tuple[int, datetime]:
    """Bump the consecutive-block streak and schedule the next attempt.
    Returns (streak, retry_at)."""
    streak = int(db.get_meta(conn, _BLOCK_STREAK_KEY) or 0) + 1
    retry_at = now + timedelta(minutes=BLOCK_RETRY_MINUTES)
    db.set_meta(conn, _BLOCK_STREAK_KEY, str(streak))
    db.set_meta(conn, _BLOCKED_UNTIL_KEY, retry_at.isoformat())
    if streak == 1:
        db.set_meta(conn, _BLOCKED_SINCE_KEY, now.isoformat())
    return streak, retry_at


def _clear_block(conn) -> str | None:
    """Reset block state after a successful scrape. Returns when the block
    started if we were blocked, else None."""
    if db.get_meta(conn, _BLOCK_STREAK_KEY) is None:
        return None
    since = db.get_meta(conn, _BLOCKED_SINCE_KEY)
    for key in (_BLOCK_STREAK_KEY, _BLOCKED_SINCE_KEY, _BLOCKED_UNTIL_KEY):
        db.delete_meta(conn, key)
    return since or "unknown"


def _notify_chat_ids(config: Config) -> tuple[str, ...]:
    """Every chat that should receive POST notifications — the primary
    telegram_chat_id plus any telegram_extra_chat_ids, deduplicated. Error
    alerts never use this: they go to config.telegram_chat_id alone (see
    run_check's `alert` helper) — someone subscribing to Hadar's posts
    shouldn't also get woken up by a scraper failure that's the admin's
    problem, not theirs.
    """
    return tuple(dict.fromkeys((config.telegram_chat_id, *config.telegram_extra_chat_ids)))


def _flush_pending(conn, config: Config, send_post) -> None:
    """Send anything still queued (notified=0) from before posts were sent
    immediately at all hours. Posts are no longer queued going forward (see
    process_new_posts), but any row left over from that older behavior still
    needs to go out exactly once, so this runs unconditionally on every call.
    Always labeled "🌙 After Hours" since, by construction, anything that
    ever landed in this queue was outside the window when it was found.
    """
    for row in db.fetch_pending_posts(conn):
        signal = Signal(**json.loads(row["signal_json"])) if row["signal_json"] else None
        for chat_id in _notify_chat_ids(config):
            send_post(
                config.telegram_bot_token,
                chat_id,
                row["subject"],
                tuple(json.loads(row["tags"])),
                row["body"],
                row["root_subject"],
                row["image_local_path"],
                signal,
                True,
                notifier.build_thread_url(config.forum_id, row["msg_id"]),
            )
        db.mark_notified(conn, row["msg_id"])


def process_new_posts(
    conn,
    config: Config,
    posts: list[Post],
    download=None,
    send_post=None,
    classify=None,
) -> list[Post]:
    """Download any attachment, classify it into a trade signal, notify
    (subject to the notify_filter gate), then persist unseen posts. Returns
    the posts newly processed (persisted), regardless of whether they were
    actually sent — a filtered-out post is still genuinely new and must be
    marked seen so it isn't reprocessed forever.

    Classification (`classify`) runs between download and the notify
    decision, and is fail-open by contract (classify_post never raises —
    see signal.py): a classification problem must never block, delay, or
    duplicate-send a notification, unlike a genuine Telegram/DB failure
    below, which stays fail-loud exactly as it was in Phase 1.
    `notify_filter.should_notify` decides, from the post's thread bucket
    (own thread / reply to his own thread / reply to someone else's) and
    the classification, whether this post is worth sending at all — see
    notify_filter.py for the reasoning.

    A post that should be notified is always sent immediately, regardless of
    the hour — only the scrape cadence differs outside 09:30-17:30 (see
    run_check's off-hours throttle), not whether a matching post gets sent.
    A post found outside that window is still sent right away, just labeled
    "🌙 After Hours" (see notify_filter.is_after_hours) so the reader knows
    it happened off-hours. `_flush_pending` runs unconditionally first only
    to drain any row left over from the older hold-until-market-open
    behavior; new posts are never queued.

    Notification happens before the DB insert so that if `send_post` raises
    (e.g. a real Telegram API error), the post is NOT marked as seen and will
    be retried on the next run instead of being silently and permanently
    dropped. Earlier posts in the same batch that already succeeded remain
    committed even if a later post's send fails.

    `download`, `send_post`, and `classify` are injected so this is
    unit-testable without a live network, Telegram, or OpenRouter call. They
    resolve to the real functions at call time (not as def-time defaults) so
    callers like run_check can be tested by monkeypatching
    `notifier.send_post` / `hadar_tracker.signal.classify_post`.
    """
    if download is None:
        download = images.download_image
    if send_post is None:
        send_post = notifier.send_post
    if classify is None:
        classify = classify_post

    _flush_pending(conn, config, send_post)

    new_posts: list[Post] = []
    for post in posts:
        if db.post_exists(conn, post.msg_id):
            continue

        image_local_path: str | None = None
        if post.image_file_name:
            image_local_path = download(post.image_file_name, config.images_dir)

        signal = classify(
            post,
            image_local_path,
            config.openrouter_api_key,
            config.openrouter_model,
            config.openrouter_vision_model,
        )
        signal_json = json.dumps(dataclasses.asdict(signal)) if signal else None

        bucket = notify_filter.classify_bucket(post, conn)
        notify = notify_filter.should_notify(bucket, post, signal)
        if notify:
            for chat_id in _notify_chat_ids(config):
                send_post(
                    config.telegram_bot_token,
                    chat_id,
                    post.subject,
                    post.tags,
                    post.body,
                    post.root_subject,
                    image_local_path,
                    signal,
                    notify_filter.is_after_hours(post.posted_at),
                    notifier.build_thread_url(config.forum_id, post.msg_id),
                )
        db.insert_post(
            conn,
            post.msg_id,
            post.posted_at,
            post.level,
            post.thread_group,
            post.root_subject,
            post.subject,
            post.body,
            post.tags,
            post.image_file_name,
            image_local_path,
            now_iso(),
            signal_json,
        )
        new_posts.append(post)

    return new_posts


def run_check(config: Config | None = None) -> int:
    """Run one incremental check. Returns 0 on success, 1 on failure.

    On failure the error is logged AND a Telegram alert is sent AND we return
    non-zero — the spec's no-silent-failure contract. This applies to EVERY
    stage of the run (DB connect/init, the scrape, and processing new posts —
    which covers downloading attachments, sending Telegram messages, and
    persisting to the DB), not just the scrape call, since a network/HTTP
    error while sending or downloading for a genuinely new post is the most
    likely real-world failure mode.

    Outside market hours, most invocations are a fast no-op: the deployment
    schedule stays fixed (e.g. every 10 min, all day — see deploy/README.md),
    but there's no need to hit Sponser's server that often overnight, so
    notify_filter.should_run_offhours_check throttles the actual
    scrape+process work to once per hour off-hours rather than
    reconfiguring the scheduler for two cadences. This only affects how often
    new posts are *discovered* off-hours — once found, a post is sent
    immediately regardless of the hour (see process_new_posts), just labeled
    "🌙 After Hours" when applicable.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs every request URL at INFO, and Telegram's Bot API puts the
    # bot token in the URL path — keep it out of the journal.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("hadar_tracker.check")

    if config is None:
        config = load_config()

    def alert(message: str) -> None:
        try:
            notifier.send_alert(
                config.telegram_bot_token,
                config.telegram_chat_id,
                message,
            )
        except Exception as alert_exc:  # noqa: BLE001 - never let alerting itself crash the run
            log.error("failed to send Telegram alert: %s", alert_exc)

    try:
        conn = db.connect(config.db_path)
        db.init_db(conn)
    except Exception as exc:  # noqa: BLE001 - fail loudly on ANY DB setup error
        log.error("run failed: %s", exc)
        alert(f"scraper run failed: {exc}")
        return 1

    now = datetime.now(notify_filter.IL_TZ)
    blocked_until = db.get_meta(conn, _BLOCKED_UNTIL_KEY)
    if blocked_until and now < datetime.fromisoformat(blocked_until):
        log.info("skipping check: backing off after a 403 block until %s", blocked_until)
        return 0

    if not notify_filter.is_market_hours_now():
        if not notify_filter.should_run_offhours_check(conn):
            log.info("skipping off-hours check (already checked within the last hour)")
            return 0
        notify_filter.mark_offhours_check_ran(conn)

    try:
        posts = client.fetch_posts(user_id=config.user_id, forum_id=config.forum_id)
    except client.BlockedError as exc:
        streak, retry_at = _record_block(conn, now)
        log.error("scrape blocked (attempt %d): %s — next try at %s", streak, exc, retry_at.isoformat())
        if streak == 1:
            alert(
                f"blocked by Sponser/Cloudflare: {exc}. Retrying every "
                f"2 hours; you'll get one more message when scraping works "
                f"again and the normal schedule resumes."
            )
        return 1
    except Exception as exc:  # noqa: BLE001 - fail loudly on ANY scrape error
        log.error("scrape failed: %s", exc)
        alert(f"scraper run failed: {exc}")
        return 1

    blocked_since = _clear_block(conn)
    if blocked_since:
        log.info("scrape recovered (blocked since %s)", blocked_since)
        alert(f"recovered: scraping works again (blocked since {blocked_since}).")

    try:
        new_posts = process_new_posts(conn, config, posts)
    except Exception as exc:  # noqa: BLE001 - fail loudly on ANY processing error
        log.error("run failed: %s", exc)
        alert(f"scraper run failed: {exc}")
        return 1

    log.info("check complete: %d new post(s)", len(new_posts))
    return 0


def main() -> None:
    sys.exit(run_check())


if __name__ == "__main__":
    main()
