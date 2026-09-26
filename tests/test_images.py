import os

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

    def get(self, url, impersonate=None, timeout=None):
        self.calls.append({"url": url, "impersonate": impersonate, "timeout": timeout})
        return self.response


def test_download_image_writes_file_and_returns_path(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"\x89PNG\r\nfake"))
    monkeypatch.setattr(images, "requests", fake)
    dest = images.download_image("abc123.gif", str(tmp_path / "imgs"))
    assert dest.endswith("abc123.gif")
    with open(dest, "rb") as handle:
        assert handle.read() == b"\x89PNG\r\nfake"
    assert fake.calls[0]["url"] == images.IMAGE_BASE + "abc123.gif"
    assert fake.calls[0]["impersonate"] == "chrome"


def test_download_image_raises_on_http_error(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"", status=404))
    monkeypatch.setattr(images, "requests", fake)
    with pytest.raises(RuntimeError):
        images.download_image("missing.gif", str(tmp_path / "imgs"))


def test_download_image_traversal_filename_confined_to_images_dir(tmp_path, monkeypatch):
    # os.path.basename strips leading "../" segments down to the final
    # component, so this resolves to a plain filename written INSIDE
    # images_dir rather than escaping to tmp_path/etc/passwd.
    fake = FakeRequests(FakeResponse(b"evil"))
    monkeypatch.setattr(images, "requests", fake)
    images_dir = tmp_path / "imgs"
    escape_target = tmp_path / "etc" / "passwd"

    dest = images.download_image("../../etc/passwd", str(images_dir))

    assert os.path.dirname(os.path.abspath(dest)) == os.path.abspath(str(images_dir))
    assert not escape_target.exists()
    # The URL fetched from the remote site must still use the ORIGINAL
    # (unsanitized) filename so the correct remote attachment is retrieved.
    assert fake.calls[0]["url"] == images.IMAGE_BASE + "../../etc/passwd"


def test_download_image_absolute_path_filename_confined_to_images_dir(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"evil"))
    monkeypatch.setattr(images, "requests", fake)
    images_dir = tmp_path / "imgs"
    outside_dir = tmp_path / "outside"
    absolute_like = str(outside_dir / "evil.gif")

    dest = images.download_image(absolute_like, str(images_dir))

    assert os.path.dirname(os.path.abspath(dest)) == os.path.abspath(str(images_dir))
    assert not outside_dir.exists()


def test_download_image_rejects_bare_parent_reference(tmp_path, monkeypatch):
    # A bare ".." would, if unsanitized, make os.path.join(images_dir, "..")
    # resolve to images_dir's PARENT -- a genuine escape. This must be
    # rejected outright rather than silently written anywhere.
    fake = FakeRequests(FakeResponse(b"evil"))
    monkeypatch.setattr(images, "requests", fake)
    images_dir = tmp_path / "imgs"

    with pytest.raises(ValueError):
        images.download_image("..", str(images_dir))

    # No network call should even be attempted since the destination is
    # unsafe before any request is made.
    assert fake.calls == []


def test_download_image_normal_guid_filename_unaffected(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"\x89PNG\r\nfake"))
    monkeypatch.setattr(images, "requests", fake)
    guid_name = "3f9a1c2e-4b5d-4e6f-8a7b-9c0d1e2f3a4b.jpg"
    dest = images.download_image(guid_name, str(tmp_path / "imgs"))

    assert dest == str(tmp_path / "imgs" / guid_name)
    with open(dest, "rb") as handle:
        assert handle.read() == b"\x89PNG\r\nfake"
    assert fake.calls[0]["url"] == images.IMAGE_BASE + guid_name
