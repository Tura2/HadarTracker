from __future__ import annotations

from hadar_tracker import db, images, notifier
from hadar_tracker.config import Config
from hadar_tracker.models import Post
from hadar_tracker.util import now_iso


def process_new_posts(
    conn,
    config: Config,
    posts: list[Post],
    download=None,
    send_post=None,
) -> list[Post]:
    """Insert unseen posts, download any attachment, and notify — one message
    each. Returns the posts newly processed.

    `download` and `send_post` are injected so this is unit-testable without a
    live network or Telegram. They resolve to the real functions at call time
    (not as def-time defaults) so callers like run_check can be tested by
    monkeypatching `notifier.send_post`.
    """
    if download is None:
        download = images.download_image
    if send_post is None:
        send_post = notifier.send_post

    new_posts: list[Post] = []
    for post in posts:
        if db.post_exists(conn, post.msg_id):
            continue

        image_local_path: str | None = None
        if post.image_file_name:
            image_local_path = download(post.image_file_name, config.images_dir)

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
        )
        send_post(
            config.telegram_bot_token,
            config.telegram_chat_id,
            post.subject,
            post.tags,
            post.body,
            post.root_subject,
            image_local_path,
        )
        new_posts.append(post)

    return new_posts
