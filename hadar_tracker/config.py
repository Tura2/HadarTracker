from __future__ import annotations

import os
from dataclasses import dataclass

# Retained for reference / the throwaway Task-2 inspection script. The app no
# longer scrapes this HTML page — it hits the JSON endpoint (see scraper/client).
DEFAULT_FORUM_URL = (
    "https://www.sponser.co.il/ForumViewUserMessages.aspx"
    "?UserId=5609&ForumId=1&IsFull=1"
)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    db_path: str
    images_dir: str
    telegram_bot_token: str
    telegram_chat_id: str
    user_id: int
    forum_id: int
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_vision_model: str | None = None
    # Extra recipients for POST notifications only — never error alerts,
    # which always go to telegram_chat_id alone (see check.py's alert()).
    # Lets more people subscribe to Hadar's posts without also being woken
    # up by a scraper failure that's the admin's problem to fix, not theirs.
    telegram_extra_chat_ids: tuple[str, ...] = ()


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Raises ConfigError (loudly) if a required variable is missing, so a
    misconfigured cron run fails fast instead of silently doing nothing.
    OPENROUTER_API_KEY is intentionally NOT required — Phase 2 (LLM trade-
    signal classification) is additive; with no key set, classify_post
    short-circuits to None and the pipeline behaves exactly as Phase 1 did.
    """
    source = os.environ if env is None else env
    token = source.get("TELEGRAM_BOT_TOKEN")
    chat_id = source.get("TELEGRAM_CHAT_ID")

    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("TELEGRAM_CHAT_ID", chat_id),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "missing required environment variables: " + ", ".join(missing)
        )

    extra_chat_ids = tuple(
        cid.strip()
        for cid in source.get("TELEGRAM_EXTRA_CHAT_IDS", "").split(",")
        if cid.strip()
    )

    return Config(
        db_path=source.get("DB_PATH", "data/hadar.sqlite3"),
        images_dir=source.get("IMAGES_DIR", "data/images"),
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        user_id=int(source.get("USER_ID", "5609")),
        forum_id=int(source.get("FORUM_ID", "1")),
        openrouter_api_key=source.get("OPENROUTER_API_KEY") or None,
        openrouter_model=source.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5"),
        openrouter_vision_model=source.get("OPENROUTER_VISION_MODEL") or None,
        telegram_extra_chat_ids=extra_chat_ids,
    )
