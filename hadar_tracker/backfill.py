from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta

from hadar_tracker import db, images
from hadar_tracker.config import Config, load_config
from hadar_tracker.scraper import history
from hadar_tracker.scraper.parse import parse_date, parse_posts
from hadar_tracker.util import now_iso

DEFAULT_DAYS = 30

# Politeness delay between requests to the general-forum history endpoint.
DEFAULT_DELAY_SECONDS = 0.5

log = logging.getLogger("hadar_tracker.backfill")


def _process_page(conn, payload: dict, config: Config, cutoff: datetime) -> int:
    """Insert the configured user's posts from one history page that are
    >= cutoff.

    Downloads any attached image first (best-effort — a download failure is
    logged and the post is still stored without a local image, rather than
    losing the whole post over one bad attachment). Returns the number of
    genuinely new rows inserted.
    """
    inserted = 0
    for post in parse_posts(payload, user_id=config.user_id):
        if datetime.fromisoformat(post.posted_at) < cutoff:
            continue

        image_local_path = None
        if post.image_file_name:
            try:
                image_local_path = images.download_image(
                    post.image_file_name, config.images_dir
                )
            except Exception as exc:  # noqa: BLE001 - one bad image shouldn't lose the post
                log.warning(
                    "image download failed for msg_id=%s: %s", post.msg_id, exc
                )

        if db.insert_post(
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
        ):
            inserted += 1

    return inserted


def _oldest_date_on_page(payload: dict) -> datetime | None:
    """The earliest DateCreated among ALL items on a page (any user).

    Used only to decide when we've paged back far enough — not for filtering
    which posts get stored (that's per-post, in _process_page). Malformed
    dates are skipped rather than crashing the walk.
    """
    dates = []
    for item in payload.get("Data", []):
        raw = item.get("DateCreated")
        if not raw:
            continue
        try:
            dates.append(datetime.fromisoformat(parse_date(raw)))
        except ValueError:
            continue
    return min(dates) if dates else None


def run_backfill(
    config: Config | None = None,
    days: int = DEFAULT_DAYS,
    max_pages: int | None = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    fetch_page=None,
    sleep=None,
) -> int:
    """Walk the general forum listing backward from today, filtering to the
    configured user's own posts, upserting each into the posts table.

    The general-forum endpoint (unlike the ~1-day "recent activity" one used
    by check.py) supports real pagination back to the forum's origin, so this
    can reach arbitrarily old history — `days` bounds how far back this run
    goes. Idempotent/resumable: every insert goes through db.insert_post's
    INSERT OR IGNORE, so interrupting and rerunning is always safe. Does NOT
    send Telegram notifications (this is a historical import, not a live
    alert). Returns 0 on success, 1 on failure (logged, never silent).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if config is None:
        config = load_config()
    if fetch_page is None:
        fetch_page = history.fetch_history_page
    if sleep is None:
        sleep = time.sleep

    conn = db.connect(config.db_path)
    db.init_db(conn)

    cutoff = datetime.now() - timedelta(days=days)
    inserted = 0
    pages_fetched = 0

    try:
        # page_id=0 is a "recently bumped" bucket: mixed dates, but real posts.
        # Process it for bonus coverage (idempotent insert makes this safe)
        # and to learn the current NumberOfPages for the real chronological walk.
        top_payload = fetch_page(page_id=0, forum_id=config.forum_id)
        number_of_pages = int(top_payload["Info"]["NumberOfPages"])
        inserted += _process_page(conn, top_payload, config, cutoff)
        pages_fetched += 1

        page_num = number_of_pages - 1
        while page_num >= 1:
            if max_pages is not None and pages_fetched >= max_pages:
                log.info("reached --max-pages limit (%d); stopping", max_pages)
                break

            payload = fetch_page(page_id=page_num, forum_id=config.forum_id)
            pages_fetched += 1
            items = payload.get("Data", [])
            if not items:
                break

            inserted += _process_page(conn, payload, config, cutoff)

            oldest = _oldest_date_on_page(payload)
            if oldest is not None and oldest < cutoff:
                break

            page_num -= 1
            if page_num >= 1:
                sleep(delay_seconds)

    except Exception as exc:  # noqa: BLE001 - fail loudly, report progress
        log.error(
            "backfill failed after %d page(s), %d post(s) inserted: %s",
            pages_fetched,
            inserted,
            exc,
        )
        return 1

    log.info(
        "backfill complete: %d new post(s) inserted from %d page(s) "
        "(cutoff: %d day(s) back)",
        inserted,
        pages_fetched,
        days,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Hadar's post history from the general forum listing."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"How many days back to backfill (default: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Safety cap on how many history pages to fetch (default: no cap).",
    )
    args = parser.parse_args()
    sys.exit(run_backfill(days=args.days, max_pages=args.max_pages))


if __name__ == "__main__":
    main()
