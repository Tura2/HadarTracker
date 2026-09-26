import json
import pathlib

import pytest

from hadar_tracker.scraper import client
from hadar_tracker.scraper.parse import ScrapeError

PAYLOAD = json.loads(
    pathlib.Path("tests/fixtures/sample_stream.json").read_text(encoding="utf-8")
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, data=None, impersonate=None, timeout=None):
        self.calls.append({"url": url, "data": data, "impersonate": impersonate, "timeout": timeout})
        return self.response


def test_fetch_raw_posts_expected_form_body(monkeypatch):
    fake = FakeRequests(FakeResponse(PAYLOAD))
    monkeypatch.setattr(client, "requests", fake)
    result = client.fetch_raw(user_id=5609, forum_id=1)
    assert result == PAYLOAD
    call = fake.calls[0]
    assert call["url"] == client.ENDPOINT
    assert call["data"] == {"ForumId": 1, "IsFull": 1, "UserId": 5609, "m": 0}
    assert call["impersonate"] == client.IMPERSONATE


def test_fetch_raw_raises_on_http_error(monkeypatch):
    fake = FakeRequests(FakeResponse({}, status=500))
    monkeypatch.setattr(client, "requests", fake)
    with pytest.raises(RuntimeError):
        client.fetch_raw()


def test_fetch_raw_raises_blocked_error_on_403(monkeypatch):
    response = FakeResponse({}, status=403)
    response.headers = {"cf-mitigated": "challenge"}
    monkeypatch.setattr(client, "requests", FakeRequests(response))
    with pytest.raises(client.BlockedError, match="cf-mitigated: challenge"):
        client.fetch_raw()


def test_fetch_posts_returns_parsed_posts(monkeypatch):
    fake = FakeRequests(FakeResponse(PAYLOAD))
    monkeypatch.setattr(client, "requests", fake)
    posts = client.fetch_posts()
    assert [p.msg_id for p in posts] == ["5001", "5002", "5004", "5006"]


def test_fetch_posts_raises_when_no_posts(monkeypatch):
    fake = FakeRequests(FakeResponse({"Data": []}))
    monkeypatch.setattr(client, "requests", fake)
    with pytest.raises(ScrapeError):
        client.fetch_posts()
