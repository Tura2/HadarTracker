import pytest

from hadar_tracker import check, db
from hadar_tracker.config import Config
from hadar_tracker.models import Post
from hadar_tracker.scraper import client, parse


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


def test_process_does_not_persist_post_when_send_fails(tmp_path):
    # If send_post raises (e.g. a real Telegram API error), the post must not
    # be committed to the DB — otherwise db.post_exists would mark it as
    # already seen and the notification would be permanently, silently lost
    # on the next run instead of being retried.
    conn = make_conn()
    config = make_config(tmp_path)

    def failing_send(*args, **kwargs):
        raise RuntimeError("telegram api error")

    posts = [Post("1001", "t1", 1, "900", "s", "old", ())]

    with pytest.raises(RuntimeError, match="telegram api error"):
        check.process_new_posts(
            conn, config, posts,
            download=lambda *a, **k: None,
            send_post=failing_send,
        )

    assert db.count_posts(conn) == 0
    assert db.post_exists(conn, "1001") is False


def test_process_keeps_earlier_successes_when_later_post_send_fails(tmp_path):
    # A failure partway through a batch must not roll back or lose posts
    # that were already successfully sent+inserted earlier in the same call.
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []

    def flaky_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None):
        sent.append(subject)
        if subject == "second":
            raise RuntimeError("telegram api error")

    posts = [
        Post("1001", "t1", 1, "900", "first", "body1", ()),
        Post("1002", "t2", 2, "900", "second", "body2", ()),
    ]

    with pytest.raises(RuntimeError, match="telegram api error"):
        check.process_new_posts(
            conn, config, posts,
            download=lambda *a, **k: None,
            send_post=flaky_send,
        )

    assert sent == ["first", "second"]
    # First post's send succeeded before the second failed, so it remains
    # committed; the second, whose send raised, was never persisted.
    assert db.count_posts(conn) == 1
    assert db.post_exists(conn, "1001") is True
    assert db.post_exists(conn, "1002") is False


def test_run_check_success_path(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    fetched = [Post("2001", "t", 1, "900", "טבע", "brand new post", ("TEVA",))]
    monkeypatch.setattr(client, "fetch_posts", lambda **k: fetched)
    sent = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_post",
        lambda token, chat_id, subject, tags, body, root_subject=None, image_path=None: sent.append(body),
    )
    rc = check.run_check(config)
    assert rc == 0
    assert sent == ["brand new post"]


def test_run_check_reports_failure_and_alerts(tmp_path, monkeypatch):
    config = make_config(tmp_path)

    def boom(**k):
        raise parse.ScrapeError("shape changed")

    monkeypatch.setattr(client, "fetch_posts", boom)
    alerts = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_alert",
        lambda token, chat_id, message: alerts.append(message),
    )
    rc = check.run_check(config)
    assert rc == 1
    assert len(alerts) == 1
    assert "shape changed" in alerts[0]


def test_run_check_reports_failure_and_alerts_when_processing_fails(tmp_path, monkeypatch, caplog):
    # A genuinely new post that fails to send (e.g. a real Telegram API
    # error) propagates out of process_new_posts by design (see its
    # docstring), but run_check must still fail loudly: log + alert + rc=1.
    # This is the gap the old code had — only the fetch_posts call was
    # guarded, so this exception used to escape run_check unhandled.
    config = make_config(tmp_path)
    fetched = [Post("3001", "t", 1, "900", "טבע", "brand new post", ("TEVA",))]
    monkeypatch.setattr(client, "fetch_posts", lambda **k: fetched)

    def failing_send(*args, **kwargs):
        raise RuntimeError("telegram api error")

    monkeypatch.setattr("hadar_tracker.notifier.send_post", failing_send)
    alerts = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_alert",
        lambda token, chat_id, message: alerts.append(message),
    )

    with caplog.at_level("ERROR"):
        rc = check.run_check(config)

    assert rc == 1
    assert len(alerts) == 1
    assert "telegram api error" in alerts[0]
    assert any("telegram api error" in record.message for record in caplog.records)
