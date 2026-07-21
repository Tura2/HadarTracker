from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Post:
    """A single scraped forum post.

    `chart_selector` is the CSS selector for the embedded chart image (set at
    parse time when `has_chart` is True); `chart_image_path` is filled later by
    the caller once the chart has been screenshotted to disk.
    """

    post_id: str
    posted_at: str
    raw_text: str
    has_chart: bool
    chart_selector: str | None = None
    chart_image_path: str | None = None
