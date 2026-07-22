import json

from hadar_tracker import signal
from hadar_tracker.models import Post, Signal, ThreadItem


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

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return self.response


def _openrouter_payload(content_dict):
    return {"choices": [{"message": {"content": json.dumps(content_dict)}}]}


def make_post(**overrides):
    fields = dict(
        msg_id="1", posted_at="2026-07-21T10:00:00", level=2, thread_group="900",
        subject="s", body="b", tags=(),
    )
    fields.update(overrides)
    return Post(**fields)


def test_classify_post_returns_none_when_no_api_key(monkeypatch):
    fake = FakeRequests(FakeResponse({}))
    monkeypatch.setattr(signal, "requests", fake)
    result = signal.classify_post(make_post(), None, api_key=None)
    assert result is None
    assert fake.calls == []


def test_classify_post_parses_well_formed_response(monkeypatch):
    fake = FakeRequests(
        FakeResponse(
            _openrouter_payload(
                {
                    "is_signal": True,
                    "ticker_mentioned": "Aerodrome",
                    "ticker_guess": "ARDM",
                    "action": "add",
                    "conviction": "medium",
                    "price_levels": "close above 460",
                    "rationale": "expects breakout",
                }
            )
        )
    )
    monkeypatch.setattr(signal, "requests", fake)

    result = signal.classify_post(make_post(), None, api_key="test-key")

    assert result == Signal(
        is_signal=True,
        ticker_mentioned="Aerodrome",
        ticker_guess="ARDM",
        action="add",
        conviction="medium",
        price_levels="close above 460",
        rationale="expects breakout",
    )
    assert fake.calls[0]["url"] == signal.OPENROUTER_ENDPOINT
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer test-key"


def test_classify_post_returns_none_on_http_error(monkeypatch):
    fake = FakeRequests(FakeResponse({}, status=500))
    monkeypatch.setattr(signal, "requests", fake)
    assert signal.classify_post(make_post(), None, api_key="k") is None


def test_classify_post_returns_none_on_malformed_json(monkeypatch):
    fake = FakeRequests(
        FakeResponse({"choices": [{"message": {"content": "not json"}}]})
    )
    monkeypatch.setattr(signal, "requests", fake)
    assert signal.classify_post(make_post(), None, api_key="k") is None


def test_classify_post_coerces_invalid_action_and_conviction_to_safe_defaults(monkeypatch):
    fake = FakeRequests(
        FakeResponse(
            _openrouter_payload({"is_signal": True, "action": "yolo", "conviction": "extreme"})
        )
    )
    monkeypatch.setattr(signal, "requests", fake)
    result = signal.classify_post(make_post(), None, api_key="k")
    assert result.action == "none"
    assert result.conviction == "low"


def test_classify_post_includes_image_content_block_when_image_path_set(monkeypatch, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(make_post(), str(img), api_key="k")

    content = fake.calls[0]["json"]["messages"][0]["content"]
    assert len(content) == 2
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_classify_post_proceeds_text_only_when_image_unreadable(monkeypatch):
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    result = signal.classify_post(make_post(), "/no/such/file.png", api_key="k")

    assert result is not None
    content = fake.calls[0]["json"]["messages"][0]["content"]
    assert len(content) == 1  # text only, image block skipped


def test_classify_post_uses_vision_model_when_image_present(monkeypatch, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(
        make_post(), str(img), api_key="k", model="deepseek/deepseek-v4-flash",
        vision_model="google/gemini-2.5-flash",
    )

    assert fake.calls[0]["json"]["model"] == "google/gemini-2.5-flash"


def test_classify_post_uses_text_model_when_no_image_even_with_vision_model_set(monkeypatch):
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(
        make_post(), None, api_key="k", model="deepseek/deepseek-v4-flash",
        vision_model="google/gemini-2.5-flash",
    )

    assert fake.calls[0]["json"]["model"] == "deepseek/deepseek-v4-flash"


def test_classify_post_falls_back_to_model_for_image_when_vision_model_unset(monkeypatch, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(make_post(), str(img), api_key="k", model="anthropic/claude-sonnet-4.5")

    assert fake.calls[0]["json"]["model"] == "anthropic/claude-sonnet-4.5"


def test_classify_post_uses_text_model_when_image_unreadable_even_with_vision_model_set(monkeypatch):
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(
        make_post(), "/no/such/file.png", api_key="k", model="deepseek/deepseek-v4-flash",
        vision_model="google/gemini-2.5-flash",
    )

    # Image was unreadable, so no image block was ever attached — must not
    # route to the vision model for a request that has no image in it.
    assert fake.calls[0]["json"]["model"] == "deepseek/deepseek-v4-flash"


def test_classify_post_includes_thread_transcript_in_prompt(monkeypatch):
    """Verify that thread_transcript with multiple ThreadItems is rendered in the LLM prompt."""
    transcript = (
        ThreadItem(
            author="other",
            level=1,
            subject="Initial discussion",
            body="What do you think?",
            posted_at="2026-07-21T09:00:00",
        ),
        ThreadItem(
            author="hadar",
            level=2,
            subject="RE: Initial discussion",
            body="I'm bullish on ARDM",
            posted_at="2026-07-21T09:30:00",
        ),
    )
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": True, "action": "buy", "conviction": "high"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(
        make_post(thread_transcript=transcript),
        None,
        api_key="k",
    )

    # Verify the prompt text contains thread context with author labels
    prompt_text = fake.calls[0]["json"]["messages"][0]["content"][0]["text"]
    assert "[Other user] Initial discussion: What do you think?" in prompt_text
    assert "[Hadar] RE: Initial discussion: I'm bullish on ARDM" in prompt_text
