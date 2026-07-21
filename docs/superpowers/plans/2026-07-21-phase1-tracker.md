# HadarTracker Phase 1 (Scrape → Store → Notify) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably scrape trader "Hadar"'s public Sponser forum posts, store each post durably and deduplicated in SQLite, and send a Telegram notification (text + archived chart image) for every new post.

**Architecture:** A single Python package (`hadar_tracker`) with one shared Playwright-based scraping engine consumed by two entry points: `check.py` (cron-invoked incremental diff → insert → notify) and `backfill.py` (on-demand, resumable historical crawl paging backward). Parsing is split from browser I/O so it is unit-testable against saved HTML fixtures with no live network. SQLite is the single-writer store; Telegram is the only output channel (posts and failure alerts).

**Tech Stack:** Python 3.11+, Playwright (Chromium, headless), BeautifulSoup4 (HTML parsing), SQLite (stdlib `sqlite3`), python-telegram-bot (v21, async), pytest.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the design spec (`docs/superpowers/specs/2026-07-21-phase1-tracker-design.md`).

- **Language/engine:** Python + Playwright (headless Chromium) is the core scraping engine. Post content loads via JS/AJAX and is NOT in static HTML, so a real browser is mandatory — no plain HTTP + HTML fetch.
- **Storage:** Single-file SQLite database, single writer, no concurrent-access needs. `posts` table schema is fixed (see Task 3). Do not add columns beyond the spec without adding a task.
- **Notifications:** Telegram via `python-telegram-bot`, sending to the user's personal chat. One message per new post (raw text + chart image attachment if present). Same channel sends scrape-failure alerts.
- **No silent failures:** Every `check.py` run either succeeds cleanly or fails loudly — non-zero exit code **and** a clear log line **and** a Telegram alert (`"scraper run failed: ..."`). Zero posts found where posts were expected is a failure, not an empty success.
- **Idempotent/resumable backfill:** `backfill.py` upserts by `post_id` (insert-or-ignore); safe to interrupt and rerun at any time.
- **Access model:** Passive, logged-out reading only. Assume the profile page is publicly viewable; add login handling only if Task 2 proves it is not.
- **Charts:** Posts sometimes embed charts (e.g. from `chart.bursagraph.co.il`). These must be archived as image screenshots to `data/charts/`, because the live chart source can change after the fact.
- **Testing discipline:** Unit tests exercise parsing logic against saved HTML/DOM fixtures, independent of live network. Manual smoke test against the live site before deploying each change to the VPS.
- **Deployment target:** Runs continuously on the user's Oracle Cloud VPS via cron or systemd timer; built and tested locally first. Poll interval starts at every 10–15 minutes.
- **Tooling fallback:** Plain Playwright is the default. Escalate to Scrapling's stealth fetcher ONLY if Sponser blocks plain headless browsing (out of scope for this plan; noted as a contingency).

**Target profile URL (fixed):**
`https://www.sponser.co.il/ForumViewUserMessages.aspx?UserId=5609&ForumId=1&IsFull=1`

---

## File Structure

Every path is relative to the repo root `c:/Users/offir/Desktop/Projects/HadarTracker`.

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata + pytest config (`pythonpath = ["."]` so `hadar_tracker` imports resolve from repo root). |
| `requirements.txt` | Pinned dependency floors: playwright, python-telegram-bot, beautifulsoup4, pytest. |
| `.gitignore` | Ignore `.venv/`, `data/`, `__pycache__/`, `*.pyc`, `.env`. |
| `.env.example` | Documented template of required environment variables (no secrets committed). |
| `hadar_tracker/__init__.py` | Marks the package. Empty. |
| `hadar_tracker/models.py` | The `Post` dataclass — the single shared data shape passed from scraper → check/backfill. |
| `hadar_tracker/util.py` | Tiny shared helpers (`now_iso()`). |
| `hadar_tracker/config.py` | `Config` dataclass + `load_config()` reading env vars; fails loudly on missing required vars. |
| `hadar_tracker/db.py` | All SQLite access: connect, schema init, existence check, insert-or-ignore, count. No business logic. |
| `hadar_tracker/scraper/__init__.py` | Marks the scraper sub-package. Empty. |
| `hadar_tracker/scraper/parser.py` | Pure `parse_posts(html) -> list[Post]`. No network, no browser. Selector constants live here. |
| `hadar_tracker/scraper/browser.py` | Playwright I/O only: `render_page(...)`, `screenshot_element(...)`. |
| `hadar_tracker/scraper/engine.py` | Orchestration combining browser + parser: `fetch_latest(...)`, `iter_backward(...)`, `page_url(...)`, `ScrapeError`. |
| `hadar_tracker/notifier.py` | Telegram sending: `send_post(...)`, `send_alert(...)`. |
| `hadar_tracker/check.py` | Incremental cron job: `process_new_posts(...)`, `run_check(...)`, `main()`. |
| `hadar_tracker/backfill.py` | Historical crawl: `run_backfill(...)`, `main()`. |
| `scripts/inspect_page.py` | Throwaway, non-headless Playwright inspection script (Task 2) — captures HTML/screenshot + logs network requests. Not imported by the app. |
| `tests/__init__.py` | Marks tests a package. Empty. |
| `tests/fixtures/sample_posts.html` | Hand-authored, deterministic HTML fixture for parser unit tests. |
| `tests/fixtures/user_messages_page1.html` | Real captured page HTML (produced by Task 2). Used to reconcile selectors; not asserted against directly. |
| `tests/test_config.py` | Tests for `load_config()`. |
| `tests/test_util.py` | Test for `now_iso()`. |
| `tests/test_db.py` | Tests for db layer against a temp/in-memory database. |
| `tests/test_parser.py` | Tests for `parse_posts()` against `sample_posts.html`. |
| `tests/test_engine.py` | Tests for `fetch_latest`/`iter_backward`/`page_url` with `browser.render_page` monkeypatched. |
| `tests/test_notifier.py` | Tests for `send_post`/`send_alert` with a fake `Bot`. |
| `tests/test_check.py` | Tests for `process_new_posts` and `run_check` with fakes/mocks. |
| `tests/test_backfill.py` | Tests for `run_backfill` with `engine.iter_backward` faked. |
| `deploy/run_check.sh` | VPS wrapper: load `.env`, run `python -m hadar_tracker.check`. |
| `deploy/run_backfill.sh` | VPS wrapper for the backfill entry point. |
| `deploy/hadar-tracker.service` | systemd oneshot unit running `run_check.sh`. |
| `deploy/hadar-tracker.timer` | systemd timer firing the service every 10 minutes. |
| `deploy/README.md` | Oracle VPS install + cron/systemd instructions. |
| `docs/superpowers/notes/2026-07-21-page-structure.md` | Task 2 findings: load mechanism, real selectors, pagination scheme, login/bot-detection answers. |

### Task ordering rationale

The spec names "inspect the live page in a real browser" as the **first implementation task**, because it resolves the four open items (load mechanism, real selectors, pagination scheme, login/bot-detection) that the scraper's real selectors depend on. Therefore:

- **Task 1** scaffolds the project (no live-site knowledge needed).
- **Task 2** is the live-page investigation. It runs before any scraper code so the selector constants and the committed real-page fixture reflect reality.
- **Task 3 (db.py)** has **no dependency** on Task 2 and may be executed in parallel with it; it is listed after Task 2 only to keep the plan linear.
- **Tasks 4–5 (parser/engine)** ship with a hand-authored deterministic fixture (`sample_posts.html`) so their unit tests are hermetic and concrete regardless of the live site. The selector **constants** in `parser.py`/`engine.py` are isolated at the top of each file; Task 2's findings pin their real values, and Task 4/5 include an explicit reconciliation step. If the real DOM differs from the authored fixture, update the fixture and the constants together — the change stays localized to those two files.

This honors the spec's "investigation first" intent while keeping every downstream task independently testable without the live network.

---

## Task 1: Project scaffolding, shared models, config, util

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `hadar_tracker/__init__.py`
- Create: `hadar_tracker/models.py`
- Create: `hadar_tracker/util.py`
- Create: `hadar_tracker/config.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/.gitkeep`
- Test: `tests/test_util.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `hadar_tracker.models.Post` — `@dataclass(frozen=True)` with fields `post_id: str`, `posted_at: str`, `raw_text: str`, `has_chart: bool`, `chart_selector: str | None = None`, `chart_image_path: str | None = None`.
  - `hadar_tracker.util.now_iso() -> str` — current UTC time, ISO 8601.
  - `hadar_tracker.config.DEFAULT_FORUM_URL: str`.
  - `hadar_tracker.config.Config` — `@dataclass(frozen=True)` with fields `forum_url: str`, `db_path: str`, `charts_dir: str`, `telegram_bot_token: str`, `telegram_chat_id: str`, `headless: bool`.
  - `hadar_tracker.config.ConfigError(Exception)`.
  - `hadar_tracker.config.load_config(env: dict[str, str] | None = None) -> Config`.

- [ ] **Step 1: Create dependency and project config files**

`requirements.txt`:

```
playwright>=1.44
python-telegram-bot>=21.0
beautifulsoup4>=4.12
pytest>=8.0
```

`pyproject.toml`:

```toml
[project]
name = "hadar-tracker"
version = "0.1.0"
description = "Scrape, store, and Telegram-notify Hadar's Sponser forum posts (Phase 1)."
requires-python = ">=3.11"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`.gitignore`:

```
.venv/
data/
__pycache__/
*.pyc
.env
```

`.env.example`:

```
# Telegram bot credentials (required) — no defaults, load_config() raises without them.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Optional overrides (defaults shown).
FORUM_URL=https://www.sponser.co.il/ForumViewUserMessages.aspx?UserId=5609&ForumId=1&IsFull=1
DB_PATH=data/hadar.sqlite3
CHARTS_DIR=data/charts
# HEADLESS=0 to run the browser headed (debugging only); anything but "0" means headless.
HEADLESS=1
```

- [ ] **Step 2: Create package files, `Post`, `util`, `config`**

`hadar_tracker/__init__.py`: empty file.

`tests/__init__.py`: empty file.

`tests/fixtures/.gitkeep`: empty file (keeps the fixtures dir in git before real fixtures land).

`hadar_tracker/models.py`:

```python
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
```

`hadar_tracker/util.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
```

`hadar_tracker/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_FORUM_URL = (
    "https://www.sponser.co.il/ForumViewUserMessages.aspx"
    "?UserId=5609&ForumId=1&IsFull=1"
)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    forum_url: str
    db_path: str
    charts_dir: str
    telegram_bot_token: str
    telegram_chat_id: str
    headless: bool


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Raises ConfigError (loudly) if a required variable is missing, so a
    misconfigured cron run fails fast instead of silently doing nothing.
    """
    source = os.environ if env is None else env
    token = source.get("TELEGRAM_BOT_TOKEN")
    chat_id = source.get("TELEGRAM_CHAT_ID")

    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("TELEGRAM_CHAT_ID", chat_id),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "missing required environment variables: " + ", ".join(missing)
        )

    return Config(
        forum_url=source.get("FORUM_URL", DEFAULT_FORUM_URL),
        db_path=source.get("DB_PATH", "data/hadar.sqlite3"),
        charts_dir=source.get("CHARTS_DIR", "data/charts"),
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        headless=source.get("HEADLESS", "1") != "0",
    )
```

- [ ] **Step 3: Write the failing tests**

`tests/test_util.py`:

```python
from datetime import datetime

from hadar_tracker.util import now_iso


def test_now_iso_is_parseable_iso8601():
    value = now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
```

`tests/test_config.py`:

```python
import pytest

from hadar_tracker.config import Config, ConfigError, DEFAULT_FORUM_URL, load_config


def test_load_config_uses_defaults_when_only_required_present():
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    config = load_config(env)
    assert isinstance(config, Config)
    assert config.forum_url == DEFAULT_FORUM_URL
    assert config.db_path == "data/hadar.sqlite3"
    assert config.charts_dir == "data/charts"
    assert config.headless is True


def test_load_config_honors_overrides():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "FORUM_URL": "https://example.test/x",
        "DB_PATH": "/tmp/x.sqlite3",
        "CHARTS_DIR": "/tmp/charts",
        "HEADLESS": "0",
    }
    config = load_config(env)
    assert config.forum_url == "https://example.test/x"
    assert config.db_path == "/tmp/x.sqlite3"
    assert config.charts_dir == "/tmp/charts"
    assert config.headless is False


def test_load_config_raises_when_required_missing():
    with pytest.raises(ConfigError) as exc:
        load_config({"TELEGRAM_BOT_TOKEN": "tok"})
    assert "TELEGRAM_CHAT_ID" in str(exc.value)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_util.py tests/test_config.py -v`
Expected: FAIL — collection/import errors until Step 2 files exist (if you wrote tests first) or, if files exist, all PASS. If any assertion fails, fix the config/util code, not the test.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_util.py tests/test_config.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt .gitignore .env.example hadar_tracker/__init__.py hadar_tracker/models.py hadar_tracker/util.py hadar_tracker/config.py tests/__init__.py tests/fixtures/.gitkeep tests/test_util.py tests/test_config.py
git commit -m "feat: scaffold project with shared models, config, and util"
```

---

## Task 2: Live-page investigation (real Playwright session)

**Purpose:** Resolve the spec's four open items before scraper selectors are finalized. This task is **investigative**, not TDD — its deliverables are a captured fixture and a findings document, not a passing unit test. That is intentional and spec-mandated ("first thing to check once we're in a real browser session"). Verification is a concrete checklist, below.

**Prerequisite (run once, locally):**

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# bash/Linux/macOS:    source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

**Files:**
- Create: `scripts/inspect_page.py`
- Create: `tests/fixtures/user_messages_page1.html` (captured output)
- Create: `docs/superpowers/notes/2026-07-21-page-structure.md` (findings)

**Interfaces:**
- Consumes: `hadar_tracker.config.DEFAULT_FORUM_URL`.
- Produces: documented answers that pin the selector constants used in Task 4 (`POST_CONTAINER_SELECTOR`, `POST_ID_ATTR`, `POST_TIMESTAMP_SELECTOR`, `POST_TEXT_SELECTOR`, `CHART_IMG_SELECTOR`) and the pagination scheme used in Task 5 (`page_url`).

- [ ] **Step 1: Write the inspection script**

`scripts/inspect_page.py`:

```python
"""One-off, non-headless page inspection for HadarTracker Task 2.

Run:  python scripts/inspect_page.py
Opens Hadar's message feed in a visible browser, waits for JS to render,
dumps the rendered HTML + a full-page screenshot to tests/fixtures/, and
prints every network request so you can spot an underlying data endpoint.
This script is NOT imported by the app; it is a manual investigation tool.
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
        browser = p.chromium.launch(headless=False)
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

        input(
            "\nInspect the page + DevTools now. Note the post-container selector, "
            "post-id attribute, date/text selectors, chart <img> selector, and how "
            "pagination works. Press Enter to close the browser..."
        )
        browser.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the inspection script against the live site**

Run: `python scripts/inspect_page.py`
Expected: a visible Chromium window loads Hadar's feed; posts are visible; `tests/fixtures/user_messages_page1.html` and `.png` are written; the terminal prints the network request list.

- [ ] **Step 3: Answer the four open items and write the findings doc**

While the browser is open, use DevTools (Elements + Network) to determine:

1. **Load mechanism** — Are posts rendered into the DOM after an XHR/fetch to a JSON endpoint (prefer hitting that endpoint later — faster/more robust), or rendered server-side into the ASP.NET markup after a postback? Record the actual answer.
2. **Login required?** — Confirm the feed shows full post text while logged out. If it does not, record exactly what is gated (this becomes a new task, not a silent change — see "Deviations" note at the end of this plan).
3. **Selectors** — Identify the real values for each constant Task 4 will use:
   - post container element + CSS selector
   - the attribute or child element carrying the stable per-post id
   - the timestamp element selector
   - the post-body text selector
   - the embedded-chart `<img>` selector (confirm charts come from `chart.bursagraph.co.il` or note the real host)
4. **Pagination scheme** — How do you get older posts? A query-string page number (e.g. `&PageNumber=2`), a "load more" button, infinite scroll, or a postback form? Record the exact mechanism so Task 5's `page_url()` / paging loop can be finalized.
5. **Bot detection** — Note any CAPTCHA, Cloudflare interstitial, or rate-limit behavior. If plain Playwright is blocked, record it; the contingency is escalating to Scrapling (out of scope here) — flag it, do not silently work around it.

Write `docs/superpowers/notes/2026-07-21-page-structure.md` with a section per item above, each with the concrete confirmed answer and the exact selector/URL strings.

- [ ] **Step 4: Verify deliverables exist (verification checklist)**

Run: `git status --short tests/fixtures/user_messages_page1.html docs/superpowers/notes/2026-07-21-page-structure.md`
Expected: both files are listed as new/untracked.

Manual confirmation (all must be true before commit):
- `tests/fixtures/user_messages_page1.html` is non-empty and contains Hadar's post text.
- The findings doc answers all five items above with concrete strings (no "TBD").

- [ ] **Step 5: Commit**

```bash
git add scripts/inspect_page.py tests/fixtures/user_messages_page1.html docs/superpowers/notes/2026-07-21-page-structure.md
git commit -m "chore: capture live page structure and document scrape mechanism"
```

Note: do NOT commit `user_messages_page1.png` (it is a large binary debugging aid). It is fine to leave it untracked.

---

## Task 3: SQLite storage layer (`db.py`)

**Note:** This task has no dependency on Task 2 and may be done in parallel with it.

**Files:**
- Create: `hadar_tracker/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing from other tasks (uses stdlib `sqlite3`).
- Produces:
  - `hadar_tracker.db.SCHEMA: str`
  - `hadar_tracker.db.connect(db_path: str) -> sqlite3.Connection` — ensures the parent directory exists; sets `row_factory = sqlite3.Row`.
  - `hadar_tracker.db.init_db(conn: sqlite3.Connection) -> None`
  - `hadar_tracker.db.post_exists(conn: sqlite3.Connection, post_id: str) -> bool`
  - `hadar_tracker.db.insert_post(conn, post_id: str, posted_at: str, raw_text: str, chart_image_path: str | None, scraped_at: str) -> bool` — INSERT OR IGNORE; returns `True` iff a new row was inserted (this makes it safe for both `check.py` and the idempotent `backfill.py`).
  - `hadar_tracker.db.count_posts(conn: sqlite3.Connection) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/test_db.py`:

```python
from hadar_tracker import db


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_insert_and_exists():
    conn = make_conn()
    assert db.post_exists(conn, "p1") is False
    inserted = db.insert_post(conn, "p1", "2026-07-21T10:00:00+00:00", "hello", None, "2026-07-21T10:05:00+00:00")
    assert inserted is True
    assert db.post_exists(conn, "p1") is True
    assert db.count_posts(conn) == 1


def test_insert_is_idempotent_on_post_id():
    conn = make_conn()
    assert db.insert_post(conn, "p1", "t1", "first", None, "s1") is True
    # Same post_id again — must be ignored, not duplicated, and report not-new.
    assert db.insert_post(conn, "p1", "t1", "changed", "chart.png", "s2") is False
    assert db.count_posts(conn) == 1
    row = conn.execute("SELECT raw_text, chart_image_path FROM posts WHERE post_id = 'p1'").fetchone()
    assert row["raw_text"] == "first"
    assert row["chart_image_path"] is None


def test_stores_chart_image_path():
    conn = make_conn()
    db.insert_post(conn, "p2", "t", "with chart", "data/charts/p2.png", "s")
    row = conn.execute("SELECT chart_image_path FROM posts WHERE post_id = 'p2'").fetchone()
    assert row["chart_image_path"] == "data/charts/p2.png"


def test_connect_creates_parent_directory(tmp_path):
    db_file = tmp_path / "nested" / "sub" / "hadar.sqlite3"
    conn = db.connect(str(db_file))
    db.init_db(conn)
    assert db_file.parent.exists()
    assert db.count_posts(conn) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.db'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/db.py`:

```python
from __future__ import annotations

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    post_id          TEXT PRIMARY KEY,
    posted_at        TEXT NOT NULL,
    raw_text         TEXT NOT NULL,
    chart_image_path TEXT,
    scraped_at       TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database at db_path.

    Ensures the parent directory exists so the very first run on a fresh VPS
    does not fail on a missing `data/` folder.
    """
    if db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def post_exists(conn: sqlite3.Connection, post_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    return row is not None


def insert_post(
    conn: sqlite3.Connection,
    post_id: str,
    posted_at: str,
    raw_text: str,
    chart_image_path: str | None,
    scraped_at: str,
) -> bool:
    """Insert a post, ignoring it if post_id already exists.

    Returns True iff a new row was actually inserted. Safe for both the
    incremental check and the idempotent/resumable backfill.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO posts "
        "(post_id, posted_at, raw_text, chart_image_path, scraped_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (post_id, posted_at, raw_text, chart_image_path, scraped_at),
    )
    conn.commit()
    return cur.rowcount == 1


def count_posts(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/db.py tests/test_db.py
git commit -m "feat: add SQLite storage layer with idempotent insert"
```

---

## Task 4: HTML parsing (`scraper/parser.py`)

**Files:**
- Create: `hadar_tracker/scraper/__init__.py`
- Create: `hadar_tracker/scraper/parser.py`
- Create: `tests/fixtures/sample_posts.html`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `hadar_tracker.models.Post`.
- Produces:
  - Selector constants (top of `parser.py`, reconciled with Task 2 findings): `POST_CONTAINER_SELECTOR`, `POST_ID_ATTR`, `POST_TIMESTAMP_SELECTOR`, `POST_TEXT_SELECTOR`, `CHART_IMG_SELECTOR` (all `str`).
  - `hadar_tracker.scraper.parser.parse_posts(html: str) -> list[Post]` — pure function, no network.

- [ ] **Step 1: Create the deterministic fixture**

`tests/fixtures/sample_posts.html` (hand-authored to match the selector constants; reconcile with the real `user_messages_page1.html` from Task 2 in Step 6):

```html
<!DOCTYPE html>
<html lang="he">
<head><meta charset="utf-8"><title>Hadar messages</title></head>
<body>
  <div id="posts">
    <div class="forum-message" data-message-id="1001">
      <span class="message-date">21/07/2026 10:15</span>
      <div class="message-body">קניתי מניה היום בפתיחה</div>
    </div>
    <div class="forum-message" data-message-id="1002">
      <span class="message-date">21/07/2026 11:40</span>
      <div class="message-body">גרף עדכני מצורף</div>
      <img class="chart" src="https://chart.bursagraph.co.il/chart?symbol=TEVA" alt="chart">
    </div>
    <div class="forum-message" data-message-id="1003">
      <span class="message-date">21/07/2026 12:05</span>
      <div class="message-body">סגרתי חצי פוזיציה</div>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parser.py`:

```python
import pathlib

from hadar_tracker.scraper.parser import parse_posts

FIXTURE = pathlib.Path("tests/fixtures/sample_posts.html").read_text(encoding="utf-8")


def test_parses_all_posts():
    posts = parse_posts(FIXTURE)
    assert [p.post_id for p in posts] == ["1001", "1002", "1003"]


def test_extracts_text_and_timestamp():
    posts = parse_posts(FIXTURE)
    first = posts[0]
    assert first.posted_at == "21/07/2026 10:15"
    assert "קניתי מניה" in first.raw_text


def test_detects_chart_and_builds_selector():
    posts = parse_posts(FIXTURE)
    with_chart = posts[1]
    without_chart = posts[2]
    assert with_chart.has_chart is True
    assert with_chart.chart_selector == (
        "div.forum-message[data-message-id='1002'] "
        "img[src*='chart.bursagraph.co.il']"
    )
    assert without_chart.has_chart is False
    assert without_chart.chart_selector is None


def test_empty_html_returns_empty_list():
    assert parse_posts("<html><body></body></html>") == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.scraper.parser'`.

- [ ] **Step 4: Write the implementation**

`hadar_tracker/scraper/__init__.py`: empty file.

`hadar_tracker/scraper/parser.py`:

```python
from __future__ import annotations

from bs4 import BeautifulSoup

from hadar_tracker.models import Post

# --- Selectors -------------------------------------------------------------
# These placeholder-but-realistic values match tests/fixtures/sample_posts.html.
# Reconcile them with the real DOM captured in Task 2
# (docs/superpowers/notes/2026-07-21-page-structure.md). If the real structure
# differs, update these constants AND tests/fixtures/sample_posts.html together.
POST_CONTAINER_SELECTOR = "div.forum-message"
POST_ID_ATTR = "data-message-id"
POST_TIMESTAMP_SELECTOR = ".message-date"
POST_TEXT_SELECTOR = ".message-body"
CHART_IMG_SELECTOR = "img[src*='chart.bursagraph.co.il']"
# ---------------------------------------------------------------------------


def parse_posts(html: str) -> list[Post]:
    """Parse rendered HTML into Post objects. Pure — no network, no browser."""
    soup = BeautifulSoup(html, "html.parser")
    posts: list[Post] = []

    for node in soup.select(POST_CONTAINER_SELECTOR):
        post_id = node.get(POST_ID_ATTR)
        if not post_id:
            # A container without a stable id is unusable — skip it.
            continue

        date_node = node.select_one(POST_TIMESTAMP_SELECTOR)
        posted_at = date_node.get_text(strip=True) if date_node else ""

        text_node = node.select_one(POST_TEXT_SELECTOR)
        raw_text = text_node.get_text("\n", strip=True) if text_node else ""

        chart_img = node.select_one(CHART_IMG_SELECTOR)
        has_chart = chart_img is not None
        chart_selector = (
            f"{POST_CONTAINER_SELECTOR}[{POST_ID_ATTR}='{post_id}'] "
            f"{CHART_IMG_SELECTOR}"
            if has_chart
            else None
        )

        posts.append(
            Post(
                post_id=str(post_id),
                posted_at=posted_at,
                raw_text=raw_text,
                has_chart=has_chart,
                chart_selector=chart_selector,
            )
        )

    return posts
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_parser.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Reconcile selectors with the real page (Task 2 output)**

Open `docs/superpowers/notes/2026-07-21-page-structure.md`. Compare each selector constant against the real values recorded there. If any differ:
1. Update the constant in `parser.py`.
2. Update `tests/fixtures/sample_posts.html` so its structure matches the real DOM (keep 3 posts, one with a chart, so the assertions stay meaningful).
3. Re-run `python -m pytest tests/test_parser.py -v` — must still PASS.

If the real values match the placeholders exactly, record "confirmed unchanged" in the findings doc and move on.

- [ ] **Step 7: Commit**

```bash
git add hadar_tracker/scraper/__init__.py hadar_tracker/scraper/parser.py tests/fixtures/sample_posts.html tests/test_parser.py
git commit -m "feat: add HTML post parser with fixture-based tests"
```

---

## Task 5: Browser I/O + scrape engine (`scraper/browser.py`, `scraper/engine.py`)

**Files:**
- Create: `hadar_tracker/scraper/browser.py`
- Create: `hadar_tracker/scraper/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `hadar_tracker.scraper.parser.parse_posts`, `hadar_tracker.scraper.parser.POST_CONTAINER_SELECTOR`, `hadar_tracker.models.Post`.
- Produces:
  - `hadar_tracker.scraper.browser.render_page(url: str, wait_selector: str, headless: bool = True, timeout_ms: int = 30000) -> str`
  - `hadar_tracker.scraper.browser.screenshot_element(url: str, selector: str, out_path: str, headless: bool = True, timeout_ms: int = 30000) -> None`
  - `hadar_tracker.scraper.engine.ScrapeError(Exception)`
  - `hadar_tracker.scraper.engine.page_url(base_url: str, page_num: int) -> str`
  - `hadar_tracker.scraper.engine.fetch_latest(forum_url: str, headless: bool = True) -> list[Post]` — raises `ScrapeError` when zero posts parse (surfaces layout breakage loudly, per spec).
  - `hadar_tracker.scraper.engine.iter_backward(forum_url: str, headless: bool = True, start_page: int = 1, max_pages: int | None = None) -> Iterator[tuple[str, Post]]` — yields `(source_url, post)` so a chart on page N can be screenshotted from its own page.

**Note on `browser.py`:** it wraps Playwright I/O and is exercised only by the live smoke test (Step 6) and manual runs, not by unit tests — unit tests monkeypatch `engine`'s reference to `render_page`. This keeps the test suite hermetic (Global Constraint: tests independent of live network).

- [ ] **Step 1: Write the failing tests**

`tests/test_engine.py`:

```python
import pathlib

import pytest

from hadar_tracker.scraper import engine
from hadar_tracker.models import Post

SAMPLE = pathlib.Path("tests/fixtures/sample_posts.html").read_text(encoding="utf-8")
EMPTY = "<html><body></body></html>"


def test_page_url_first_page_is_base():
    assert engine.page_url("https://x.test/f?UserId=1", 1) == "https://x.test/f?UserId=1"


def test_page_url_appends_page_number_with_existing_query():
    assert engine.page_url("https://x.test/f?UserId=1", 3) == "https://x.test/f?UserId=1&PageNumber=3"


def test_page_url_appends_page_number_without_query():
    assert engine.page_url("https://x.test/f", 2) == "https://x.test/f?PageNumber=2"


def test_fetch_latest_parses_rendered_html(monkeypatch):
    monkeypatch.setattr(engine.browser, "render_page", lambda *a, **k: SAMPLE)
    posts = engine.fetch_latest("https://x.test/f")
    assert [p.post_id for p in posts] == ["1001", "1002", "1003"]


def test_fetch_latest_raises_when_no_posts(monkeypatch):
    monkeypatch.setattr(engine.browser, "render_page", lambda *a, **k: EMPTY)
    with pytest.raises(engine.ScrapeError):
        engine.fetch_latest("https://x.test/f")


def test_iter_backward_yields_source_url_and_stops_on_empty_page(monkeypatch):
    # Page 1 -> sample (3 posts), page 2 -> empty (stop).
    calls = {"n": 0}

    def fake_render(url, wait_selector, headless=True, timeout_ms=30000):
        calls["n"] += 1
        return SAMPLE if calls["n"] == 1 else EMPTY

    monkeypatch.setattr(engine.browser, "render_page", fake_render)
    results = list(engine.iter_backward("https://x.test/f"))
    assert len(results) == 3
    src_url, post = results[0]
    assert src_url == "https://x.test/f"
    assert isinstance(post, Post)


def test_iter_backward_respects_max_pages(monkeypatch):
    monkeypatch.setattr(engine.browser, "render_page", lambda *a, **k: SAMPLE)
    results = list(engine.iter_backward("https://x.test/f", max_pages=2))
    # 2 pages x 3 posts each, never runs out because render always returns SAMPLE.
    assert len(results) == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.scraper.engine'`.

- [ ] **Step 3: Write `browser.py`**

`hadar_tracker/scraper/browser.py`:

```python
from __future__ import annotations

from playwright.sync_api import sync_playwright


def render_page(
    url: str,
    wait_selector: str,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> str:
    """Load `url` in headless Chromium, wait for `wait_selector` (the post
    container, so JS/AJAX has populated the feed), and return rendered HTML.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms)
            page.wait_for_selector(wait_selector, timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()


def screenshot_element(
    url: str,
    selector: str,
    out_path: str,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> None:
    """Load `url`, find `selector`, and screenshot just that element to
    `out_path` (archives an embedded chart before its live source can change).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms)
            page.wait_for_selector(selector, timeout=timeout_ms)
            page.locator(selector).first.screenshot(path=out_path)
        finally:
            browser.close()
```

- [ ] **Step 4: Write `engine.py`**

`hadar_tracker/scraper/engine.py`:

```python
from __future__ import annotations

from typing import Iterator

from hadar_tracker.models import Post
from hadar_tracker.scraper import browser
from hadar_tracker.scraper.parser import POST_CONTAINER_SELECTOR, parse_posts


class ScrapeError(Exception):
    """Raised when a page renders but yields no parseable posts.

    Surfaces layout breakage / load failure loudly instead of as an empty
    success (Global Constraint: no silent failures).
    """


def page_url(base_url: str, page_num: int) -> str:
    """Return the URL for a given history page.

    Page 1 is the base URL unchanged. Later pages append a `PageNumber` query
    parameter. NOTE: if Task 2 found a different pagination mechanism (load-more
    button / infinite scroll / postback), replace this helper and the loop in
    `iter_backward` accordingly, per the findings doc.
    """
    if page_num <= 1:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}PageNumber={page_num}"


def fetch_latest(forum_url: str, headless: bool = True) -> list[Post]:
    """Render the first page and parse the newest posts.

    Raises ScrapeError if zero posts parse (posts were expected).
    """
    html = browser.render_page(
        forum_url, wait_selector=POST_CONTAINER_SELECTOR, headless=headless
    )
    posts = parse_posts(html)
    if not posts:
        raise ScrapeError(
            "zero posts parsed from rendered page — layout may have changed "
            "or the page failed to load"
        )
    return posts


def iter_backward(
    forum_url: str,
    headless: bool = True,
    start_page: int = 1,
    max_pages: int | None = None,
) -> Iterator[tuple[str, Post]]:
    """Yield (source_url, Post) pages-backward through post history.

    Stops when a page yields no posts (end of history) or when `max_pages`
    pages have been fetched. Yielding the source URL lets the caller
    screenshot a chart from the exact page the post lives on.
    """
    page_num = start_page
    while max_pages is None or page_num < start_page + max_pages:
        url = page_url(forum_url, page_num)
        html = browser.render_page(
            url, wait_selector=POST_CONTAINER_SELECTOR, headless=headless
        )
        posts = parse_posts(html)
        if not posts:
            return
        for post in posts:
            yield url, post
        page_num += 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_engine.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Live smoke test (manual, not committed)**

Run a one-liner against the real site to confirm `browser.py` + real selectors work end-to-end:

```bash
python -c "from hadar_tracker.scraper.engine import fetch_latest; from hadar_tracker.config import DEFAULT_FORUM_URL; ps = fetch_latest(DEFAULT_FORUM_URL); print(len(ps), 'posts'); print(ps[0].posted_at, ps[0].raw_text[:60])"
```

Expected: prints a non-zero post count and the newest post's timestamp + text snippet. If it raises `ScrapeError` or a Playwright timeout, revisit the selector constants (Task 4 Step 6) and `wait_selector` before proceeding.

- [ ] **Step 7: Commit**

```bash
git add hadar_tracker/scraper/browser.py hadar_tracker/scraper/engine.py tests/test_engine.py
git commit -m "feat: add Playwright browser I/O and scrape engine"
```

---

## Task 6: Telegram notifier (`notifier.py`)

**Files:**
- Create: `hadar_tracker/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `telegram.Bot` (from python-telegram-bot).
- Produces:
  - `hadar_tracker.notifier.send_post(bot_token: str, chat_id: str, text: str, image_path: str | None = None) -> None` — one message per post; sends a photo with caption when `image_path` is set, else a text message.
  - `hadar_tracker.notifier.send_alert(bot_token: str, chat_id: str, message: str) -> None` — sends a prefixed failure alert.

**Design note:** python-telegram-bot v21 is async. `notifier` exposes synchronous wrappers (`asyncio.run(...)`) so `check.py`/`backfill.py` stay simple synchronous scripts. Telegram photo captions are capped at 1024 chars, so a photo caption is truncated to 1024; text-only messages use the full text (Telegram's 4096 limit is far above typical post length).

- [ ] **Step 1: Write the failing tests**

`tests/test_notifier.py`:

```python
import hadar_tracker.notifier as notifier


class FakeBot:
    """Records calls; supports `async with bot` like telegram.Bot."""

    last = {}

    def __init__(self, token):
        FakeBot.last["token"] = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_message(self, chat_id, text):
        FakeBot.last["kind"] = "message"
        FakeBot.last["chat_id"] = chat_id
        FakeBot.last["text"] = text

    async def send_photo(self, chat_id, photo, caption):
        FakeBot.last["kind"] = "photo"
        FakeBot.last["chat_id"] = chat_id
        FakeBot.last["caption"] = caption


def test_send_post_text_only(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "hello world")
    assert FakeBot.last["kind"] == "message"
    assert FakeBot.last["chat_id"] == "42"
    assert FakeBot.last["text"] == "hello world"
    assert FakeBot.last["token"] == "tok"


def test_send_post_with_image(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "chart post", str(img))
    assert FakeBot.last["kind"] == "photo"
    assert FakeBot.last["caption"] == "chart post"


def test_send_post_truncates_long_caption(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "x" * 2000, str(img))
    assert len(FakeBot.last["caption"]) == 1024


def test_send_alert_prefixes_message(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_alert("tok", "42", "scraper run failed: boom")
    assert FakeBot.last["kind"] == "message"
    assert "scraper run failed: boom" in FakeBot.last["text"]
    assert "HadarTracker" in FakeBot.last["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.notifier'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/notifier.py`:

```python
from __future__ import annotations

import asyncio

from telegram import Bot

_CAPTION_LIMIT = 1024


def send_post(
    bot_token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
) -> None:
    """Send one Telegram message for a post: photo+caption if image_path is
    set, otherwise a plain text message."""
    asyncio.run(_send_post_async(bot_token, chat_id, text, image_path))


def send_alert(bot_token: str, chat_id: str, message: str) -> None:
    """Send a scrape-failure alert so failures are never silent."""
    asyncio.run(_send_alert_async(bot_token, chat_id, message))


async def _send_post_async(
    bot_token: str,
    chat_id: str,
    text: str,
    image_path: str | None,
) -> None:
    bot = Bot(token=bot_token)
    async with bot:
        if image_path:
            with open(image_path, "rb") as handle:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=handle,
                    caption=text[:_CAPTION_LIMIT],
                )
        else:
            await bot.send_message(chat_id=chat_id, text=text)


async def _send_alert_async(
    bot_token: str,
    chat_id: str,
    message: str,
) -> None:
    bot = Bot(token=bot_token)
    async with bot:
        await bot.send_message(
            chat_id=chat_id, text=f"[HadarTracker] {message}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram notifier for posts and failure alerts"
```

---

## Task 7: Incremental diff/insert/notify core (`check.py` — `process_new_posts`)

**Files:**
- Create: `hadar_tracker/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `hadar_tracker.models.Post`, `hadar_tracker.config.Config`, `hadar_tracker.db` (`post_exists`, `insert_post`), `hadar_tracker.scraper.browser.screenshot_element`, `hadar_tracker.notifier.send_post`, `hadar_tracker.util.now_iso`.
- Produces:
  - `hadar_tracker.check.process_new_posts(conn, config: Config, posts: list[Post], screenshot=None, send_post=None) -> list[Post]` — inserts only unseen posts, screenshots any chart, sends one notification each, returns the list of newly-processed posts. `screenshot`/`send_post` are injected for testability; when left `None` they resolve to `browser.screenshot_element` / `notifier.send_post` **at call time** (so `run_check` in Task 8 can be tested by monkeypatching `notifier.send_post`).

- [ ] **Step 1: Write the failing tests**

`tests/test_check.py`:

```python
from hadar_tracker import check, db
from hadar_tracker.config import Config
from hadar_tracker.models import Post


def make_config(tmp_path):
    return Config(
        forum_url="https://x.test/f",
        db_path=":memory:",
        charts_dir=str(tmp_path / "charts"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        headless=True,
    )


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_process_inserts_and_notifies_new_posts(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []
    shots = []

    def fake_send(token, chat_id, text, image_path=None):
        sent.append((text, image_path))

    def fake_shot(url, selector, out_path, headless=True):
        shots.append((url, selector, out_path))

    posts = [
        Post("1001", "t1", "no chart", has_chart=False),
        Post("1002", "t2", "has chart", has_chart=True,
             chart_selector="div.forum-message[data-message-id='1002'] img"),
    ]
    new = check.process_new_posts(conn, config, posts, screenshot=fake_shot, send_post=fake_send)

    assert [p.post_id for p in new] == ["1001", "1002"]
    assert db.count_posts(conn) == 2
    assert len(sent) == 2
    # Only the charted post was screenshotted, to the expected path.
    assert len(shots) == 1
    assert shots[0][2].endswith("1002.png")
    # The charted post's notification carried the saved image path.
    assert sent[1] == ("has chart", shots[0][2])


def test_process_skips_already_seen_posts(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    db.insert_post(conn, "1001", "t1", "old", None, "s1")
    sent = []

    posts = [Post("1001", "t1", "old", has_chart=False)]
    new = check.process_new_posts(
        conn, config, posts,
        screenshot=lambda *a, **k: None,
        send_post=lambda *a, **k: sent.append(a),
    )
    assert new == []
    assert sent == []
    assert db.count_posts(conn) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.check'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/check.py`:

```python
from __future__ import annotations

import os

from hadar_tracker import db, notifier
from hadar_tracker.config import Config
from hadar_tracker.models import Post
from hadar_tracker.scraper import browser
from hadar_tracker.util import now_iso


def process_new_posts(
    conn,
    config: Config,
    posts: list[Post],
    screenshot=None,
    send_post=None,
) -> list[Post]:
    """Insert unseen posts, archive charts, and notify — one message each.

    `screenshot` and `send_post` are injected so this is unit-testable without
    a live browser or Telegram. They resolve to the real functions at call time
    (not as def-time defaults) so callers like run_check can be tested by
    monkeypatching `notifier.send_post`. Returns the posts newly processed.
    """
    if screenshot is None:
        screenshot = browser.screenshot_element
    if send_post is None:
        send_post = notifier.send_post

    new_posts: list[Post] = []
    for post in posts:
        if db.post_exists(conn, post.post_id):
            continue

        chart_path: str | None = None
        if post.has_chart and post.chart_selector:
            os.makedirs(config.charts_dir, exist_ok=True)
            chart_path = os.path.join(config.charts_dir, f"{post.post_id}.png")
            screenshot(
                config.forum_url,
                post.chart_selector,
                chart_path,
                headless=config.headless,
            )

        db.insert_post(
            conn,
            post.post_id,
            post.posted_at,
            post.raw_text,
            chart_path,
            now_iso(),
        )
        send_post(
            config.telegram_bot_token,
            config.telegram_chat_id,
            post.raw_text,
            chart_path,
        )
        new_posts.append(post)

    return new_posts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/check.py tests/test_check.py
git commit -m "feat: add incremental diff/insert/notify core"
```

---

## Task 8: Check orchestration + error handling + CLI (`check.py` — `run_check`, `main`)

**Files:**
- Modify: `hadar_tracker/check.py` (append `run_check` and `main`)
- Test: `tests/test_check.py` (add cases)

**Interfaces:**
- Consumes: `hadar_tracker.config.load_config`, `hadar_tracker.db` (`connect`, `init_db`), `hadar_tracker.scraper.engine.fetch_latest`, `hadar_tracker.notifier.send_alert`, and `process_new_posts` from Task 7.
- Produces:
  - `hadar_tracker.check.run_check(config: Config | None = None) -> int` — full incremental run; returns exit code `0` on success, `1` on scrape failure (after logging + sending a Telegram alert). No silent failures.
  - `hadar_tracker.check.main() -> None` — CLI entry: `sys.exit(run_check())`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_check.py`)**

```python
from hadar_tracker.scraper import engine


def test_run_check_success_path(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    fetched = [Post("2001", "t", "brand new post", has_chart=False)]
    monkeypatch.setattr(engine, "fetch_latest", lambda url, headless=True: fetched)
    sent = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_post",
        lambda token, chat_id, text, image_path=None: sent.append(text),
    )
    rc = check.run_check(config)
    assert rc == 0
    assert sent == ["brand new post"]


def test_run_check_reports_failure_and_alerts(tmp_path, monkeypatch):
    config = make_config(tmp_path)

    def boom(url, headless=True):
        raise engine.ScrapeError("layout changed")

    monkeypatch.setattr(engine, "fetch_latest", boom)
    alerts = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_alert",
        lambda token, chat_id, message: alerts.append(message),
    )
    rc = check.run_check(config)
    assert rc == 1
    assert len(alerts) == 1
    assert "layout changed" in alerts[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check.py -v`
Expected: FAIL — `AttributeError: module 'hadar_tracker.check' has no attribute 'run_check'`.

- [ ] **Step 3: Append the implementation to `hadar_tracker/check.py`**

Add these imports to the top of `hadar_tracker/check.py` (alongside the existing ones):

```python
import logging
import sys

from hadar_tracker.config import load_config
from hadar_tracker.scraper import engine
```

Append to the end of `hadar_tracker/check.py`:

```python
def run_check(config: Config | None = None) -> int:
    """Run one incremental check. Returns 0 on success, 1 on failure.

    On failure the error is logged AND a Telegram alert is sent AND we return
    non-zero — the spec's no-silent-failure contract.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("hadar_tracker.check")

    if config is None:
        config = load_config()

    conn = db.connect(config.db_path)
    db.init_db(conn)

    try:
        posts = engine.fetch_latest(config.forum_url, headless=config.headless)
    except Exception as exc:  # noqa: BLE001 - fail loudly on ANY scrape error
        log.error("scrape failed: %s", exc)
        try:
            notifier.send_alert(
                config.telegram_bot_token,
                config.telegram_chat_id,
                f"scraper run failed: {exc}",
            )
        except Exception as alert_exc:  # noqa: BLE001
            log.error("failed to send Telegram alert: %s", alert_exc)
        return 1

    new_posts = process_new_posts(conn, config, posts)
    log.info("check complete: %d new post(s)", len(new_posts))
    return 0


def main() -> None:
    sys.exit(run_check())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check.py -v`
Expected: PASS (4 tests total in the file).

- [ ] **Step 5: Full-suite regression check**

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1, 3, 4, 5, 6, 7, 8.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/check.py tests/test_check.py
git commit -m "feat: add check orchestration, error handling, and CLI entry"
```

---

## Task 9: Resumable historical backfill (`backfill.py`)

**Files:**
- Create: `hadar_tracker/backfill.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `hadar_tracker.config.load_config`/`Config`, `hadar_tracker.db` (`connect`, `init_db`, `post_exists`, `insert_post`), `hadar_tracker.scraper.engine.iter_backward` (yields `(source_url, Post)`), `hadar_tracker.scraper.browser.screenshot_element`, `hadar_tracker.util.now_iso`.
- Produces:
  - `hadar_tracker.backfill.run_backfill(config: Config | None = None, max_pages: int | None = None, screenshot=browser.screenshot_element) -> int` — pages backward, upserts by `post_id` (idempotent/resumable), screenshots charts from each post's source page; returns exit code (`0` success, `1` on error mid-crawl, after logging progress).
  - `hadar_tracker.backfill.main() -> None` — CLI entry with `--max-pages` argument.

- [ ] **Step 1: Write the failing tests**

`tests/test_backfill.py`:

```python
from hadar_tracker import backfill, db
from hadar_tracker.config import Config
from hadar_tracker.models import Post
from hadar_tracker.scraper import engine


def make_config(tmp_path):
    return Config(
        forum_url="https://x.test/f",
        db_path=str(tmp_path / "hadar.sqlite3"),
        charts_dir=str(tmp_path / "charts"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        headless=True,
    )


def test_backfill_inserts_all_and_is_idempotent(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    history = [
        ("https://x.test/f", Post("1", "t1", "a", has_chart=False)),
        ("https://x.test/f", Post("2", "t2", "b", has_chart=False)),
        ("https://x.test/f?PageNumber=2", Post("3", "t3", "c", has_chart=False)),
    ]
    monkeypatch.setattr(engine, "iter_backward", lambda *a, **k: iter(history))

    rc = backfill.run_backfill(config, screenshot=lambda *a, **k: None)
    assert rc == 0
    conn = db.connect(config.db_path)
    assert db.count_posts(conn) == 3

    # Rerun: same history, nothing new inserted (idempotent/resumable).
    monkeypatch.setattr(engine, "iter_backward", lambda *a, **k: iter(history))
    rc = backfill.run_backfill(config, screenshot=lambda *a, **k: None)
    assert rc == 0
    conn = db.connect(config.db_path)
    assert db.count_posts(conn) == 3


def test_backfill_screenshots_chart_from_source_url(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    history = [
        ("https://x.test/f?PageNumber=5",
         Post("9", "t", "charted", has_chart=True,
              chart_selector="div.forum-message[data-message-id='9'] img")),
    ]
    monkeypatch.setattr(engine, "iter_backward", lambda *a, **k: iter(history))
    shots = []
    backfill.run_backfill(config, screenshot=lambda url, sel, out, headless=True: shots.append((url, out)))

    assert len(shots) == 1
    # Screenshot taken from the post's own page, not page 1.
    assert shots[0][0] == "https://x.test/f?PageNumber=5"
    assert shots[0][1].endswith("9.png")


def test_backfill_returns_nonzero_on_error(tmp_path, monkeypatch):
    config = make_config(tmp_path)

    def boom(*a, **k):
        raise engine.ScrapeError("boom")

    monkeypatch.setattr(engine, "iter_backward", boom)
    rc = backfill.run_backfill(config, screenshot=lambda *a, **k: None)
    assert rc == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.backfill'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/backfill.py`:

```python
from __future__ import annotations

import argparse
import logging
import os
import sys

from hadar_tracker import db
from hadar_tracker.config import Config, load_config
from hadar_tracker.scraper import browser, engine
from hadar_tracker.util import now_iso


def run_backfill(
    config: Config | None = None,
    max_pages: int | None = None,
    screenshot=browser.screenshot_element,
) -> int:
    """Page backward through history, upserting by post_id.

    Idempotent and resumable: already-stored posts are skipped, so an
    interrupted run can be rerun safely. Returns 0 on success, 1 on error
    (after logging how many posts were inserted before the failure).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("hadar_tracker.backfill")

    if config is None:
        config = load_config()

    conn = db.connect(config.db_path)
    db.init_db(conn)

    inserted = 0
    try:
        for source_url, post in engine.iter_backward(
            config.forum_url, headless=config.headless, max_pages=max_pages
        ):
            if db.post_exists(conn, post.post_id):
                continue

            chart_path: str | None = None
            if post.has_chart and post.chart_selector:
                os.makedirs(config.charts_dir, exist_ok=True)
                chart_path = os.path.join(config.charts_dir, f"{post.post_id}.png")
                screenshot(
                    source_url,
                    post.chart_selector,
                    chart_path,
                    headless=config.headless,
                )

            if db.insert_post(
                conn,
                post.post_id,
                post.posted_at,
                post.raw_text,
                chart_path,
                now_iso(),
            ):
                inserted += 1
    except Exception as exc:  # noqa: BLE001 - report progress, exit non-zero
        log.error("backfill failed after %d inserts: %s", inserted, exc)
        return 1

    log.info("backfill complete: %d new post(s) inserted", inserted)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Hadar's post history.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit how many history pages to crawl (default: until history ends).",
    )
    args = parser.parse_args()
    sys.exit(run_backfill(max_pages=args.max_pages))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backfill.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/backfill.py tests/test_backfill.py
git commit -m "feat: add resumable, idempotent historical backfill"
```

---

## Task 10: Deployment to Oracle VPS (cron/systemd + docs)

**Files:**
- Create: `deploy/run_check.sh`
- Create: `deploy/run_backfill.sh`
- Create: `deploy/hadar-tracker.service`
- Create: `deploy/hadar-tracker.timer`
- Create: `deploy/README.md`

**Interfaces:**
- Consumes: `python -m hadar_tracker.check` (Task 8 `main`), `python -m hadar_tracker.backfill` (Task 9 `main`), `.env` (variables from Task 1's `.env.example`).
- Produces: shell wrappers + systemd units + install docs. No Python interfaces.

- [ ] **Step 1: Write the wrapper scripts**

`deploy/run_check.sh`:

```bash
#!/usr/bin/env bash
# Cron/systemd wrapper: run one incremental check from the repo root.
set -euo pipefail

# Move to the repo root (this script lives in deploy/).
cd "$(dirname "$0")/.."

# Load environment variables from .env if present.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

exec ./.venv/bin/python -m hadar_tracker.check
```

`deploy/run_backfill.sh`:

```bash
#!/usr/bin/env bash
# Manual wrapper: run the historical backfill. Extra args pass through
# (e.g. ./deploy/run_backfill.sh --max-pages 10).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

exec ./.venv/bin/python -m hadar_tracker.backfill "$@"
```

- [ ] **Step 2: Verify the scripts are valid bash**

Run: `bash -n deploy/run_check.sh && bash -n deploy/run_backfill.sh && echo OK`
Expected: prints `OK` (no syntax errors).

- [ ] **Step 3: Write the systemd units**

`deploy/hadar-tracker.service`:

```ini
[Unit]
Description=HadarTracker incremental check (scrape -> store -> notify)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# Adjust User and WorkingDirectory to match the VPS deployment path.
User=ubuntu
WorkingDirectory=/home/ubuntu/HadarTracker
ExecStart=/home/ubuntu/HadarTracker/deploy/run_check.sh
```

`deploy/hadar-tracker.timer`:

```ini
[Unit]
Description=Run HadarTracker check every 10 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
Unit=hadar-tracker.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Write the deployment README**

`deploy/README.md`:

````markdown
# Deploying HadarTracker to the Oracle Cloud VPS

Build and test locally first (`python -m pytest` must be green). Then, on the VPS:

## 1. Clone and set up

```bash
cd ~
git clone <repo-url> HadarTracker
cd HadarTracker
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m playwright install --with-deps chromium
```

`--with-deps` pulls the OS libraries headless Chromium needs on a fresh server.

## 2. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
chmod 600 .env
```

Get a bot token from @BotFather; get your chat id by messaging the bot and
reading `https://api.telegram.org/bot<TOKEN>/getUpdates`.

## 3. Make wrappers executable and smoke-test

```bash
chmod +x deploy/run_check.sh deploy/run_backfill.sh
./deploy/run_check.sh
```

Expected: exit code 0, a log line `check complete: N new post(s)`, and — on the
first run against a populated feed — Telegram messages for the newest posts.

## 4. Schedule it — choose ONE of the two options below

### Option A: systemd timer (recommended)

Edit `User` and `WorkingDirectory` in `deploy/hadar-tracker.service` to match
your path, then:

```bash
sudo cp deploy/hadar-tracker.service /etc/systemd/system/
sudo cp deploy/hadar-tracker.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hadar-tracker.timer
systemctl list-timers hadar-tracker.timer
journalctl -u hadar-tracker.service -n 50 --no-pager
```

### Option B: cron

```bash
crontab -e
```

Add (every 10 minutes; adjust to 15 once cadence is known from backfill):

```
*/10 * * * * /home/ubuntu/HadarTracker/deploy/run_check.sh >> /home/ubuntu/HadarTracker/data/check.log 2>&1
```

`check.py` exits non-zero and sends a Telegram alert on failure, so both the
log file / `journalctl` and Telegram will surface problems — no silent misses.

## 5. (Optional) Run the historical backfill

Not required for launch; needed before Phase 2. Safe to interrupt and rerun.

```bash
./deploy/run_backfill.sh            # full history
./deploy/run_backfill.sh --max-pages 10   # bounded test run
```

## 6. Tuning

Once backfill reveals Hadar's real posting cadence, adjust the interval
(`OnUnitActiveSec` in the timer, or the cron `*/N`) toward the 10–15 min target.
````

- [ ] **Step 5: Commit**

```bash
git add deploy/run_check.sh deploy/run_backfill.sh deploy/hadar-tracker.service deploy/hadar-tracker.timer deploy/README.md
git commit -m "feat: add VPS deployment wrappers, systemd units, and docs"
```

---

## Final verification

- [ ] **Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS — all tests across Tasks 1, 3, 4, 5, 6, 7, 8, 9 (config, util, db, parser, engine, notifier, check, backfill).

- [ ] **Confirm the two entry points import and expose `main`**

Run: `python -c "import hadar_tracker.check as c, hadar_tracker.backfill as b; assert callable(c.main) and callable(b.main); print('entry points OK')"`
Expected: prints `entry points OK`.

---

## Notes on deviations / gaps filled beyond the spec

These are judgment calls made because the spec left them open; a downstream engineer should treat them as the plan's decisions, not the spec's:

1. **Concrete module/file names** within the spec's proposed `scraper/` package: split into `parser.py` (pure), `browser.py` (Playwright I/O), `engine.py` (orchestration) so parsing is unit-testable without a browser (satisfies the spec's fixture-based testing requirement). Added `models.py`, `config.py`, `util.py` as shared support modules.
2. **Parsing library:** chose BeautifulSoup4 for parsing the rendered HTML (Playwright renders; bs4 extracts). The spec fixes Playwright as the browser engine but does not name a parser; bs4 keeps parsing pure and fast to unit-test.
3. **Deterministic fixture (`sample_posts.html`)** with placeholder-but-realistic selectors, plus an explicit reconciliation step (Task 4 Step 6) against Task 2's real capture. This lets parser tests be hermetic and concrete before the live investigation, per the ordering rationale above.
4. **`iter_backward` yields `(source_url, Post)`** rather than bare `Post`, so a chart on history page N is screenshotted from its own page rather than page 1 — closes a correctness gap the spec's prose did not address.
5. **`insert_post` is `INSERT OR IGNORE` returning a "was-new" bool**, serving both `check.py` and the spec's "idempotent/resumable backfill (upsert on post_id)" with one function (DRY) — no separate `upsert` needed.
6. **Config via environment variables** (`.env` + `.env.example`), including `HEADLESS` toggle for the Task 2 headed inspection. The spec did not specify a config mechanism; env vars keep secrets out of git and suit cron/systemd.
7. **Telegram photo caption truncated to 1024 chars** (Telegram's hard limit); full text still stored in SQLite. A rare long charted post's Telegram caption is clipped, but no data is lost in storage.
8. **If Task 2 finds the page requires login or blocks plain Playwright**, that is flagged in the findings doc and becomes a NEW task (login handling, or escalation to Scrapling's stealth fetcher) — per the spec, "a small addition, not a redesign" / "escalate to Scrapling only if plain Playwright gets blocked." This plan does not pre-build either, matching the spec's non-goals.
