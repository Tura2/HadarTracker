from hadar_tracker.models import Post


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
