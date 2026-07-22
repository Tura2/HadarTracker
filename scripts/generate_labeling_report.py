"""One-off analysis script: build a self-contained HTML report of Hadar's
last-90-days posts, grouped into 3 structural buckets, for manual labeling.

Not part of the shipped app (Phase 1/2 pipeline) — this is a throwaway
analysis tool to validate a hypothesis about which of Hadar's posts carry
real trading signal vs which are noise, before deciding whether to add a
structural pre-filter ahead of the LLM classifier in signal.py.

Buckets (derived purely from data already in the posts table — no new
scraping):
  - own_root:    level == 1 (he started the thread)
  - reply_own:   level > 1, but the thread_group already has a level==1 row
                 in this table (so the root post was also his)
  - reply_other: level > 1, no level==1 row for this thread_group in this
                 table -> the root must belong to another user (this table
                 only ever contains Hadar's own posts, see parse_posts)

Images are downscaled to small JPEG thumbnails (Pillow) before being
embedded as base64 data URIs, since embedding all 643 originals verbatim
would make the report unworkably large.
"""
from __future__ import annotations

import base64
import io
import json
import sqlite3

from PIL import Image

DB_PATH = "data/hadar.sqlite3"
OUT_JSON = "scripts/_report_data.json"

THUMB_MAX_DIM = 320
THUMB_JPEG_QUALITY = 45


def suggest_label(bucket: str, image_uri: str | None, tags: list[str], body: str | None) -> str:
    """Heuristic pre-label so the user reviews/corrects instead of starting
    from zero on 4k+ posts. Deliberately conservative: only calls "noise" on
    the clear-cut empty/near-empty replies; anything with real body text and
    no image gets "unsure" so a human actually reads it rather than the
    heuristic silently hiding a possible signal.
    """
    body_len = len(body or "")
    if bucket == "own_root":
        return "real"  # his hypothesis: his own threads ARE the actions
    if bucket == "reply_own":
        if image_uri or tags:
            return "real"
        return "noise" if body_len <= 15 else "unsure"
    # reply_other
    if image_uri:
        return "graph"
    return "noise" if body_len <= 15 else "unsure"


def thumbnail_data_uri(path: str) -> str | None:
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMB_MAX_DIM, THUMB_MAX_DIM))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=THUMB_JPEG_QUALITY)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:  # noqa: BLE001 - one bad image shouldn't kill the report
        print(f"WARN: could not thumbnail {path}: {exc}")
        return None


def build_threads(conn: sqlite3.Connection, thread_groups: set[str]) -> dict[str, list[dict]]:
    """Full multi-user conversation per thread_group, from context_items
    (populated by scripts/fetch_thread_context.py's separate re-walk — the
    `posts` table alone only ever has Hadar's own messages, see module
    docstring). Keyed by thread_group so posts in the same thread share one
    copy instead of duplicating the conversation per-post.
    """
    threads: dict[str, list[dict]] = {}
    if not thread_groups:
        return threads
    placeholders = ",".join("?" * len(thread_groups))
    rows = conn.execute(
        f"SELECT msg_id, thread_group, level, is_hadar, subject, body, posted_at "
        f"FROM context_items WHERE thread_group IN ({placeholders}) ORDER BY posted_at",
        list(thread_groups),
    ).fetchall()
    for r in rows:
        threads.setdefault(r["thread_group"], []).append(
            {
                "id": r["msg_id"],
                "is_hadar": bool(r["is_hadar"]),
                "level": r["level"],
                "subject": r["subject"],
                "body": r["body"],
                "date": r["posted_at"],
            }
        )
    return threads


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT msg_id, posted_at, level, thread_group, root_subject, "
        "subject, body, tags, image_local_path FROM posts ORDER BY posted_at"
    ).fetchall()

    own_roots = {r["thread_group"] for r in rows if r["level"] == 1}

    thumb_cache: dict[str, str | None] = {}
    posts = []
    all_thread_groups: set[str] = set()
    for r in rows:
        if r["level"] == 1:
            bucket = "own_root"
        elif r["thread_group"] in own_roots:
            bucket = "reply_own"
        else:
            bucket = "reply_other"

        image_uri = None
        if r["image_local_path"]:
            path = r["image_local_path"]
            if path not in thumb_cache:
                thumb_cache[path] = thumbnail_data_uri(path)
            image_uri = thumb_cache[path]

        tags = json.loads(r["tags"] or "[]")
        all_thread_groups.add(r["thread_group"])
        posts.append(
            {
                "id": r["msg_id"],
                "date": r["posted_at"],
                "level": r["level"],
                "bucket": bucket,
                "thread_group": r["thread_group"],
                "root_subject": r["root_subject"],
                "subject": r["subject"],
                "body": r["body"],
                "tags": tags,
                "image": image_uri,
                "suggested": suggest_label(bucket, image_uri, tags, r["body"]),
            }
        )

    threads = build_threads(conn, all_thread_groups)

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({"posts": posts, "threads": threads}, fh, ensure_ascii=False)

    print(
        f"wrote {len(posts)} posts, {sum(1 for p in posts if p['image'])} with thumbnails, "
        f"{len(threads)} threads with context ({sum(len(v) for v in threads.values())} context rows)"
    )


if __name__ == "__main__":
    main()
