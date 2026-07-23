import json
import pathlib
from dataclasses import replace as dataclasses_replace

import pytest

from hadar_tracker import check, db, notify_filter
from hadar_tracker.config import Config
from hadar_tracker.models import Post, Signal
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

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append((subject, tags, body, root_subject, image_path))

    def fake_download(msg_file_name, images_dir):
        downloaded.append((msg_file_name, images_dir))
        return f"{images_dir}/{msg_file_name}"

    posts = [
        Post("1001", "2026-01-05T10:00:00", 1, "900", "טבע", "no image", ("TEVA",)),
        Post("1002", "2026-01-05T10:05:00", 2, "900", "", "has image", (), root_subject="טבע",
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
    db.insert_post(conn, "1001", "2026-01-05T10:00:00", 1, "900", None, "s", "old", (), None, None, "s1")
    sent = []

    posts = [Post("1001", "2026-01-05T10:00:00", 1, "900", "s", "old", ())]
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

    posts = [Post("1001", "2026-01-05T10:00:00", 1, "900", "s", "old", ())]

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

    def flaky_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append(subject)
        if subject == "second":
            raise RuntimeError("telegram api error")

    posts = [
        Post("1001", "2026-01-05T10:00:00", 1, "900", "first", "body1", ()),
        Post("1002", "2026-01-05T10:05:00", 2, "900", "second", "body2", ()),
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


def test_process_suppresses_low_signal_reply_to_other_thread_but_still_persists(tmp_path):
    # A reply into someone else's thread, with no image/tag, classified as
    # not a real signal, must be gated out of Telegram entirely (see
    # notify_filter.should_notify) — but it's still genuinely new, so it
    # must still be persisted/marked seen rather than reprocessed forever.
    conn = make_conn()
    config = make_config(tmp_path)
    # Root of thread "900" is authored by someone else — no own_root row for
    # it exists in this fresh DB, so classify_bucket falls back to reply_other.
    posts = [Post("1001", "2026-01-05T10:00:00", 2, "900", "s", "not much", ())]
    sent = []

    new = check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=lambda *a, **k: sent.append(a),
        classify=lambda *a, **k: Signal(
            is_signal=False, ticker_mentioned=None, ticker_guess=None,
            action="none", conviction="low", price_levels=None, rationale="",
        ),
    )

    assert sent == []
    assert [p.msg_id for p in new] == ["1001"]
    assert db.post_exists(conn, "1001") is True


def test_process_passes_after_hours_flag_for_post_outside_market_window(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append(after_hours)

    # level=1 (own_root) always notifies, regardless of signal — isolates
    # the after_hours wiring from the should_notify gating tested above.
    posts = [Post("1001", "2026-01-05T22:00:00", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert sent == [True]


def test_process_passes_thread_url_built_from_forum_id_and_msg_id(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append(thread_url)

    posts = [Post("1001", "2026-01-05T10:00:00", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert sent == ["https://www.sponser.co.il/Forum.aspx?ForumId=1&MsgId=1001"]


def test_process_sends_to_every_notify_chat_id(tmp_path):
    config = dataclasses_replace(make_config(tmp_path), telegram_extra_chat_ids=("99", "100"))
    conn = make_conn()
    sent_chat_ids = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent_chat_ids.append(chat_id)

    posts = [Post("1001", "2026-01-05T10:00:00", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert sent_chat_ids == ["42", "99", "100"]


def test_process_dedupes_notify_chat_ids_when_extra_matches_primary(tmp_path):
    config = dataclasses_replace(make_config(tmp_path), telegram_extra_chat_ids=("42", "99"))
    conn = make_conn()
    sent_chat_ids = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent_chat_ids.append(chat_id)

    posts = [Post("1001", "2026-01-05T10:00:00", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert sent_chat_ids == ["42", "99"]  # "42" not repeated


def test_process_sends_post_immediately_even_when_found_after_hours(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []

    # level=1 (own_root) always notifies — isolates the immediate-send
    # behavior from should_notify gating tested elsewhere.
    posts = [Post("1001", "2026-01-05T22:00:00", 1, "900", "s", "b", ())]
    new = check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=lambda *a, **k: sent.append(a),
    )

    assert len(sent) == 1
    assert [p.msg_id for p in new] == ["1001"]
    assert db.post_exists(conn, "1001") is True
    row = conn.execute("SELECT notified FROM posts WHERE msg_id='1001'").fetchone()
    assert row["notified"] == 1


def test_process_flushes_pending_posts_labeled_after_hours_when_market_reopens(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)

    # Simulate a post held by a previous (market-closed) run.
    db.insert_post(
        conn, "1001", "2026-01-05T22:00:00", 1, "900", None, "held subject",
        "held body", ("TEVA",), None, None, "2026-01-05T22:00:00",
        signal_json=None, notified=False,
    )

    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append((subject, tags, body, after_hours))

    new = check.process_new_posts(
        conn, config, [],  # no newly-scraped posts this run — just the flush
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert new == []
    assert sent == [("held subject", ("TEVA",), "held body", True)]
    row = conn.execute("SELECT notified FROM posts WHERE msg_id='1001'").fetchone()
    assert row["notified"] == 1


def test_process_flush_passes_thread_url_for_pending_post(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    db.insert_post(
        conn, "1001", "2026-01-05T22:00:00", 1, "900", None, "held subject",
        "held body", (), None, None, "2026-01-05T22:00:00",
        signal_json=None, notified=False,
    )
    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append(thread_url)

    check.process_new_posts(
        conn, config, [],
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert sent == ["https://www.sponser.co.il/Forum.aspx?ForumId=1&MsgId=1001"]


def test_process_flush_sends_to_every_notify_chat_id(tmp_path):
    config = dataclasses_replace(make_config(tmp_path), telegram_extra_chat_ids=("99",))
    conn = make_conn()
    db.insert_post(
        conn, "1001", "2026-01-05T22:00:00", 1, "900", None, "s", "b", (),
        None, None, "2026-01-05T22:00:00", signal_json=None, notified=False,
    )
    sent_chat_ids = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent_chat_ids.append(chat_id)

    check.process_new_posts(
        conn, config, [],
        download=lambda *a, **k: None,
        send_post=fake_send,
    )

    assert sent_chat_ids == ["42", "99"]


def test_run_check_success_path(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    # run_check reads the real clock via notify_filter.is_market_hours_now
    # to decide immediate-send vs hold-for-later; pin it so this test is
    # deterministic regardless of what time it actually is when run.
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: True)
    fetched = [Post("2001", "2026-01-05T10:00:00", 1, "900", "טבע", "brand new post", ("TEVA",))]
    monkeypatch.setattr(client, "fetch_posts", lambda **k: fetched)
    sent = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_post",
        lambda token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None: sent.append(body),
    )
    rc = check.run_check(config)
    assert rc == 0
    assert sent == ["brand new post"]


def test_run_check_error_alert_only_goes_to_primary_chat_id(tmp_path, monkeypatch):
    # Someone subscribing via telegram_extra_chat_ids gets Hadar's posts,
    # not the admin's scraper-failure alerts — those stay on telegram_chat_id
    # alone, regardless of how many extra recipients are configured.
    config = dataclasses_replace(make_config(tmp_path), telegram_extra_chat_ids=("99", "100"))
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: True)

    def boom(**k):
        raise parse.ScrapeError("shape changed")

    monkeypatch.setattr(client, "fetch_posts", boom)
    alert_calls = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_alert",
        lambda token, chat_id, message: alert_calls.append(chat_id),
    )
    rc = check.run_check(config)
    assert rc == 1
    assert alert_calls == ["42"]


def test_run_check_reports_failure_and_alerts(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: True)

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
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: True)
    fetched = [Post("3001", "2026-01-05T10:00:00", 1, "900", "טבע", "brand new post", ("TEVA",))]
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


def _make_file_config(tmp_path):
    # A real sqlite file, not ":memory:" — needed here so a connection made
    # in the test setup and the separate connection run_check opens
    # internally actually see the same persisted state (two ":memory:"
    # connections would each get their own empty, unrelated database).
    return Config(
        db_path=str(tmp_path / "test.sqlite3"),
        images_dir=str(tmp_path / "images"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        user_id=5609,
        forum_id=1,
    )


def test_run_check_skips_scrape_when_offhours_check_ran_recently(tmp_path, monkeypatch):
    config = _make_file_config(tmp_path)
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: False)
    calls = []
    monkeypatch.setattr(client, "fetch_posts", lambda **k: calls.append(1) or [])

    # Pre-seed a last_offhours_check timestamp from just now, so the
    # throttle sees "checked recently" when run_check opens its own
    # connection to the same file.
    from datetime import datetime
    conn = db.connect(config.db_path)
    db.init_db(conn)
    db.set_meta(conn, "last_offhours_check", datetime.now(notify_filter.IL_TZ).isoformat())

    rc = check.run_check(config)

    assert rc == 0
    assert calls == []  # scrape never happened — throttled


def test_run_check_runs_offhours_check_when_none_ran_yet(tmp_path, monkeypatch):
    config = _make_file_config(tmp_path)
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: False)
    monkeypatch.setattr(client, "fetch_posts", lambda **k: [])

    rc = check.run_check(config)

    assert rc == 0
    conn = db.connect(config.db_path)
    db.init_db(conn)
    assert db.get_meta(conn, "last_offhours_check") is not None


class _FakeResponse:
    """Same shape as tests/test_client.py's FakeResponse — reused here so the
    real fetch_raw/fetch_posts/parse_posts chain runs unmodified; only the
    `requests` module they call through is faked."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRequests:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return self.response


def test_run_check_end_to_end_through_real_parser(tmp_path, monkeypatch):
    """Full pipeline test with only the network and Telegram/image-download
    boundaries faked.

    Every existing test in this file monkeypatches client.fetch_posts
    directly with hand-built Post objects, so the real parse_posts field
    mapping (scraper/parse.py) is never exercised in the same test that also
    drives check.py/db.py. Here we fake `hadar_tracker.scraper.client.requests`
    instead, so fetch_raw -> fetch_posts -> parse_posts all run for real
    against the same tests/fixtures/sample_stream.json fixture that
    tests/test_parse.py already pins down field-by-field. That guards against
    a Post field rename on the parser side silently breaking the
    check/db/notifier side, which independently-mocked halves can't catch.
    """
    monkeypatch.setattr(notify_filter, "is_market_hours_now", lambda: True)
    payload = json.loads(
        pathlib.Path("tests/fixtures/sample_stream.json").read_text(encoding="utf-8")
    )
    fake_requests = _FakeRequests(_FakeResponse(payload))
    monkeypatch.setattr(client, "requests", fake_requests)

    db_path = str(tmp_path / "hadar.sqlite3")
    config = Config(
        db_path=db_path,
        images_dir=str(tmp_path / "images"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        user_id=5609,
        forum_id=1,
    )

    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append((subject, tags, body, root_subject, image_path))

    monkeypatch.setattr("hadar_tracker.notifier.send_post", fake_send)

    downloaded = []

    def fake_download(msg_file_name, images_dir):
        downloaded.append((msg_file_name, images_dir))
        return f"{images_dir}/{msg_file_name}"

    monkeypatch.setattr("hadar_tracker.images.download_image", fake_download)

    rc = check.run_check(config)

    assert rc == 0

    # Same 4 Hadar-authored msg_ids that
    # tests/test_parse.py::test_parse_filters_to_hadar_only already
    # establishes for this exact fixture via the real parser alone — grounds
    # this test's expectation in the parser's own already-verified behavior.
    conn = db.connect(db_path)  # db.connect sets row_factory = sqlite3.Row
    rows = conn.execute("SELECT msg_id, root_subject FROM posts ORDER BY msg_id").fetchall()
    assert [r["msg_id"] for r in rows] == ["5001", "5002", "5004", "5006"]

    # 5006's thread root (L1=902) is authored by a *different* user (8888) —
    # tests/test_parse.py::test_parse_reply_resolves_root_subject_when_root_is_another_user
    # proves parse_posts resolves this correctly in isolation; asserting it
    # here proves that root_subject value survives the real parser -> DB
    # round trip through the whole pipeline, not just an isolated parse call.
    root_subjects = {r["msg_id"]: r["root_subject"] for r in rows}
    assert root_subjects["5006"] == "פועלים"
    assert root_subjects["5002"] == "תל אביב 35"
    assert root_subjects["5001"] is None

    # The one attachment in the fixture (on msg 5002) went through the faked
    # download boundary, and the resulting local path made it into both the
    # Telegram send call and the DB row.
    assert downloaded == [("c310bc13-abcd.gif", config.images_dir)]
    expected_path = f"{config.images_dir}/c310bc13-abcd.gif"
    image_row = conn.execute(
        "SELECT image_local_path FROM posts WHERE msg_id='5002'"
    ).fetchone()
    assert image_row["image_local_path"] == expected_path
    assert any(entry[4] == expected_path for entry in sent)
    assert len(sent) == 4

    # No OPENROUTER_API_KEY configured in this test's Config, so
    # classify_post short-circuits to None for every post — the whole real
    # pipeline (parser -> check -> db) must stay fully inert for Phase 2
    # when no key is set, exactly like Phase 1 behaved.
    signal_rows = conn.execute("SELECT signal_json FROM posts").fetchall()
    assert all(row["signal_json"] is None for row in signal_rows)


def test_process_calls_classify_with_post_image_path_and_config_and_persists_signal(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    calls = []

    def fake_classify(post, image_path, api_key, model, vision_model=None):
        calls.append((post.msg_id, image_path, api_key, model))
        return Signal(
            is_signal=True,
            ticker_mentioned="Aerodrome",
            ticker_guess="ARDM",
            action="add",
            conviction="medium",
            price_levels="close above 460",
            rationale="expects breakout",
        )

    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None, after_hours=False, thread_url=None):
        sent.append(signal)

    posts = [Post("2001", "2026-01-05T10:00:00", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=fake_send,
        classify=fake_classify,
    )

    assert calls == [("2001", None, config.openrouter_api_key, config.openrouter_model)]
    assert sent[0].action == "add"
    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='2001'").fetchone()
    stored = json.loads(row["signal_json"])
    assert stored["action"] == "add"
    assert stored["ticker_guess"] == "ARDM"


def test_process_persists_null_signal_json_when_classify_returns_none(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)

    posts = [Post("2002", "2026-01-05T10:00:00", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=lambda *a, **k: None,
        classify=lambda *a, **k: None,
    )

    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='2002'").fetchone()
    assert row["signal_json"] is None
