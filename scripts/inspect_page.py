"""One-off, headless page inspection for HadarTracker Task 2.

Run:  python scripts/inspect_page.py
Opens Hadar's message feed in a headless browser, waits for JS to render,
dumps the rendered HTML + a full-page screenshot to tests/fixtures/, and
prints every network request so an investigator can spot an underlying
data endpoint.

This script is NOT imported by the app; it is a one-off investigation
tool. It runs non-interactively (headless=True, no input() prompt) so it
can be executed by an automated agent with no display and no interactive
stdin. The captured HTML/network log are meant to be inspected afterward
by reading the fixture file and the printed request list.
"""
from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

from hadar_tracker.config import DEFAULT_FORUM_URL

FIXTURE_DIR = pathlib.Path("tests/fixtures")


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    requests: list[tuple[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("request", lambda r: requests.append((r.method, r.url)))
        page.goto(DEFAULT_FORUM_URL, timeout=60000)
        # Give client-side JS/AJAX time to populate the post list.
        page.wait_for_timeout(6000)

        html = page.content()
        (FIXTURE_DIR / "user_messages_page1.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(FIXTURE_DIR / "user_messages_page1.png"), full_page=True)

        print("=== Network requests (look for JSON/AJAX data endpoints) ===")
        for method, url in requests:
            print(f"{method}  {url}")

        browser.close()


if __name__ == "__main__":
    main()
