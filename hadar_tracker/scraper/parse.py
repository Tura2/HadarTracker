from __future__ import annotations

import re
from datetime import datetime

from hadar_tracker.models import Post

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


def extract_tags(raw) -> tuple[str, ...]:
    """Normalize the `Tags` field into a tuple of ticker symbols.

    Defensive about shape: accepts a comma/semicolon-delimited string, or a
    list of strings, or a list of dicts carrying a `Symbol`/`symbol` key.
    Returns () for anything empty or unrecognized.
    """
    if not raw:
        return ()
    if isinstance(raw, str):
        parts = re.split(r"[,;]", raw)
    elif isinstance(raw, list):
        parts = [
            part if isinstance(part, str)
            else str(part.get("Symbol") or part.get("symbol") or "")
            for part in raw
        ]
    else:
        return ()
    return tuple(p.strip() for p in parts if p and p.strip())


def parse_posts(payload: dict, user_id: int = HADAR_USER_ID) -> list[Post]:
    """Turn a raw stream payload into Hadar's Post objects. Pure — no network.

    Filters to items whose User.UserId == user_id, resolves each reply's root
    subject via the L1 thread group (root = the Level==1 sibling, which may be
    any user), and extracts tickers and the attached image file name.
    """
    if "Data" not in payload:
        raise ScrapeError("response payload missing 'Data' key — shape changed")

    data = payload["Data"]

    # Root subjects across ALL users, keyed by thread group (L1).
    root_subjects: dict[str, str] = {}
    for item in data:
        if item.get("Level") == 1:
            root_subjects[str(item.get("L1"))] = item.get("subject") or ""

    posts: list[Post] = []
    for item in data:
        user = item.get("User") or {}
        if user.get("UserId") != user_id:
            continue

        level = int(item.get("Level"))
        thread_group = str(item.get("L1"))
        root_subject = root_subjects.get(thread_group) if level > 1 else None

        has_image = bool(item.get("HasImages")) and bool(item.get("MsgFileName"))
        image_file_name = item.get("MsgFileName") if has_image else None

        posts.append(
            Post(
                msg_id=str(item.get("MsgId")),
                posted_at=parse_date(item.get("DateCreated")),
                level=level,
                thread_group=thread_group,
                subject=item.get("subject") or "",
                body=item.get("Msg") or "",
                tags=extract_tags(item.get("Tags")),
                root_subject=root_subject,
                image_file_name=image_file_name,
                image_local_path=None,
            )
        )

    return posts
