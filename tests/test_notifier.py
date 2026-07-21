import hadar_tracker.notifier as notifier


class FakeBot:
    """Records calls; supports `async with bot` like telegram.Bot."""

    last: dict = {}

    def __init__(self, token):
        FakeBot.last["token"] = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_message(self, chat_id, text):
        FakeBot.last["kind"] = "message"
        FakeBot.last["chat_id"] = chat_id
        FakeBot.last["text"] = text

    async def send_photo(self, chat_id, photo, caption):
        FakeBot.last["kind"] = "photo"
        FakeBot.last["chat_id"] = chat_id
        FakeBot.last["caption"] = caption


def test_format_message_root_post_with_tags():
    out = notifier.format_message("טבע", ("TEVA", "ICL"), "קונה טבע")
    assert out == "טבע\n🏷 TEVA, ICL\n\nקונה טבע"


def test_format_message_reply_has_context_line():
    out = notifier.format_message("", (), "מוסיף", root_subject="תל אביב 35")
    assert out == "↩️ Replying to: תל אביב 35\n\nמוסיף"


def test_format_message_body_only():
    assert notifier.format_message("", (), "just body") == "just body"


def test_send_post_text_only(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "טבע", ("TEVA",), "קונה טבע")
    assert FakeBot.last["kind"] == "message"
    assert FakeBot.last["chat_id"] == "42"
    assert FakeBot.last["token"] == "tok"
    assert "🏷 TEVA" in FakeBot.last["text"]


def test_send_post_with_image(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.gif"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "טבע", (), "עם גרף", image_path=str(img))
    assert FakeBot.last["kind"] == "photo"
    assert "עם גרף" in FakeBot.last["caption"]


def test_send_post_truncates_long_caption(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.gif"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "", (), "x" * 2000, image_path=str(img))
    assert len(FakeBot.last["caption"]) == 1024


def test_send_alert_prefixes_message(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_alert("tok", "42", "scraper run failed: boom")
    assert FakeBot.last["kind"] == "message"
    assert "scraper run failed: boom" in FakeBot.last["text"]
    assert "HadarTracker" in FakeBot.last["text"]
