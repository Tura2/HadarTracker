from __future__ import annotations

import dataclasses
import json
import logging
import sys

from hadar_tracker import db, images, notifier, notify_filter
from hadar_tracker.config import Config, load_config
from hadar_tracker.models import Post, Signal
from hadar_tracker.scraper import client
from hadar_tracker.signal import classify_post
from hadar_tracker.util import now_iso


def _flush_pending(conn, config: Config, send_post) -> None:
    """Send anything queued from a previous run (notified=0) — a post that
    passed should_notify but was discovered outside 09:30-17:30 Israel time,
    so it was held rather than sent then. Always labeled "🌙 After Hours"
    since, by construction, anything in this queue was outside the window
    when it was found. Only called when the caller has already confirmed
    market_open is True for this run (see process_new_posts).
    """
    for row in db.fetch_pending_posts(conn):
        signal = Signal(**json.loads(row["signal_json"])) if row["signal_json"] else None
        send_post(
            config.telegram_bot_token,
            config.telegram_chat_id,
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
    market_open: bool = True,
) -> list[Post]:
    """Download any attachment, classify it into a trade signal, notify
    (subject to the notify_filter gate and trading-hours window), then
    persist unseen posts. Returns the posts newly processed (persisted),
    regardless of whether they were actually sent — a filtered-out or
    queued post is still genuinely new and must be marked seen so it isn't
    reprocessed forever.

    Classification (`classify`) runs between download and the notify
    decision, and is fail-open by contract (classify_post never raises —
    see signal.py): a classification problem must never block, delay, or
    duplicate-send a notification, unlike a genuine Telegram/DB failure
    below, which stays fail-loud exactly as it was in Phase 1.
    `notify_filter.should_notify` decides, from the post's thread bucket
    (own thread / reply to his own thread / reply to someone else's) and
    the classification, whether this post is worth sending at all — see
    notify_filter.py for the reasoning.

    A post that should be notified but is discovered while `market_open` is
    False (outside 09:30-17:30 Israel time) is held: stored with
    notified=0 and NOT sent now. The next run where `market_open` is True
    flushes every held post first (see _flush_pending), each labeled
    "🌙 After Hours", before processing this run's new posts — so an
    overnight post surfaces at the next trading-hours run instead of
    firing off a Telegram message at 2am. `market_open` defaults to True
    (send immediately, exactly like before this feature existed) so
    existing callers/tests that don't care about trading hours are
    unaffected; run_check passes the real current value via
    notify_filter.is_market_hours_now().

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

    if market_open:
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
        if notify and market_open:
            send_post(
                config.telegram_bot_token,
                config.telegram_chat_id,
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
            # Queued (notified=False) only when this post should be sent but
            # we're outside trading hours right now; every other case (won't
            # be sent at all, or was sent just above) is already handled.
            notified=(not notify) or market_open,
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
    schedule stays fixed (e.g. every 10 min, all day — see deploy/README.md)
    so the hold queue flushes promptly at 09:30, but there's nothing
    time-sensitive to catch overnight, so notify_filter.should_run_offhours_check
    throttles the actual scrape+process work to once per hour off-hours
    rather than reconfiguring the scheduler for two cadences.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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

    market_open = notify_filter.is_market_hours_now()
    if not market_open:
        if not notify_filter.should_run_offhours_check(conn):
            log.info("skipping off-hours check (already checked within the last hour)")
            return 0
        notify_filter.mark_offhours_check_ran(conn)

    try:
        posts = client.fetch_posts(user_id=config.user_id, forum_id=config.forum_id)
    except Exception as exc:  # noqa: BLE001 - fail loudly on ANY scrape error
        log.error("scrape failed: %s", exc)
        alert(f"scraper run failed: {exc}")
        return 1

    try:
        new_posts = process_new_posts(conn, config, posts, market_open=market_open)
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
