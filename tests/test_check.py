from hadar_tracker import check, db
from hadar_tracker.config import Config
from hadar_tracker.models import Post


def make_config(tmp_path):
    return Config(
        db_path=":memory:",
        images_dir=str(tmp_path / "images"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        user_id=5609,
        forum_id=1,
    )


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_process_inserts_downloads_and_notifies(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []
    downloaded = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None):
        sent.append((subject, tags, body, root_subject, image_path))

    def fake_download(msg_file_name, images_dir):
        downloaded.append((msg_file_name, images_dir))
        return f"{images_dir}/{msg_file_name}"

    posts = [
        Post("1001", "t1", 1, "900", "טבע", "no image", ("TEVA",)),
        Post("1002", "t2", 2, "900", "", "has image", (), root_subject="טבע",
             image_file_name="pic.gif"),
    ]
    new = check.process_new_posts(
        conn, config, posts, download=fake_download, send_post=fake_send
    )

    assert [p.msg_id for p in new] == ["1001", "1002"]
    assert db.count_posts(conn) == 2
    # Only the second post had an attachment.
    assert downloaded == [("pic.gif", config.images_dir)]
    # The second notification carried the downloaded path and reply-context.
    assert sent[0] == ("טבע", ("TEVA",), "no image", None, None)
    assert sent[1][4] == f"{config.images_dir}/pic.gif"
    assert sent[1][3] == "טבע"
    # The image path was persisted.
    row = conn.execute("SELECT image_local_path FROM posts WHERE msg_id='1002'").fetchone()
    assert row["image_local_path"] == f"{config.images_dir}/pic.gif"


def test_process_skips_already_seen_posts(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    db.insert_post(conn, "1001", "t1", 1, "900", None, "s", "old", (), None, None, "s1")
    sent = []

    posts = [Post("1001", "t1", 1, "900", "s", "old", ())]
    new = check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: "x",
        send_post=lambda *a, **k: sent.append(a),
    )
    assert new == []
    assert sent == []
    assert db.count_posts(conn) == 1
