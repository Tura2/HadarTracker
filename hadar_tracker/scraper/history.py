from __future__ import annotations

import requests

HISTORY_ENDPOINT = "https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_MESSAGES.ashx"

# Same ordinary desktop UA as the other endpoints — not an automation fingerprint.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

__all__ = ["HISTORY_ENDPOINT", "USER_AGENT", "fetch_history_page"]


def fetch_history_page(page_id: int, forum_id: int = 1, timeout: int = 30) -> dict:
    """GET one page of the general forum listing (all users, not just Hadar).

    Pages are in chronological order: page 1 is the forum's oldest messages,
    ascending toward the present. `page_id=0` is a special "recently bumped"
    bucket (mixed dates, threads with new activity resurface) rather than a
    clean chronological page — use it only for its `Info.NumberOfPages` value
    and as a bonus coverage pass, not for date-based stopping logic.

    Raises for HTTP errors so an unexpected block/outage fails loudly.
    """
    response = requests.get(
        HISTORY_ENDPOINT,
        params={"f": forum_id, "p": page_id},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
