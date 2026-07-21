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
    assert [p.msg_id for p in posts] == ["5001", "5002", "5004"]


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


def test_parse_raises_when_data_key_missing():
    with pytest.raises(ScrapeError):
        parse_posts({"NumberOfPages": 0})


def test_parse_empty_data_returns_empty_list():
    assert parse_posts({"Data": []}) == []
