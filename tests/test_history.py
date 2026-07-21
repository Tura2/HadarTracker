import pytest

from hadar_tracker.scraper import history


class _FakeResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeRequests:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return self._response


def test_fetch_history_page_builds_expected_request(monkeypatch):
    fake = _FakeRequests(_FakeResponse({"Data": [], "Info": {"NumberOfPages": "44493"}}))
    monkeypatch.setattr(history, "requests", fake)

    payload = history.fetch_history_page(page_id=44400, forum_id=1)

    assert payload["Info"]["NumberOfPages"] == "44493"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"] == history.HISTORY_ENDPOINT
    assert call["params"] == {"f": 1, "p": 44400}
    assert "HeadlessChrome" not in call["headers"]["User-Agent"]


def test_fetch_history_page_raises_on_http_error(monkeypatch):
    fake = _FakeRequests(_FakeResponse({}, status=403))
    monkeypatch.setattr(history, "requests", fake)

    with pytest.raises(RuntimeError):
        history.fetch_history_page(page_id=1, forum_id=1)
