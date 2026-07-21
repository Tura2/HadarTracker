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
    scraped_at       TEXT NOT NULL
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
    conn.commit()


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
) -> bool:
    """Insert a post, ignoring it if msg_id already exists.

    `tags` is JSON-encoded to a TEXT column here (single source of truth for
    the serialization format). Returns True iff a new row was inserted — safe
    for both the incremental check and any idempotent re-run.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO posts "
        "(msg_id, posted_at, level, thread_group, root_subject, subject, "
        " body, tags, image_file_name, image_local_path, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        ),
    )
    conn.commit()
    return cur.rowcount == 1


def count_posts(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
