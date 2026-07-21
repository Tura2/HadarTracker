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
