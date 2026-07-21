from __future__ import annotations

import dataclasses
import json
import logging
import sys

from hadar_tracker import db, images, notifier
from hadar_tracker.config import Config, load_config
from hadar_tracker.models import Post
from hadar_tracker.scraper import client
from hadar_tracker.signal import classify_post
from hadar_tracker.util import now_iso


def process_new_posts(
    conn,
    config: Config,
    posts: list[Post],
    download=None,
    send_post=None,
    classify=None,
) -> list[Post]:
    """Download any attachment, classify it into a trade signal, notify, then
    persist unseen posts — one message each. Returns the posts newly
    processed.

    Classification (`classify`) runs between download and notify, and is
    fail-open by contract (classify_post never raises — see signal.py): a
    classification problem must never block, delay, or duplicate-send a
    notification, unlike a genuine Telegram/DB failure below, which stays
    fail-loud exactly as it was in Phase 1.

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
        )
        signal_json = json.dumps(dataclasses.asdict(signal)) if signal else None

        send_post(
            config.telegram_bot_token,
            config.telegram_chat_id,
            post.subject,
            post.tags,
            post.body,
            post.root_subject,
            image_local_path,
            signal,
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

    try:
        posts = client.fetch_posts(user_id=config.user_id, forum_id=config.forum_id)
    except Exception as exc:  # noqa: BLE001 - fail loudly on ANY scrape error
        log.error("scrape failed: %s", exc)
        alert(f"scraper run failed: {exc}")
        return 1

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
