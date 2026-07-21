from datetime import datetime, timedelta

from hadar_tracker import backfill, db
from hadar_tracker.config import Config

HADAR_ID = 5609


def _fmt(dt: datetime) -> str:
    return dt.strftime("%d/%m/%y | %H:%M")


def _item(msg_id, days_ago, user_id=HADAR_ID, level=1, l1=None, **extra):
    now = datetime.now() - timedelta(days=days_ago)
    item = {
        "MsgId": msg_id,
        "User": {"UserId": user_id},
        "Level": level,
        "L1": l1 or msg_id,
        "subject": f"subject-{msg_id}",
        "Msg": f"body-{msg_id}",
        "Tags": [],
        "DateCreated": _fmt(now),
        "HasImages": False,
        "MsgFileName": None,
    }
    item.update(extra)
    return item


def make_config(tmp_path):
    return Config(
        db_path=str(tmp_path / "hadar.sqlite3"),
        images_dir=str(tmp_path / "images"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        user_id=HADAR_ID,
        forum_id=1,
    )


class _FakeHistory:
    """Maps page_id -> payload, records every call, no real network."""

    def __init__(self, pages: dict[int, dict]):
        self.pages = pages
        self.calls: list[int] = []

    def __call__(self, page_id, forum_id=1, timeout=30):
        self.calls.append(page_id)
        return self.pages[page_id]


def test_backfill_walks_backward_and_stops_past_cutoff(tmp_path):
    config = make_config(tmp_path)

    pages = {
        0: {"Data": [_item(9001, 0)], "Info": {"NumberOfPages": "10"}},
        9: {"Data": [_item(9002, 1), _item(8000, 1, user_id=1234)]},
        8: {"Data": [_item(9003, 3)]},
        7: {"Data": [_item(9004, 10)]},  # older than 5-day cutoff -> stop here
    }
    fetch = _FakeHistory(pages)

    rc = backfill.run_backfill(
        config, days=5, fetch_page=fetch, sleep=lambda _s: None
    )

    assert rc == 0
    conn = db.connect(config.db_path)
    # 9001 (page0), 9002 (page9) inserted; 9003 (page8) inserted; 9004 (page7)
    # excluded (older than cutoff), even though its page WAS processed.
    assert db.count_posts(conn) == 3
    assert db.post_exists(conn, "9001")
    assert db.post_exists(conn, "9002")
    assert db.post_exists(conn, "9003")
    assert not db.post_exists(conn, "9004")
    # Never went past the page that crossed the cutoff.
    assert 6 not in fetch.calls
    assert fetch.calls == [0, 9, 8, 7]


def test_backfill_is_idempotent_on_rerun(tmp_path):
    config = make_config(tmp_path)
    pages = {
        0: {"Data": [_item(9001, 0)], "Info": {"NumberOfPages": "3"}},
        2: {"Data": [_item(9002, 10)]},  # already past a 5-day cutoff -> stop
    }
    fetch = _FakeHistory(pages)

    rc1 = backfill.run_backfill(config, days=5, fetch_page=fetch, sleep=lambda _s: None)
    rc2 = backfill.run_backfill(config, days=5, fetch_page=fetch, sleep=lambda _s: None)

    assert rc1 == 0
    assert rc2 == 0
    conn = db.connect(config.db_path)
    assert db.count_posts(conn) == 1  # only 9001 (0 days ago); 9002 excluded, no duplicate


def test_backfill_respects_max_pages(tmp_path):
    config = make_config(tmp_path)
    pages = {
        0: {"Data": [_item(9001, 0)], "Info": {"NumberOfPages": "10"}},
        9: {"Data": [_item(9002, 1)]},
        8: {"Data": [_item(9003, 1)]},
    }
    fetch = _FakeHistory(pages)

    rc = backfill.run_backfill(
        config, days=30, max_pages=2, fetch_page=fetch, sleep=lambda _s: None
    )

    assert rc == 0
    assert fetch.calls == [0, 9]  # page0 counts as 1 page; stops before page 8
    conn = db.connect(config.db_path)
    assert db.count_posts(conn) == 2
    assert not db.post_exists(conn, "9003")


def test_backfill_downloads_attached_image(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    pages = {
        0: {
            "Data": [
                _item(9001, 0, HasImages=True, MsgFileName="chart.gif")
            ],
            "Info": {"NumberOfPages": "1"},
        },
    }
    fetch = _FakeHistory(pages)
    downloads = []

    def fake_download(msg_file_name, images_dir, timeout=30):
        downloads.append((msg_file_name, images_dir))
        return f"{images_dir}/{msg_file_name}"

    monkeypatch.setattr(backfill.images, "download_image", fake_download)

    rc = backfill.run_backfill(config, days=30, fetch_page=fetch, sleep=lambda _s: None)

    assert rc == 0
    assert downloads == [("chart.gif", config.images_dir)]
    conn = db.connect(config.db_path)
    row = conn.execute("SELECT image_local_path FROM posts WHERE msg_id = '9001'").fetchone()
    assert row["image_local_path"] == f"{config.images_dir}/chart.gif"


def test_backfill_returns_nonzero_and_logs_on_failure(tmp_path, caplog):
    config = make_config(tmp_path)

    def boom(page_id, forum_id=1, timeout=30):
        raise RuntimeError("connection reset")

    rc = backfill.run_backfill(config, days=5, fetch_page=boom, sleep=lambda _s: None)

    assert rc == 1
    assert any("connection reset" in r.message for r in caplog.records)


def test_backfill_never_notifies_via_telegram(tmp_path, monkeypatch):
    """Backfill is a historical import, not a live alert stream."""
    config = make_config(tmp_path)
    pages = {0: {"Data": [_item(9001, 0)], "Info": {"NumberOfPages": "1"}}}
    fetch = _FakeHistory(pages)

    called = []
    import hadar_tracker.notifier as notifier

    monkeypatch.setattr(notifier, "send_post", lambda *a, **k: called.append(a))
    monkeypatch.setattr(notifier, "send_alert", lambda *a, **k: called.append(a))

    backfill.run_backfill(config, days=30, fetch_page=fetch, sleep=lambda _s: None)

    assert called == []
