from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_FORUM_URL = (
    "https://www.sponser.co.il/ForumViewUserMessages.aspx"
    "?UserId=5609&ForumId=1&IsFull=1"
)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    forum_url: str
    db_path: str
    charts_dir: str
    telegram_bot_token: str
    telegram_chat_id: str
    headless: bool


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Raises ConfigError (loudly) if a required variable is missing, so a
    misconfigured cron run fails fast instead of silently doing nothing.
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

    return Config(
        forum_url=source.get("FORUM_URL", DEFAULT_FORUM_URL),
        db_path=source.get("DB_PATH", "data/hadar.sqlite3"),
        charts_dir=source.get("CHARTS_DIR", "data/charts"),
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        headless=source.get("HEADLESS", "1") != "0",
    )
