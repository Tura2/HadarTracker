from hadar_tracker.models import Post, Signal, ThreadItem


def test_post_defaults_are_none_for_optional_fields():
    p = Post(
        msg_id="1",
        posted_at="2026-07-21T10:00:00",
        level=1,
        thread_group="900",
        subject="s",
        body="b",
        tags=("TEVA",),
    )
    assert p.root_subject is None
    assert p.image_file_name is None
    assert p.image_local_path is None
    assert p.tags == ("TEVA",)


def test_post_is_frozen():
    import dataclasses

    p = Post(
        msg_id="1", posted_at="t", level=2, thread_group="900",
        subject="", body="b", tags=(),
    )
    try:
        p.msg_id = "2"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Post should be frozen")


def test_post_thread_transcript_defaults_to_empty_tuple():
    p = Post(
        msg_id="1", posted_at="t", level=2, thread_group="900",
        subject="", body="b", tags=(),
    )
    assert p.thread_transcript == ()


def test_post_thread_transcript_holds_thread_items():
    item = ThreadItem(
        author="other", level=1, subject="root subj", body="root body",
        posted_at="2026-07-21T10:00:00",
    )
    p = Post(
        msg_id="1", posted_at="2026-07-21T10:05:00", level=2, thread_group="900",
        subject="s", body="b", tags=(), thread_transcript=(item,),
    )
    assert p.thread_transcript == (item,)


def test_signal_holds_all_fields_and_is_frozen():
    import dataclasses

    s = Signal(
        is_signal=True,
        ticker_mentioned="Aerodrome",
        ticker_guess="ARDM",
        action="add",
        conviction="medium",
        price_levels="close above 460",
        rationale="expects breakout",
    )
    assert s.action == "add"
    assert s.ticker_guess == "ARDM"
    try:
        s.action = "sell"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Signal should be frozen")
