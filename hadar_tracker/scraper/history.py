from __future__ import annotations

from curl_cffi import requests

from hadar_tracker.scraper.client import IMPERSONATE

HISTORY_ENDPOINT = "https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_MESSAGES.ashx"

__all__ = ["HISTORY_ENDPOINT", "fetch_history_page"]


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
        impersonate=IMPERSONATE,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
