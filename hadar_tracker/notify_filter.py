from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from hadar_tracker import db
from hadar_tracker.models import Post, Signal

# Israeli trading-hours window. post.posted_at is already a naive Israel-local
# ISO string (see scraper/parse.py's DateCreated handling), so is_after_hours
# needs no timezone conversion — just compare the local clock time. Only
# is_market_hours_now (which asks "what time is it right now") needs the
# actual IANA timezone, since the machine running check.py may be in any tz
# (e.g. a UTC VPS).
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(17, 30)
IL_TZ = ZoneInfo("Asia/Jerusalem")

OWN_ROOT = "own_root"
REPLY_OWN = "reply_own"
REPLY_OTHER = "reply_other"


def classify_bucket(post: Post, conn) -> str:
    """Classify a post as own_root / reply_own / reply_other.

    A root post (level == 1) is always own_root — the per-user stream
    endpoint (scraper/client.py) is already filtered to Hadar's own posts
    (see scraper/parse.py), so any level==1 row here is a thread he started.

    For a reply (level > 1), the root's author is looked up first from
    `post.thread_transcript` (built by parse_posts from the same scrape
    payload — free, no extra query). Only if the root wasn't in that
    payload (an older thread not part of "recent activity") do we fall back
    to checking whether Hadar already has a stored level==1 post in the same
    thread_group.
    """
    if post.level == 1:
        return OWN_ROOT

    for item in post.thread_transcript:
        if item.level == 1:
            return REPLY_OWN if item.author == "hadar" else REPLY_OTHER

    if db.thread_has_root(conn, post.thread_group):
        return REPLY_OWN
    return REPLY_OTHER


def should_notify(bucket: str, post: Post, signal: Signal | None) -> bool:
    """Decide whether a post should actually be sent to Telegram.

    own_root always passes — his own thread IS the action/analysis per the
    validated hypothesis (see the labeling report). A reply with an
    attached image or a ticker tag also always passes, structurally, no LLM
    needed — the labeling exercise showed an image on a reply is reliably a
    real chart. Everything else defers to the LLM signal classification.

    If classification is unavailable (no OPENROUTER_API_KEY, or the call
    failed — classify_post fails open to None per signal.py), this defaults
    to SENDING rather than silently dropping a possibly-real signal: a
    classifier hiccup must never look like "nothing happened," matching
    Phase 1's no-silent-failure stance (see CLAUDE.md).
    """
    if bucket == OWN_ROOT:
        return True
    if post.image_file_name or post.tags:
        return True
    if signal is None:
        return True
    return signal.is_signal


def is_after_hours(posted_at: str) -> bool:
    """True if posted_at falls outside the 09:30-17:30 Israel trading-hours
    window (see the module docstring re: posted_at already being local)."""
    local_time = datetime.fromisoformat(posted_at).time()
    return not (MARKET_OPEN <= local_time <= MARKET_CLOSE)


def is_market_hours_now() -> bool:
    """True if the current real-world time is within 09:30-17:30 Israel
    time. Used by check.py to decide whether a new post that should be
    notified gets sent immediately or held (notified=0) for the next run
    that lands inside the window — see db.fetch_pending_posts.
    """
    local_time = datetime.now(IL_TZ).time()
    return MARKET_OPEN <= local_time <= MARKET_CLOSE


# Deployment runs check.py on a fixed schedule (e.g. every 10 min, all day —
# see deploy/README.md) so the hold queue flushes promptly right at 09:30.
# Outside market hours there's nothing time-sensitive to catch, so rather
# than reconfigure the scheduler for two different cadences, check.py just
# skips the actual work on most off-hours invocations, via this throttle —
# one real check per hour off-hours, every invocation in-hours (unchanged).
OFFHOURS_CHECK_INTERVAL_SECONDS = 3600
_LAST_OFFHOURS_CHECK_KEY = "last_offhours_check"


def should_run_offhours_check(conn, now: datetime | None = None) -> bool:
    """True if it's been >= OFFHOURS_CHECK_INTERVAL_SECONDS since the last
    off-hours check (or none has ever run this way)."""
    if now is None:
        now = datetime.now(IL_TZ)
    last = db.get_meta(conn, _LAST_OFFHOURS_CHECK_KEY)
    if last is None:
        return True
    elapsed = (now - datetime.fromisoformat(last)).total_seconds()
    return elapsed >= OFFHOURS_CHECK_INTERVAL_SECONDS


def mark_offhours_check_ran(conn, now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(IL_TZ)
    db.set_meta(conn, _LAST_OFFHOURS_CHECK_KEY, now.isoformat())
