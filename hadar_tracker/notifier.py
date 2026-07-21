from __future__ import annotations

import asyncio
from typing import Sequence

from telegram import Bot

_CAPTION_LIMIT = 1024


def format_message(
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
) -> str:
    """Build the notification text for a post.

    Layout (each present part on its own line, then a blank line, then body):
        <subject>
        🏷 TEVA, ICL
        ↩️ Replying to: <root_subject>

        <body>
    Empty/omitted parts are skipped.
    """
    lines: list[str] = []
    if subject:
        lines.append(subject)
    if tags:
        lines.append("🏷 " + ", ".join(tags))
    if root_subject:
        lines.append("↩️ Replying to: " + root_subject)
    lines.append("")
    lines.append(body)
    return "\n".join(lines).strip()


def send_post(
    bot_token: str,
    chat_id: str,
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
    image_path: str | None = None,
) -> None:
    """Send one Telegram message for a post: photo+caption if image_path is
    set, otherwise a plain text message."""
    text = format_message(subject, tags, body, root_subject)
    asyncio.run(_send_post_async(bot_token, chat_id, text, image_path))


def send_alert(bot_token: str, chat_id: str, message: str) -> None:
    """Send a scrape-failure alert so failures are never silent."""
    asyncio.run(_send_alert_async(bot_token, chat_id, message))


async def _send_post_async(
    bot_token: str,
    chat_id: str,
    text: str,
    image_path: str | None,
) -> None:
    bot = Bot(token=bot_token)
    async with bot:
        if image_path:
            with open(image_path, "rb") as handle:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=handle,
                    caption=text[:_CAPTION_LIMIT],
                )
        else:
            await bot.send_message(chat_id=chat_id, text=text)


async def _send_alert_async(
    bot_token: str,
    chat_id: str,
    message: str,
) -> None:
    bot = Bot(token=bot_token)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=f"[HadarTracker] {message}")
