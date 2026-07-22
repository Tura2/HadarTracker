from __future__ import annotations

import logging
import re
from datetime import datetime

from hadar_tracker.models import Post, ThreadItem

log = logging.getLogger("hadar_tracker.scraper.parse")

HADAR_USER_ID = 5609

# DateCreated arrives as "DD/MM/YY | HH:MM" in Israel local time. We store the
# parsed value as a naive ISO 8601 string (no tz offset) to stay dependency-free
# on Windows/VPS (see plan Notes on the timezone decision).
_DATE_FORMAT = "%d/%m/%y | %H:%M"


class ScrapeError(Exception):
    """Raised when the JSON payload is missing expected structure.

    Surfaces a changed response shape loudly instead of as an empty success
    (Global Constraint: no silent failures).
    """


def parse_date(raw: str) -> str:
    """Convert "DD/MM/YY | HH:MM" (Israel local) to a naive ISO 8601 string."""
    return datetime.strptime(raw.strip(), _DATE_FORMAT).isoformat()


def _format_tag_dict(part: dict) -> str:
    """A real `Tags` entry is `{"Name": "תדיראן גרופ", "Symbol": "258012"}` —
    Symbol is Sponser's internal numeric security id, not a ticker, so on
    its own it's meaningless to a human reader. Render "{Name} ({Symbol})"
    when both are present; fall back to whichever one exists otherwise.
    """
    symbol = part.get("Symbol") or part.get("symbol") or ""
    name = part.get("Name") or part.get("name") or ""
    if name and symbol:
        return f"{name} ({symbol})"
    return str(name or symbol)


def extract_tags(raw) -> tuple[str, ...]:
    """Normalize the `Tags` field into a tuple of display-ready tag strings.

    Defensive about shape: accepts a comma/semicolon-delimited string, or a
    list of strings, or a list of dicts carrying `Name`/`Symbol` (or
    lowercase `name`/`symbol`) keys — see _format_tag_dict for how those
    render. Returns () for anything empty or unrecognized.
    """
    if not raw:
        return ()
    if isinstance(raw, str):
        parts = re.split(r"[,;]", raw)
    elif isinstance(raw, list):
        parts = [part if isinstance(part, str) else _format_tag_dict(part) for part in raw]
    else:
        return ()
    return tuple(p.strip() for p in parts if p and p.strip())


def parse_posts(payload: dict, user_id: int = HADAR_USER_ID) -> list[Post]:
    """Turn a raw stream payload into Hadar's Post objects. Pure — no network.

    Filters to items whose User.UserId == user_id, resolves each reply's root
    subject via the L1 thread group (root = the Level==1 sibling, which may be
    any user), extracts tickers and the attached image file name, and builds
    each post's thread_transcript: every item sharing its L1 thread group
    (any user, any level) already present in this same payload with
    posted_at <= this post's own posted_at, explicitly sorted chronologically
    by posted_at (payload order is NOT guaranteed to be chronological — e.g.
    history.py's page_id=0 bucket is a "recently bumped" mix of dates that
    backfill.py feeds straight into this function). This is "the
    conversation so far" as Hadar would have seen it when he posted — built
    entirely from data already in the payload, no extra network calls (see
    the Phase 2 design spec's data-flow investigation).
    """
    if "Data" not in payload:
        raise ScrapeError("response payload missing 'Data' key — shape changed")

    data = payload["Data"]

    # Root subjects across ALL users, keyed by thread group (L1).
    root_subjects: dict[str, str] = {}
    for item in data:
        if item.get("Level") == 1:
            root_subjects[str(item.get("L1"))] = item.get("subject") or ""

    # Every item (any user), grouped by thread group — used to build each
    # Hadar post's thread_transcript below. posted_at is a naive ISO 8601
    # string, so plain string comparison ("<=" for filtering, and as the
    # sort key) already gives correct chronological ordering. Payload order
    # itself is NOT trusted to already be chronological (see docstring).
    threads: dict[str, list[ThreadItem]] = {}
    for item in data:
        thread_group = str(item.get("L1"))
        user = item.get("User") or {}
        is_hadar = user.get("UserId") == user_id
        author = "hadar" if is_hadar else "other"
        try:
            level = int(item.get("Level"))
            posted_at = parse_date(item.get("DateCreated"))
        except (TypeError, ValueError) as exc:
            # A malformed Level/DateCreated on some OTHER user's post must not
            # crash the whole run (Phase 1 never even looked at those fields
            # on non-Hadar items). Hadar's own items are re-parsed below
            # without this guard, so a malformed field on a genuinely-Hadar
            # post still raises loudly, unchanged from Phase 1.
            log.warning(
                "skipping malformed item (msg_id=%s) from thread transcript scan: %s",
                item.get("MsgId"), exc,
            )
            continue
        threads.setdefault(thread_group, []).append(
            ThreadItem(
                author=author,
                level=level,
                subject=item.get("subject") or "",
                body=item.get("Msg") or "",
                posted_at=posted_at,
            )
        )

    posts: list[Post] = []
    for item in data:
        user = item.get("User") or {}
        if user.get("UserId") != user_id:
            continue

        level = int(item.get("Level"))
        thread_group = str(item.get("L1"))
        root_subject = root_subjects.get(thread_group) if level > 1 else None
        posted_at = parse_date(item.get("DateCreated"))

        thread_transcript = tuple(
            sorted(
                (ti for ti in threads.get(thread_group, ()) if ti.posted_at <= posted_at),
                key=lambda ti: ti.posted_at,
            )
        )

        has_image = bool(item.get("HasImages")) and bool(item.get("MsgFileName"))
        image_file_name = item.get("MsgFileName") if has_image else None

        posts.append(
            Post(
                msg_id=str(item.get("MsgId")),
                posted_at=posted_at,
                level=level,
                thread_group=thread_group,
                subject=item.get("subject") or "",
                body=item.get("Msg") or "",
                tags=extract_tags(item.get("Tags")),
                root_subject=root_subject,
                image_file_name=image_file_name,
                image_local_path=None,
                thread_transcript=thread_transcript,
            )
        )

    return posts
