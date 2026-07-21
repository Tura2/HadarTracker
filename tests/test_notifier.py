import hadar_tracker.notifier as notifier
from hadar_tracker.models import Signal


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


def _signal(**overrides):
    fields = dict(
        is_signal=True,
        ticker_mentioned="Aerodrome",
        ticker_guess="ARDM",
        action="add",
        conviction="medium",
        price_levels="close above 460",
        rationale="expects breakout",
    )
    fields.update(overrides)
    return Signal(**fields)


def test_format_message_appends_signal_section_when_is_signal_true():
    out = notifier.format_message("s", (), "b", signal=_signal())
    assert out == (
        's\n\nb\n\n🤖 Signal: ADD — ARDM (conviction: medium)\n'
        '   "close above 460 — expects breakout"'
    )


def test_format_message_omits_signal_section_when_is_signal_false():
    out = notifier.format_message("s", (), "b", signal=_signal(is_signal=False))
    assert out == "s\n\nb"


def test_format_message_omits_signal_section_when_signal_is_none():
    out = notifier.format_message("s", (), "b", signal=None)
    assert out == "s\n\nb"


def test_format_message_signal_without_ticker_guess_omits_dash():
    out = notifier.format_message("s", (), "b", signal=_signal(ticker_guess=None))
    assert "🤖 Signal: ADD (conviction: medium)" in out


def test_format_message_includes_price_levels_when_set():
    out = notifier.format_message("s", (), "b", signal=_signal(price_levels="close above 460"))
    assert "close above 460" in out
    # price_levels and rationale should both be visible, on the rationale line.
    assert '"close above 460 — expects breakout"' in out


def test_format_message_omits_price_levels_artifact_when_none():
    out = notifier.format_message("s", (), "b", signal=_signal(price_levels=None))
    assert '"expects breakout"' in out
    # No stray leading dash/separator when price_levels is absent.
    assert "— expects breakout" not in out
    assert '" — ' not in out


def test_send_post_passes_signal_through_to_format_message(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "s", (), "b", signal=_signal())
    assert "🤖 Signal: ADD" in FakeBot.last["text"]


def test_send_post_truncated_caption_still_contains_full_signal_section(monkeypatch, tmp_path):
    # Regression for finding 1: a long image-post body must not push the
    # signal section (the whole point of Phase 2) off the end of the
    # 1024-char Telegram photo caption. The body should shrink instead.
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.gif"
    img.write_bytes(b"\x89PNG\r\n")
    signal = _signal()
    notifier.send_post(
        "tok", "42", "s", (), "x" * 2000, image_path=str(img), signal=signal
    )
    caption = FakeBot.last["caption"]
    assert len(caption) <= 1024
    assert (
        '🤖 Signal: ADD — ARDM (conviction: medium)\n'
        '   "close above 460 — expects breakout"'
    ) in caption
