from __future__ import annotations

import requests

from hadar_tracker.models import Post
from hadar_tracker.scraper.parse import HADAR_USER_ID, ScrapeError, parse_posts

ENDPOINT = "https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx"

# An ordinary desktop User-Agent — the same request the page's own JS makes.
# Deliberately NOT a headless/automation fingerprint (that is what gets blocked).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

__all__ = ["ENDPOINT", "USER_AGENT", "ScrapeError", "fetch_raw", "fetch_posts"]


def fetch_raw(
    user_id: int = HADAR_USER_ID,
    forum_id: int = 1,
    timeout: int = 30,
) -> dict:
    """POST the stream endpoint and return the parsed JSON payload.

    Raises for HTTP errors so an unexpected block/outage fails loudly.
    """
    response = requests.post(
        ENDPOINT,
        data={"ForumId": forum_id, "IsFull": 1, "UserId": user_id, "m": 0},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def fetch_posts(
    user_id: int = HADAR_USER_ID,
    forum_id: int = 1,
    timeout: int = 30,
) -> list[Post]:
    """Fetch and parse the latest batch of Hadar's posts.

    Raises ScrapeError if zero posts parse (posts were expected — the endpoint
    covers ~1 day of activity, so an empty result signals a shape change or a
    block, not a normal state).
    """
    payload = fetch_raw(user_id=user_id, forum_id=forum_id, timeout=timeout)
    posts = parse_posts(payload, user_id=user_id)
    if not posts:
        raise ScrapeError(
            "zero posts parsed from stream endpoint — response shape may have "
            "changed or the request was blocked"
        )
    return posts
