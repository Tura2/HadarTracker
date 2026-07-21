import pytest

from hadar_tracker import images


class FakeResponse:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response


def test_download_image_writes_file_and_returns_path(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"\x89PNG\r\nfake"))
    monkeypatch.setattr(images, "requests", fake)
    dest = images.download_image("abc123.gif", str(tmp_path / "imgs"))
    assert dest.endswith("abc123.gif")
    with open(dest, "rb") as handle:
        assert handle.read() == b"\x89PNG\r\nfake"
    assert fake.calls[0]["url"] == images.IMAGE_BASE + "abc123.gif"


def test_download_image_raises_on_http_error(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"", status=404))
    monkeypatch.setattr(images, "requests", fake)
    with pytest.raises(RuntimeError):
        images.download_image("missing.gif", str(tmp_path / "imgs"))
