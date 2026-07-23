from __future__ import annotations

import json
import os
import sqlite3
from typing import Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    msg_id           TEXT PRIMARY KEY,
    posted_at        TEXT NOT NULL,
    level            INTEGER NOT NULL,
    thread_group     TEXT NOT NULL,
    root_subject     TEXT,
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    tags             TEXT NOT NULL,
    image_file_name  TEXT,
    image_local_path TEXT,
    signal_json      TEXT,
    scraped_at       TEXT NOT NULL,
    notified         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database at db_path.

    Ensures the parent directory exists so the first run on a fresh VPS does
    not fail on a missing `data/` folder.
    """
    if db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_add_signal_json_column(conn)
    _migrate_add_notified_column(conn)
    conn.commit()


def _migrate_add_signal_json_column(conn: sqlite3.Connection) -> None:
    """Add signal_json to a posts table created before Phase 2 existed.

    SCHEMA's `CREATE TABLE IF NOT EXISTS` is a no-op against an
    already-created table, so a DB file from before this column existed
    needs an explicit ALTER TABLE — this makes init_db safe against both a
    fresh DB (SCHEMA already has the column, so this is a no-op) and an
    existing one (VPS deployments already running Phase 1).
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if "signal_json" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN signal_json TEXT")


def _migrate_add_notified_column(conn: sqlite3.Connection) -> None:
    """Add notified to a posts table created before the trading-hours hold
    queue existed. Defaults every pre-existing row to 1 (already handled) —
    a migration must never retroactively queue up months of old posts for
    delivery just because the column didn't exist yet.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if "notified" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN notified INTEGER NOT NULL DEFAULT 1")


def post_exists(conn: sqlite3.Connection, msg_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM posts WHERE msg_id = ?", (msg_id,)
    ).fetchone()
    return row is not None


def insert_post(
    conn: sqlite3.Connection,
    msg_id: str,
    posted_at: str,
    level: int,
    thread_group: str,
    root_subject: str | None,
    subject: str,
    body: str,
    tags: Sequence[str],
    image_file_name: str | None,
    image_local_path: str | None,
    scraped_at: str,
    signal_json: str | None = None,
    notified: bool = True,
) -> bool:
    """Insert a post, ignoring it if msg_id already exists.

    `tags` is JSON-encoded to a TEXT column here (single source of truth for
    the serialization format). `signal_json` is the caller's already-
    serialized `Signal` (see hadar_tracker.signal.classify_post) or None if
    classification didn't run/succeed. `notified` defaults to True — posts
    are sent immediately when found, regardless of the hour (see
    check.py/notify_filter.py), so no current caller inserts with
    notified=False. The parameter and the notified=0 path
    (fetch_pending_posts/mark_notified below) only remain to drain any row
    left over from the older hold-until-market-open behavior. Returns True
    iff a new row was inserted — safe for both the incremental check and any
    idempotent re-run.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO posts "
        "(msg_id, posted_at, level, thread_group, root_subject, subject, "
        " body, tags, image_file_name, image_local_path, scraped_at, signal_json, notified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            msg_id,
            posted_at,
            level,
            thread_group,
            root_subject,
            subject,
            body,
            json.dumps(list(tags)),
            image_file_name,
            image_local_path,
            scraped_at,
            signal_json,
            1 if notified else 0,
        ),
    )
    conn.commit()
    return cur.rowcount == 1


def count_posts(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]


def fetch_pending_posts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Posts already stored but not yet sent (notified=0) — a legacy queue
    from before posts were sent immediately at all hours; nothing inserts
    with notified=False anymore, so this only ever drains rows left over
    from that older behavior. Ordered by posted_at so a flush delivers them
    in the order Hadar actually posted them.
    """
    return conn.execute(
        "SELECT * FROM posts WHERE notified = 0 ORDER BY posted_at"
    ).fetchall()


def mark_notified(conn: sqlite3.Connection, msg_id: str) -> None:
    conn.execute("UPDATE posts SET notified = 1 WHERE msg_id = ?", (msg_id,))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Small key-value store for run-level state that isn't a post — e.g.
    check.py's last-off-hours-check timestamp (see notify_filter.py)."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def thread_has_root(conn: sqlite3.Connection, thread_group: str) -> bool:
    """True if a level==1 post already exists in this thread_group.

    This table only ever contains Hadar's own posts (parse_posts filters to
    Hadar-only), so a level==1 row here means Hadar started this thread.
    Used by notify_filter.classify_bucket to tell a reply into his own
    thread apart from a reply into someone else's when the root wasn't in
    the same scrape payload as the reply (so thread_transcript alone can't
    answer it).
    """
    row = conn.execute(
        "SELECT 1 FROM posts WHERE thread_group = ? AND level = 1 LIMIT 1",
        (thread_group,),
    ).fetchone()
    return row is not None
