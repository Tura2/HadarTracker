from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadItem:
    """One message in a thread, captured for LLM classification context.

    `author` is "hadar" or "other" — no real usernames are kept; only
    Hadar's own trade actions are what Phase 2 classifies.
    """

    author: str
    level: int
    subject: str
    body: str
    posted_at: str


@dataclass(frozen=True)
class Signal:
    """A structured trade-signal read of one post, produced by
    hadar_tracker.signal.classify_post.

    See docs/superpowers/specs/2026-07-21-phase2-llm-signal-design.md for
    the field semantics (action/conviction value sets, etc.).
    """

    is_signal: bool
    ticker_mentioned: str | None
    ticker_guess: str | None
    action: str
    conviction: str
    price_levels: str | None
    rationale: str


@dataclass(frozen=True)
class Post:
    """A single forum post parsed from the JSON stream endpoint.

    `tags` holds the stock tickers mentioned (possibly empty). `root_subject`
    is filled only for replies (`level > 1`) — the subject of the thread's
    `level == 1` root. `image_file_name` is the `MsgFileName` of an attached
    picture (when `HasImages` is set); `image_local_path` is filled later by
    the caller once the attachment has been downloaded to disk.
    `thread_transcript` holds every item (any user) sharing this post's
    thread group that was already present in the same fetched payload, up to
    and including this post's own timestamp — the "conversation so far" used
    for LLM classification context.
    """

    msg_id: str
    posted_at: str
    level: int
    thread_group: str
    subject: str
    body: str
    tags: tuple[str, ...]
    root_subject: str | None = None
    image_file_name: str | None = None
    image_local_path: str | None = None
    thread_transcript: tuple[ThreadItem, ...] = ()
