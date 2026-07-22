"""One-off analysis script: re-walk the same forum-history page range as the
90-day backfill, but this time keep EVERY user's items (not just Hadar's),
so we can reconstruct full multi-person threads.

hadar_tracker.scraper.parse.parse_posts filters to Hadar-only by design (see
CLAUDE.md) — the `posts` table therefore never has another user's message
body, only the `root_subject` text. The general-forum endpoint
(scraper/history.py) itself returns all users on each page; we just never
persisted that. This script re-fetches the identical page range and stores
every item into a side table (`context_items`, in the same data/hadar.sqlite3
file but not part of the shipped app schema in db.py) keyed by msg_id, so we
can look up "everything said in thread group X" after the fact.

Same page-walk skeleton as hadar_tracker.backfill.run_backfill (page_id=0
bonus pass, then number_of_pages-1 downward, stopping once a page's oldest
item crosses the cutoff) — deliberately not importing run_backfill itself
since that function filters to Hadar and doesn't expose raw items.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time
from datetime import datetime, timedelta

from hadar_tracker.scraper import history
from hadar_tracker.scraper.parse import parse_date

DB_PATH = "data/hadar.sqlite3"
FORUM_ID = 1
DELAY_SECONDS = 0.5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_thread_context")

SCHEMA = """
CREATE TABLE IF NOT EXISTS context_items (
    msg_id      TEXT PRIMARY KEY,
    thread_group TEXT NOT NULL,
    level       INTEGER NOT NULL,
    is_hadar    INTEGER NOT NULL,
    user_name   TEXT,
    subject     TEXT,
    body        TEXT,
    posted_at   TEXT NOT NULL
);
"""


def _oldest_date_on_page(payload: dict) -> datetime | None:
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


def _store_page(conn: sqlite3.Connection, payload: dict) -> int:
    inserted = 0
    for item in payload.get("Data", []):
        try:
            msg_id = str(item.get("MsgId"))
            level = int(item.get("Level"))
            thread_group = str(item.get("L1"))
            posted_at = parse_date(item.get("DateCreated"))
        except (TypeError, ValueError):
            continue
        user = item.get("User") or {}
        is_hadar = 1 if user.get("UserId") == 5609 else 0
        cur = conn.execute(
            "INSERT OR IGNORE INTO context_items "
            "(msg_id, thread_group, level, is_hadar, user_name, subject, body, posted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg_id, thread_group, level, is_hadar,
                user.get("UserName") or user.get("Nick"),
                item.get("subject") or "", item.get("Msg") or "", posted_at,
            ),
        )
        if cur.rowcount == 1:
            inserted += 1
    conn.commit()
    return inserted


def main(days: int = 90) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()

    cutoff = datetime.now() - timedelta(days=days)
    top_payload = history.fetch_history_page(page_id=0, forum_id=FORUM_ID)
    number_of_pages = int(top_payload["Info"]["NumberOfPages"])
    total_inserted = _store_page(conn, top_payload)
    pages_fetched = 1

    page_num = number_of_pages - 1
    while page_num >= 1:
        payload = history.fetch_history_page(page_id=page_num, forum_id=FORUM_ID)
        pages_fetched += 1
        items = payload.get("Data", [])
        if not items:
            break
        total_inserted += _store_page(conn, payload)

        oldest = _oldest_date_on_page(payload)
        if oldest is not None and oldest < cutoff:
            break

        page_num -= 1
        if page_num >= 1:
            time.sleep(DELAY_SECONDS)

        if pages_fetched % 25 == 0:
            log.info("progress: %d pages fetched, %d context rows so far", pages_fetched, total_inserted)

    log.info("done: %d pages fetched, %d context rows inserted", pages_fetched, total_inserted)


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    main(days)
