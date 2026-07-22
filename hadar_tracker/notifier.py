from __future__ import annotations

import asyncio
import html
import re
from typing import Sequence

from telegram import Bot

from hadar_tracker.models import Signal

_CAPTION_LIMIT = 1024

# Live debugging (see the chat history around this line) ruled out bidi
# control characters (both a leading RLM and a full RLE...PDF embedding
# around each line were tried and had zero effect) and found the real
# trigger: Telegram misrenders a short Hebrew line ending in Latin digits
# (e.g. a stop-loss price like "סטופ 4230") as left-aligned ONLY when it is
# the literal LAST line of the message — the same line renders correctly
# whenever anything follows it (confirmed: it's fine mid-body, and fine
# whenever a signal section trails it). The 🔗 thread-link line below is
# real, useful trailing content that fixes this the same way; _RLM (an
# invisible zero-width Right-to-Left Mark) is now only a fallback for the
# rare case there's no thread_url to link to.
_RLM = "‏"

# Sponser's own client-side "forum-title" link for a specific message (see
# assets2022/forum.js: `<a href="https://www.sponser.co.il/Forum.aspx?
# ForumId=' + forumId + '&MsgId=' + msgId + ...">`). PageId is deliberately
# omitted — passing PageId=0 (the only value we could easily determine)
# causes an infinite redirect loop on the live site; ForumId+MsgId alone
# resolves correctly on their own.
_THREAD_URL = "https://www.sponser.co.il/Forum.aspx?ForumId={forum_id}&MsgId={msg_id}"


def build_thread_url(forum_id: int, msg_id: str) -> str:
    return _THREAD_URL.format(forum_id=forum_id, msg_id=msg_id)


def _esc(text: str | None) -> str:
    """Escape for Telegram's HTML parse mode (used for the bold reply-context
    label). `html.unescape` first: Sponser's raw scraped text sometimes
    contains a literal, undecoded entity like "&nbsp;" (seen live in a real
    subject line) — escaping straight from there would turn its "&" into
    "&amp;", which Telegram then renders as the literal text "&nbsp;"
    instead of a space. Unescaping first collapses any such entity back to
    a real character, then re-escaping makes it HTML-safe for our own tags.
    quote=False since we're not embedding into an HTML attribute."""
    return html.escape(html.unescape(text or ""), quote=False)

# Sponser's forum editor encodes smileys as |NN| placeholders in the raw
# text (resolved client-side on the site via a `var ICONS = [...]` table to
# <img> tags — see https://www.sponser.co.il/Images/{filename} — which the
# JSON API we scrape never does). Mapped by hand from the actual smiley
# images for every code observed in Hadar's posts; a handful (4, 34, 128,
# 164, 203) are best-effort guesses from small/ambiguous source images.
# Codes not in this table are dropped rather than left as a raw "|999|".
_EMOJI_CODES = {
    "1": "🙂", "3": "😠", "4": "👍", "5": "😎", "6": "🙁", "8": "🏅",
    "9": "😉", "10": "🤢", "12": "🌹", "13": "🙂", "15": "😌", "21": "🌸",
    "26": "😂", "28": "🎂", "30": "😉", "31": "😏", "32": "😊", "34": "🤷",
    "35": "😆", "36": "❤️", "38": "🤔", "40": "😎", "52": "😂", "78": "🪬",
    "128": "🙂", "135": "📈", "164": "🐂", "203": "🙄", "255": "😍", "267": "💬",
}
_EMOJI_CODE_RE = re.compile(r"\|(\d+)\|")


def _replace_emoji_codes(text: str) -> str:
    if not text:
        return text
    return _EMOJI_CODE_RE.sub(lambda m: _EMOJI_CODES.get(m.group(1), ""), text)

# Conviction is rendered as a colored ball emoji rather than text, per the
# live-deployment request — green/yellow/red reads faster than a word at a
# glance in Telegram. Unknown/missing conviction values fall back to a
# neutral white ball rather than raising.
_CONVICTION_BALL = {"high": "🟢", "medium": "🟡", "low": "🔴"}


def _build_signal_section(signal: Signal | None) -> str:
    """Render the `🤖 Signal: ...` block, or "" if there's nothing to show.

    Shared by format_message (text messages) and the photo-caption
    truncation path in send_post, so both paths render signals identically.
    """
    if signal is None or not signal.is_signal:
        return ""
    lines: list[str] = []
    header = f"🤖 Signal: {signal.action.upper()}"
    if signal.ticker_guess:
        header += f" — {_esc(signal.ticker_guess)}"
    header += " " + _CONVICTION_BALL.get(signal.conviction, "⚪")
    lines.append(header)
    rationale_parts = [_esc(p) for p in (signal.price_levels, signal.rationale) if p]
    if rationale_parts:
        lines.append(f'   "{" — ".join(rationale_parts)}"')
    return "\n".join(lines)


def format_message(
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
    signal: Signal | None = None,
    after_hours: bool = False,
    thread_url: str | None = None,
) -> str:
    """Build the notification text for a post, sent with Telegram's HTML
    parse mode (see send_post/_send_post_async).

    Layout — subject, reply-context, and body flow together uninterrupted
    (tags used to sit between subject and reply-context, which read as
    noise breaking up the story right when a reader needs the reply
    context to understand the subject/body — see the live example that
    prompted this reorder, a false-positive ticker tag matched from an
    idiom in the body, sitting right in the middle of the message); tags
    and the signal move to a single footer block after body instead:
        🌙 After Hours
        <subject>
        ↩️ <b>הגיב ל</b>: <root_subject>

        <body>

        🏷 TEVA, ICL
        🤖 Signal: ADD — DJIN 🟡
           "close above 460 — breakout"

        🔗 <a href="...">Link</a>
    Empty/omitted parts are skipped. The signal section only appears when
    `signal` is given AND `signal.is_signal` is true — a classified-as-noise
    post (or a classification failure, where `signal` is None) renders
    exactly as it did in Phase 1. `after_hours` marks a post whose own
    `posted_at` fell outside the 09:30-17:30 Israel trading-hours window
    (see notify_filter.is_after_hours) — it's about when Hadar posted, not
    when this message happens to be sent. `subject`/`root_subject`/`body`
    are run through `_replace_emoji_codes` first, so the forum's raw "|NN|"
    smiley placeholders render as real emoji instead of literal pipe-digits,
    then HTML-escaped (`_esc`) since the message is sent as HTML — required
    for the `הגיב ל` label to render bold rather than as literal `<b>` tags.
    `thread_url` (build one with notify_filter... see check.py) renders as a
    clickable "🔗 Link" line — real trailing content that, as a side effect,
    also keeps the body from ever being the message's literal last line (see
    _RLM above for why that matters). Falls back to the invisible _RLM
    sentinel line when no thread_url is given.
    """
    lines: list[str] = []
    if after_hours:
        lines.append("🌙 After Hours")
    if subject:
        lines.append(_esc(_replace_emoji_codes(subject)))
    if root_subject:
        lines.append("↩️ <b>הגיב ל</b>: " + _esc(_replace_emoji_codes(root_subject)))
    lines.append("")
    lines.append(_esc(_replace_emoji_codes(body)))

    footer: list[str] = []
    if tags:
        footer.append("🏷 " + ", ".join(_esc(t) for t in tags))
    signal_section = _build_signal_section(signal)
    if signal_section:
        footer.append(signal_section)
    if footer:
        lines.append("")
        lines.extend(footer)

    result = "\n".join(lines).strip()
    if thread_url:
        result += '\n\n🔗 <a href="' + html.escape(thread_url, quote=True) + '">Link</a>'
    else:
        result += "\n" + _RLM
    return result


def _build_photo_caption(
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None,
    signal: Signal | None,
    limit: int = _CAPTION_LIMIT,
    after_hours: bool = False,
    thread_url: str | None = None,
) -> str:
    """Build the Telegram photo-caption text, truncated to `limit` chars.

    Unlike a blind `text[:limit]` slice off the fully-assembled message,
    this truncates the BODY rather than the tail of the string — so when a
    signal is present (the highest-value case for image posts, per the
    design spec), the `🤖 Signal: ...` section always survives intact
    instead of being silently cut off (see Finding 1 of the whole-branch
    review). Note the `full[:limit]` no-signal fallback below can still
    truncate the trailing 🔗 link line on an extreme-length body; that's an
    existing, accepted tradeoff of this fallback, not new.
    """
    signal_section = _build_signal_section(signal)
    full = format_message(subject, tags, body, root_subject, signal, after_hours, thread_url)
    if len(full) <= limit:
        return full
    if not signal_section:
        return full[:limit]

    overflow = len(full) - limit
    truncated_body = body[: max(0, len(body) - overflow)]
    caption = format_message(subject, tags, truncated_body, root_subject, signal, after_hours, thread_url)
    if len(caption) > limit:
        # Last-resort clamp (e.g. head+signal alone already exceed limit):
        # trim from the front so the signal section, at the tail, survives.
        caption = caption[-limit:]
    return caption


def send_post(
    bot_token: str,
    chat_id: str,
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
    image_path: str | None = None,
    signal: Signal | None = None,
    after_hours: bool = False,
    thread_url: str | None = None,
) -> None:
    """Send one Telegram message for a post: photo+caption if image_path is
    set, otherwise a plain text message. Appends a trade-signal section if
    `signal` is given and classified as a real signal. `after_hours` marks
    a post whose own timestamp fell outside trading hours (see
    notify_filter.is_after_hours) with a leading label. `thread_url`, when
    given, renders as a clickable "🔗 Link" line back to the post on
    sponser.co.il (see check.py for how it's built)."""
    text = format_message(subject, tags, body, root_subject, signal, after_hours, thread_url)
    caption = None
    if image_path:
        caption = _build_photo_caption(
            subject, tags, body, root_subject, signal, after_hours=after_hours, thread_url=thread_url
        )
    asyncio.run(_send_post_async(bot_token, chat_id, text, image_path, caption))


def send_alert(bot_token: str, chat_id: str, message: str) -> None:
    """Send a scrape-failure alert so failures are never silent."""
    asyncio.run(_send_alert_async(bot_token, chat_id, message))


async def _send_post_async(
    bot_token: str,
    chat_id: str,
    text: str,
    image_path: str | None,
    caption: str | None = None,
) -> None:
    bot = Bot(token=bot_token)
    async with bot:
        if image_path:
            with open(image_path, "rb") as handle:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=handle,
                    caption=caption if caption is not None else text[:_CAPTION_LIMIT],
                    parse_mode="HTML",
                )
        else:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def _send_alert_async(
    bot_token: str,
    chat_id: str,
    message: str,
) -> None:
    bot = Bot(token=bot_token)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=f"[HadarTracker] {message}")
