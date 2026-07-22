from datetime import datetime
from zoneinfo import ZoneInfo

from hadar_tracker import db, notify_filter
from hadar_tracker.models import Post, Signal, ThreadItem


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def _post(level, thread_group, thread_transcript=(), tags=(), image_file_name=None):
    return Post(
        msg_id="1", posted_at="2026-01-05T10:00:00", level=level,
        thread_group=thread_group, subject="s", body="b", tags=tags,
        image_file_name=image_file_name, thread_transcript=thread_transcript,
    )


def _signal(is_signal):
    return Signal(
        is_signal=is_signal, ticker_mentioned=None, ticker_guess=None,
        action="none", conviction="low", price_levels=None, rationale="",
    )


# --- classify_bucket ---

def test_classify_bucket_root_post_is_own_root():
    conn = make_conn()
    assert notify_filter.classify_bucket(_post(level=1, thread_group="1"), conn) == notify_filter.OWN_ROOT


def test_classify_bucket_reply_uses_transcript_when_root_is_hadar():
    conn = make_conn()
    transcript = (ThreadItem(author="hadar", level=1, subject="root", body="", posted_at="2026-01-05T09:00:00"),)
    post = _post(level=2, thread_group="1", thread_transcript=transcript)
    assert notify_filter.classify_bucket(post, conn) == notify_filter.REPLY_OWN


def test_classify_bucket_reply_uses_transcript_when_root_is_other():
    conn = make_conn()
    transcript = (ThreadItem(author="other", level=1, subject="root", body="", posted_at="2026-01-05T09:00:00"),)
    post = _post(level=2, thread_group="1", thread_transcript=transcript)
    assert notify_filter.classify_bucket(post, conn) == notify_filter.REPLY_OTHER


def test_classify_bucket_reply_falls_back_to_db_when_root_missing_from_transcript():
    conn = make_conn()
    db.insert_post(conn, "root1", "2026-01-05T09:00:00", 1, "1", None, "root", "b", (), None, None, "x")
    post = _post(level=2, thread_group="1")  # empty thread_transcript
    assert notify_filter.classify_bucket(post, conn) == notify_filter.REPLY_OWN


def test_classify_bucket_reply_defaults_to_reply_other_when_no_info_at_all():
    conn = make_conn()
    post = _post(level=2, thread_group="1")  # empty transcript, nothing in DB
    assert notify_filter.classify_bucket(post, conn) == notify_filter.REPLY_OTHER


# --- should_notify ---

def test_should_notify_own_root_always_true_even_with_suppressing_signal():
    post = _post(level=1, thread_group="1")
    assert notify_filter.should_notify(notify_filter.OWN_ROOT, post, _signal(is_signal=False)) is True


def test_should_notify_reply_with_image_passes_without_signal():
    post = _post(level=2, thread_group="1", image_file_name="chart.gif")
    assert notify_filter.should_notify(notify_filter.REPLY_OTHER, post, None) is True


def test_should_notify_reply_with_tag_passes_without_signal():
    post = _post(level=2, thread_group="1", tags=("TEVA",))
    assert notify_filter.should_notify(notify_filter.REPLY_OWN, post, None) is True


def test_should_notify_reply_with_no_signal_available_defaults_true():
    # Fail-open: classify_post returning None (no API key / call failed)
    # must never silently swallow a possibly-real post.
    post = _post(level=2, thread_group="1")
    assert notify_filter.should_notify(notify_filter.REPLY_OTHER, post, None) is True


def test_should_notify_reply_follows_signal_when_no_structural_signal():
    post = _post(level=2, thread_group="1")
    assert notify_filter.should_notify(notify_filter.REPLY_OTHER, post, _signal(is_signal=True)) is True
    assert notify_filter.should_notify(notify_filter.REPLY_OTHER, post, _signal(is_signal=False)) is False


# --- is_after_hours ---

def test_is_after_hours_false_within_window():
    assert notify_filter.is_after_hours("2026-01-05T09:30:00") is False
    assert notify_filter.is_after_hours("2026-01-05T13:00:00") is False
    assert notify_filter.is_after_hours("2026-01-05T17:30:00") is False


def test_is_after_hours_true_outside_window():
    assert notify_filter.is_after_hours("2026-01-05T09:29:00") is True
    assert notify_filter.is_after_hours("2026-01-05T17:31:00") is True
    assert notify_filter.is_after_hours("2026-01-05T03:00:00") is True


# --- is_market_hours_now ---

class _FixedDatetime(datetime):
    """Stand-in for the datetime class so is_market_hours_now can be tested
    without depending on the real wall-clock time it happens to run at."""
    _fixed: datetime

    @classmethod
    def now(cls, tz=None):
        return cls._fixed if tz is None else cls._fixed.astimezone(tz)


def _freeze_now(monkeypatch, iso_local: str) -> None:
    fixed = datetime.fromisoformat(iso_local).replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
    frozen = type("FrozenDatetime", (_FixedDatetime,), {"_fixed": fixed})
    monkeypatch.setattr(notify_filter, "datetime", frozen)


def test_is_market_hours_now_true_inside_window(monkeypatch):
    _freeze_now(monkeypatch, "2026-01-05T13:00:00")
    assert notify_filter.is_market_hours_now() is True


def test_is_market_hours_now_false_outside_window(monkeypatch):
    _freeze_now(monkeypatch, "2026-01-05T20:00:00")
    assert notify_filter.is_market_hours_now() is False


# --- db pending-post helpers ---

def test_fetch_pending_posts_returns_only_unnotified_rows_in_posted_at_order():
    conn = make_conn()
    db.insert_post(conn, "a", "2026-01-05T11:00:00", 1, "1", None, "s", "b", (), None, None, "x", notified=False)
    db.insert_post(conn, "b", "2026-01-05T09:00:00", 1, "2", None, "s", "b", (), None, None, "x", notified=False)
    db.insert_post(conn, "c", "2026-01-05T10:00:00", 1, "3", None, "s", "b", (), None, None, "x", notified=True)

    pending = db.fetch_pending_posts(conn)
    assert [row["msg_id"] for row in pending] == ["b", "a"]


def test_mark_notified_flips_the_flag():
    conn = make_conn()
    db.insert_post(conn, "a", "2026-01-05T11:00:00", 1, "1", None, "s", "b", (), None, None, "x", notified=False)
    db.mark_notified(conn, "a")
    assert db.fetch_pending_posts(conn) == []


# --- off-hours check throttle ---

def test_should_run_offhours_check_true_when_never_run():
    conn = make_conn()
    now = datetime.fromisoformat("2026-01-05T20:00:00").replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
    assert notify_filter.should_run_offhours_check(conn, now) is True


def test_should_run_offhours_check_false_within_an_hour():
    conn = make_conn()
    t0 = datetime.fromisoformat("2026-01-05T20:00:00").replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
    notify_filter.mark_offhours_check_ran(conn, t0)
    t1 = t0.replace(minute=59)
    assert notify_filter.should_run_offhours_check(conn, t1) is False


def test_should_run_offhours_check_true_after_an_hour():
    conn = make_conn()
    t0 = datetime.fromisoformat("2026-01-05T20:00:00").replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
    notify_filter.mark_offhours_check_ran(conn, t0)
    t1 = datetime.fromisoformat("2026-01-05T21:00:01").replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
    assert notify_filter.should_run_offhours_check(conn, t1) is True


# --- db meta key-value store ---

def test_get_meta_returns_none_when_unset():
    conn = make_conn()
    assert db.get_meta(conn, "nope") is None


def test_set_meta_then_get_meta_round_trips():
    conn = make_conn()
    db.set_meta(conn, "k", "v1")
    assert db.get_meta(conn, "k") == "v1"


def test_set_meta_overwrites_existing_value():
    conn = make_conn()
    db.set_meta(conn, "k", "v1")
    db.set_meta(conn, "k", "v2")
    assert db.get_meta(conn, "k") == "v2"
