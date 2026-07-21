import json

from hadar_tracker import db


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_insert_and_exists():
    conn = make_conn()
    assert db.post_exists(conn, "p1") is False
    inserted = db.insert_post(
        conn, "p1", "2026-07-21T10:00:00", 1, "900", None,
        "subj", "body", ("TEVA", "ICL"), None, None, "2026-07-21T10:05:00",
    )
    assert inserted is True
    assert db.post_exists(conn, "p1") is True
    assert db.count_posts(conn) == 1
    row = conn.execute("SELECT * FROM posts WHERE msg_id = 'p1'").fetchone()
    assert row["level"] == 1
    assert row["thread_group"] == "900"
    assert row["subject"] == "subj"
    assert json.loads(row["tags"]) == ["TEVA", "ICL"]


def test_insert_is_idempotent_on_msg_id():
    conn = make_conn()
    assert db.insert_post(
        conn, "p1", "t1", 1, "900", None, "s", "first", (), None, None, "s1"
    ) is True
    # Same msg_id again — ignored, not duplicated, reports not-new.
    assert db.insert_post(
        conn, "p1", "t1", 1, "900", None, "s", "changed", (), None, None, "s2"
    ) is False
    assert db.count_posts(conn) == 1
    row = conn.execute("SELECT body FROM posts WHERE msg_id = 'p1'").fetchone()
    assert row["body"] == "first"


def test_stores_reply_and_image_fields():
    conn = make_conn()
    db.insert_post(
        conn, "p2", "t", 2, "900", "root subj", "", "reply body",
        (), "abc.gif", "data/images/abc.gif", "s",
    )
    row = conn.execute("SELECT * FROM posts WHERE msg_id = 'p2'").fetchone()
    assert row["level"] == 2
    assert row["root_subject"] == "root subj"
    assert row["image_file_name"] == "abc.gif"
    assert row["image_local_path"] == "data/images/abc.gif"


def test_connect_creates_parent_directory(tmp_path):
    db_file = tmp_path / "nested" / "sub" / "hadar.sqlite3"
    conn = db.connect(str(db_file))
    db.init_db(conn)
    assert db_file.parent.exists()
    assert db.count_posts(conn) == 0


def test_insert_stores_signal_json():
    conn = make_conn()
    db.insert_post(
        conn, "p3", "t", 1, "900", None, "s", "body", (), None, None, "s1",
        signal_json='{"is_signal": true, "action": "add"}',
    )
    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='p3'").fetchone()
    assert row["signal_json"] == '{"is_signal": true, "action": "add"}'


def test_insert_signal_json_defaults_to_none():
    conn = make_conn()
    db.insert_post(conn, "p4", "t", 1, "900", None, "s", "body", (), None, None, "s1")
    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='p4'").fetchone()
    assert row["signal_json"] is None


def test_init_db_migrates_table_created_before_signal_json_existed():
    conn = db.connect(":memory:")
    # Simulate a pre-Phase-2 database: the exact CREATE TABLE Phase 1 shipped,
    # with no signal_json column.
    conn.executescript(
        """
        CREATE TABLE posts (
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
    )
    conn.commit()
    columns_before = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    assert "signal_json" not in columns_before

    db.init_db(conn)  # must not raise, and must add the missing column

    columns_after = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    assert "signal_json" in columns_after
    assert db.insert_post(conn, "p5", "t", 1, "900", None, "s", "b", (), None, None, "s1") is True
