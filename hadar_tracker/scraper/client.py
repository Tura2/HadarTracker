from __future__ import annotations

from curl_cffi import requests

from hadar_tracker.models import Post
from hadar_tracker.scraper.parse import HADAR_USER_ID, ScrapeError, parse_posts

ENDPOINT = "https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx"

# Sponser's Cloudflare front challenges clients whose TLS/HTTP2 fingerprint
# doesn't match their User-Agent — plain `requests` claiming to be Chrome got
# 403 `cf-mitigated: challenge` from 2026-09-25. curl_cffi impersonates a real
# Chrome handshake and sets the matching User-Agent/headers itself, so no
# manual User-Agent is sent. Shared by every module that talks to Sponser.
IMPERSONATE = "chrome"

__all__ = ["ENDPOINT", "IMPERSONATE", "BlockedError", "ScrapeError", "fetch_raw", "fetch_posts"]


class BlockedError(Exception):
    """Raised on HTTP 403 — Sponser's Cloudflare front is refusing us (e.g.
    `cf-mitigated: challenge`). Distinct from other HTTP errors so check.py
    can back off and alert once instead of retrying and alerting every run.
    """


def fetch_raw(
    user_id: int = HADAR_USER_ID,
    forum_id: int = 1,
    timeout: int = 30,
) -> dict:
    """POST the stream endpoint and return the parsed JSON payload.

    Raises BlockedError on 403 and raises for any other HTTP error, so an
    unexpected block/outage fails loudly.
    """
    response = requests.post(
        ENDPOINT,
        data={"ForumId": forum_id, "IsFull": 1, "UserId": user_id, "m": 0},
        impersonate=IMPERSONATE,
        timeout=timeout,
    )
    if response.status_code == 403:
        mitigated = getattr(response, "headers", {}).get("cf-mitigated")
        detail = f" (cf-mitigated: {mitigated})" if mitigated else ""
        raise BlockedError(f"403 Forbidden from {ENDPOINT}{detail}")
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
