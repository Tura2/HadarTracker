import hadar_tracker.notifier as notifier
from hadar_tracker.models import Signal


def sentinel(s: str) -> str:
    """format_message always appends a final invisible line (notifier._RLM)
    so the real content is never the message's literal last line — see the
    live-debugging notes above _RLM in notifier.py. Mirrors that here so
    expected strings stay readable instead of embedding it manually."""
    return s + "\n" + notifier._RLM


class FakeBot:
    """Records calls; supports `async with bot` like telegram.Bot."""

    last: dict = {}

    def __init__(self, token):
        FakeBot.last["token"] = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_message(self, chat_id, text, parse_mode=None):
        FakeBot.last["kind"] = "message"
        FakeBot.last["chat_id"] = chat_id
        FakeBot.last["text"] = text
        FakeBot.last["parse_mode"] = parse_mode

    async def send_photo(self, chat_id, photo, caption, parse_mode=None):
        FakeBot.last["kind"] = "photo"
        FakeBot.last["chat_id"] = chat_id
        FakeBot.last["caption"] = caption
        FakeBot.last["parse_mode"] = parse_mode


def test_format_message_root_post_with_tags():
    # Tags render in a footer block after the body, not between title and
    # reply-context — see format_message's docstring for why (a tag can be
    # a real stock that isn't actually what's discussed, and having it sit
    # in the middle broke up the reading flow right when a reader needs
    # the reply-context most).
    out = notifier.format_message("טבע", ("TEVA", "ICL"), "קונה טבע")
    assert out == sentinel("<b>כותרת:</b> טבע\n\n<b>תוכן:</b>\nקונה טבע\n\n🏷 TEVA, ICL")


def test_format_message_reply_context_comes_before_title():
    out = notifier.format_message("הכותרת שלי", (), "מוסיף", root_subject="תל אביב 35")
    assert out == sentinel(
        "<b>הגיב ל:</b> תל אביב 35\n<b>כותרת:</b> הכותרת שלי\n\n<b>תוכן:</b>\nמוסיף"
    )


def test_format_message_body_only():
    assert notifier.format_message("", (), "just body") == sentinel("<b>תוכן:</b>\njust body")


def test_format_message_replaces_known_emoji_code_in_body():
    out = notifier.format_message("", (), "אתה באמת ביביסט ללא מוח.|30|")
    assert out == sentinel("<b>תוכן:</b>\nאתה באמת ביביסט ללא מוח.😲")


def test_format_message_replaces_repeated_emoji_codes():
    out = notifier.format_message("", (), "וואלה|35||35|")
    assert out == sentinel("<b>תוכן:</b>\nוואלה🤔🤔")


def test_format_message_replaces_emoji_code_in_subject_and_root_subject():
    out = notifier.format_message("כותרת|1|", (), "גוף", root_subject="תגובה|36|")
    assert out.splitlines()[0] == "<b>הגיב ל:</b> תגובה❤️"
    assert "<b>כותרת:</b> כותרת🤣" in out


def test_format_message_drops_unknown_emoji_code():
    out = notifier.format_message("", (), "טקסט|99999|סוף")
    assert out == sentinel("<b>תוכן:</b>\nטקסטסוף")


def test_format_message_escapes_html_special_characters_in_body():
    out = notifier.format_message("", (), "if price > 460 & rising <now>")
    assert "&gt;" in out and "&amp;" in out and "&lt;now&gt;" in out
    assert "<now>" not in out


def test_format_message_collapses_undecoded_source_entities():
    # Regression: a real live subject line was "...לבדוק&nbsp;" — a literal,
    # undecoded HTML entity from Sponser's own scraped text. Escaping that
    # straight through turned its "&" into "&amp;", so Telegram rendered the
    # literal text "&nbsp;" instead of a space.
    out = notifier.format_message("כותרת&nbsp;", (), "b")
    assert "&nbsp;" not in out
    assert "&amp;nbsp;" not in out


def test_format_message_always_ends_with_invisible_sentinel_line():
    # Regression: a live message with a short Hebrew line ending in Latin
    # digits (e.g. a stop-loss price) rendered left-aligned specifically
    # when it was the message's literal last line — confirmed by testing on
    # real Telegram messages. The fix isn't a bidi control character; it's
    # ensuring the body is never actually the terminal line.
    out = notifier.format_message("", (), "סטופ 4230")
    lines = out.split("\n")
    assert lines[-1] == notifier._RLM
    assert lines[-2] == "סטופ 4230"


def test_format_message_renders_thread_url_as_hyperlink():
    out = notifier.format_message("s", (), "b", thread_url="https://www.sponser.co.il/Forum.aspx?ForumId=1&MsgId=123")
    assert out.endswith(
        '🔗 <a href="https://www.sponser.co.il/Forum.aspx?ForumId=1&amp;MsgId=123">Link</a>'
    )
    assert notifier._RLM not in out  # link line replaces the invisible fallback


def test_build_thread_url_format():
    assert notifier.build_thread_url(1, "8966582") == (
        "https://www.sponser.co.il/Forum.aspx?ForumId=1&MsgId=8966582"
    )


def test_send_post_text_only(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "טבע", ("TEVA",), "קונה טבע")
    assert FakeBot.last["kind"] == "message"
    assert FakeBot.last["chat_id"] == "42"
    assert FakeBot.last["token"] == "tok"
    assert FakeBot.last["parse_mode"] == "HTML"
    assert "🏷 TEVA" in FakeBot.last["text"]


def test_send_post_with_image(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.gif"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "טבע", (), "עם גרף", image_path=str(img))
    assert FakeBot.last["kind"] == "photo"
    assert FakeBot.last["parse_mode"] == "HTML"
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
    assert out == sentinel(
        '<b>כותרת:</b> s\n\n<b>תוכן:</b>\nb\n\n🤖 Signal: ADD — ARDM 🟡\n'
        '   "close above 460 — expects breakout"'
    )


def test_format_message_omits_signal_section_when_is_signal_false():
    out = notifier.format_message("s", (), "b", signal=_signal(is_signal=False))
    assert out == sentinel("<b>כותרת:</b> s\n\n<b>תוכן:</b>\nb")


def test_format_message_omits_signal_section_when_signal_is_none():
    out = notifier.format_message("s", (), "b", signal=None)
    assert out == sentinel("<b>כותרת:</b> s\n\n<b>תוכן:</b>\nb")


def test_format_message_signal_without_ticker_guess_omits_dash():
    out = notifier.format_message("s", (), "b", signal=_signal(ticker_guess=None))
    assert "🤖 Signal: ADD 🟡" in out


def test_format_message_conviction_ball_high_is_green():
    out = notifier.format_message("s", (), "b", signal=_signal(conviction="high"))
    assert "🟢" in out


def test_format_message_conviction_ball_low_is_red():
    out = notifier.format_message("s", (), "b", signal=_signal(conviction="low"))
    assert "🔴" in out


def test_format_message_after_hours_label_is_first_line():
    out = notifier.format_message("s", (), "b", after_hours=True)
    assert out == sentinel("🌙 After Hours\n<b>כותרת:</b> s\n\n<b>תוכן:</b>\nb")


def test_format_message_no_after_hours_label_by_default():
    out = notifier.format_message("s", (), "b")
    assert "After Hours" not in out


def test_send_post_passes_after_hours_through_to_format_message(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "s", (), "b", after_hours=True)
    assert "🌙 After Hours" in FakeBot.last["text"]


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
        '🤖 Signal: ADD — ARDM 🟡\n'
        '   "close above 460 — expects breakout"'
    ) in caption
