from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Post:
    """A single forum post parsed from the JSON stream endpoint.

    `tags` holds the stock tickers mentioned (possibly empty). `root_subject`
    is filled only for replies (`level > 1`) — the subject of the thread's
    `level == 1` root. `image_file_name` is the `MsgFileName` of an attached
    picture (when `HasImages` is set); `image_local_path` is filled later by
    the caller once the attachment has been downloaded to disk.
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
