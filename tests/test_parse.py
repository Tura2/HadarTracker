import json
import pathlib

import pytest

from hadar_tracker.scraper.parse import (
    HADAR_USER_ID,
    ScrapeError,
    extract_tags,
    parse_date,
    parse_posts,
)

PAYLOAD = json.loads(
    pathlib.Path("tests/fixtures/sample_stream.json").read_text(encoding="utf-8")
)


def test_hadar_user_id_constant():
    assert HADAR_USER_ID == 5609


def test_parse_date_converts_israeli_format_to_iso():
    assert parse_date("21/07/26 | 10:32") == "2026-07-21T10:32:00"


def test_extract_tags_from_delimited_string():
    assert extract_tags("TEVA, ICL") == ("TEVA", "ICL")
    assert extract_tags("") == ()
    assert extract_tags(None) == ()


def test_extract_tags_from_list_of_strings_and_dicts():
    assert extract_tags(["TEVA", "ICL"]) == ("TEVA", "ICL")
    assert extract_tags([{"Symbol": "TEVA"}, {"Symbol": "ICL"}]) == ("TEVA", "ICL")


def test_parse_filters_to_hadar_only():
    posts = parse_posts(PAYLOAD)
    assert [p.msg_id for p in posts] == ["5001", "5002", "5004", "5006"]


def test_parse_root_post_fields():
    posts = parse_posts(PAYLOAD)
    root = posts[0]
    assert root.msg_id == "5001"
    assert root.level == 1
    assert root.thread_group == "900"
    assert root.root_subject is None
    assert root.subject == "תל אביב 35"
    assert root.posted_at == "2026-07-21T10:32:00"
    assert root.tags == ("TA35",)
    assert root.image_file_name is None


def test_parse_reply_resolves_root_subject_and_image():
    posts = parse_posts(PAYLOAD)
    reply = posts[1]
    assert reply.msg_id == "5002"
    assert reply.level == 2
    assert reply.root_subject == "תל אביב 35"
    assert reply.image_file_name == "c310bc13-abcd.gif"
    assert reply.image_local_path is None


def test_parse_multi_ticker_post():
    posts = parse_posts(PAYLOAD)
    teva = posts[2]
    assert teva.msg_id == "5004"
    assert teva.tags == ("TEVA", "ICL")


def test_parse_reply_resolves_root_subject_when_root_is_another_user():
    # Thread L1=900 root is authored by Hadar, so a naive implementation that
    # only scans Hadar's own items to build root_subjects would still pass
    # there. This thread (L1=902) has its Level==1 root authored by a
    # *different* user (8888), with Hadar only posting the Level>1 reply
    # (5006). This proves root_subjects is built from ALL items, not just
    # Hadar's filtered posts.
    posts = parse_posts(PAYLOAD)
    reply = next(p for p in posts if p.msg_id == "5006")
    assert reply.level == 2
    assert reply.thread_group == "902"
    assert reply.root_subject == "פועלים"


def test_parse_raises_when_data_key_missing():
    with pytest.raises(ScrapeError):
        parse_posts({"NumberOfPages": 0})


def test_parse_empty_data_returns_empty_list():
    assert parse_posts({"Data": []}) == []


def test_parse_reply_thread_transcript_includes_prior_items_up_to_itself():
    posts = parse_posts(PAYLOAD)
    reply = next(p for p in posts if p.msg_id == "5002")
    # L1=900 in the fixture: 5001 (10:32, hadar, root), 5002 (11:00, hadar),
    # 5003 (11:05, user 9999). 5002's transcript should include itself and
    # the earlier root, but NOT 5003, which comes after it.
    assert [ti.posted_at for ti in reply.thread_transcript] == [
        "2026-07-21T10:32:00", "2026-07-21T11:00:00",
    ]
    assert reply.thread_transcript[0].author == "hadar"
    assert reply.thread_transcript[0].subject == "תל אביב 35"
    assert reply.thread_transcript[1].body == "מוסיף פוזיציה, גרף מצורף"


def test_parse_reply_thread_transcript_includes_other_users_root():
    posts = parse_posts(PAYLOAD)
    reply = next(p for p in posts if p.msg_id == "5006")
    # L1=902's root (5005) is authored by a different user (8888) — proves
    # the transcript captures cross-user thread items, not just Hadar's own,
    # mirroring the existing root_subject cross-user invariant above.
    assert len(reply.thread_transcript) == 2
    root_item, own_item = reply.thread_transcript
    assert root_item.author == "other"
    assert root_item.subject == "פועלים"
    assert root_item.body == "מה דעתכם על הבנק"
    assert own_item.author == "hadar"
    assert own_item.body == "מסכים עם הניתוח, נראה חיובי"


def test_parse_root_post_thread_transcript_is_just_itself():
    posts = parse_posts(PAYLOAD)
    root = posts[0]  # msg_id 5001, L1=900, the thread's own root
    assert len(root.thread_transcript) == 1
    assert root.thread_transcript[0].author == "hadar"
    assert root.thread_transcript[0].subject == "תל אביב 35"


def test_parse_thread_transcript_is_sorted_even_when_payload_order_is_not():
    # history.py's page_id=0 bucket is documented as mixed-date/non-chronological,
    # and backfill.py feeds that payload straight into parse_posts, so
    # thread_transcript can't just trust payload order — it must be explicitly
    # sorted by posted_at. Here the later post (12:00) appears FIRST in the
    # payload and the earlier root (09:00) appears SECOND.
    payload = {
        "Data": [
            {
                "MsgId": 7002,
                "DateCreated": "21/07/26 | 12:00",
                "Level": 2,
                "L1": 950,
                "subject": "",
                "Msg": "second reply, listed first in payload",
                "Tags": "",
                "HasImages": 0,
                "MsgFileName": None,
                "User": {"UserId": 5609},
            },
            {
                "MsgId": 7001,
                "DateCreated": "21/07/26 | 09:00",
                "Level": 1,
                "L1": 950,
                "subject": "נושא",
                "Msg": "root post, listed second in payload but earlier",
                "Tags": "",
                "HasImages": 0,
                "MsgFileName": None,
                "User": {"UserId": 5609},
            },
        ],
        "NumberOfPages": 0,
        "IsMoreMsg": 0,
    }
    posts = parse_posts(payload)
    reply = next(p for p in posts if p.msg_id == "7002")
    assert [ti.posted_at for ti in reply.thread_transcript] == [
        "2026-07-21T09:00:00", "2026-07-21T12:00:00",
    ]


def test_parse_skips_malformed_other_user_item_in_thread_scan_without_crashing():
    # Finding 3 regression: a malformed Level/DateCreated on some OTHER
    # user's post (not Hadar's) in the same thread group must not crash the
    # whole parse_posts call — Phase 1 never even looked at those fields for
    # non-Hadar items, and Phase 2's thread-transcript scan shouldn't newly
    # depend on their validity. The malformed item is simply skipped from
    # the transcript; Hadar's own post still parses fine.
    payload = {
        "Data": [
            {
                "MsgId": 8001,
                "DateCreated": "21/07/26 | 09:00",
                "Level": 1,
                "L1": 960,
                "subject": "נושא אחר",
                "Msg": "root post by someone else",
                "Tags": "",
                "HasImages": 0,
                "MsgFileName": None,
                "User": {"UserId": 4242},
            },
            {
                "MsgId": 8002,
                # Malformed DateCreated on a non-Hadar post sharing the thread.
                "DateCreated": "not-a-date",
                "Level": 2,
                "L1": 960,
                "subject": "",
                "Msg": "malformed reply by someone else",
                "Tags": "",
                "HasImages": 0,
                "MsgFileName": None,
                "User": {"UserId": 4242},
            },
            {
                "MsgId": 8003,
                "DateCreated": "21/07/26 | 10:00",
                "Level": 2,
                "L1": 960,
                "subject": "",
                "Msg": "hadar's reply",
                "Tags": "",
                "HasImages": 0,
                "MsgFileName": None,
                "User": {"UserId": 5609},
            },
        ],
        "NumberOfPages": 0,
        "IsMoreMsg": 0,
    }
    posts = parse_posts(payload)
    reply = next(p for p in posts if p.msg_id == "8003")
    assert reply.body == "hadar's reply"
    transcript_bodies = [ti.body for ti in reply.thread_transcript]
    assert "malformed reply by someone else" not in transcript_bodies
    assert "root post by someone else" in transcript_bodies
    assert "hadar's reply" in transcript_bodies
