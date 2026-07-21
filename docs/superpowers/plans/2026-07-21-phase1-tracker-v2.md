# HadarTracker Phase 1 (v2 — JSON endpoint architecture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status of the prior work (read first):** This is a **standalone continuation plan**. Tasks 1 and 2 of the original plan (`docs/superpowers/plans/2026-07-21-phase1-tracker.md`) are already **complete and committed**:

- **Original Task 1** (`fea24ac`) shipped the package scaffolding — `hadar_tracker/models.py` (`Post`), `hadar_tracker/config.py` (`Config` / `ConfigError` / `load_config` / `DEFAULT_FORUM_URL`), `hadar_tracker/util.py` (`now_iso`), plus `pyproject.toml`, `requirements.txt`, `.gitignore`, `.env.example`, and the `tests/` package. Those files exist; this plan **modifies** some of them.
- **Original Task 2** (`322cc08`) was a live investigation that **overturned the scraping architecture**. Its findings are folded into the revised design spec (`docs/superpowers/specs/2026-07-21-phase1-tracker-design.md`, commit `88cca08`) — the source of truth for this plan. In short: **no browser at all.** Headless Playwright is Cloudflare-blocked (403), but the page's own AJAX endpoint (`POST https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx`, body `ForumId=1&IsFull=1&UserId=5609&m=0`) returns full JSON to a plain HTTP client and is **not** blocked. Phase 1 is a plain-HTTP JSON client — no Playwright, no BeautifulSoup, no HTML parsing.

Because the architecture changed, several original-plan interfaces are now stale and are **replaced** here (the `Post` dataclass fields, the `Config` fields, the `posts` table schema, the entire `scraper/` package, and the deploy steps). This plan **renumbers tasks starting at Task 1** and covers **only the remaining work** to reach a working Phase 1. It does not re-plan the original Tasks 1–2. Where it modifies an already-shipped file, the task says so explicitly and reproduces the full new file contents.

**Goal:** Reliably fetch trader "Hadar"'s public Sponser forum posts from the site's JSON AJAX endpoint, store each post durably and deduplicated in SQLite (new schema), and send a Telegram notification (subject, tickers, reply-context, body, and attached photo when present) for every new post.

**Architecture:** A single Python package (`hadar_tracker`) built around a plain-HTTP JSON client. `scraper/parse.py` is a pure function turning a raw JSON payload into `Post` objects (filter to Hadar's `UserId`, resolve reply→root thread context, extract tickers) — fully unit-testable against a hand-authored fixture with no network. `scraper/client.py` is the thin, mockable `requests` POST that feeds it. `images.py` downloads attached pictures over plain HTTP. `check.py` (the cron job) diffs the latest batch against SQLite, downloads any attachment, and notifies via `notifier.py`. `backfill.py` is an honest stub — the historical mechanism is an unresolved open item (see Notes). SQLite is the single-writer store; Telegram is the only output channel (posts and failure alerts).

**Tech Stack:** Python 3.11+, `requests` (HTTP), SQLite (stdlib `sqlite3`), `python-telegram-bot` (v21, async), `pytest`. **No Playwright, no Chromium, no BeautifulSoup.**

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the design spec (`docs/superpowers/specs/2026-07-21-phase1-tracker-design.md`).

- **Language/engine:** Plain-HTTP JSON client. **No browser, no Playwright, no HTML parsing.** The one and only data source for `check.py` is `POST https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx` with form body `ForumId=1&IsFull=1&UserId=5609&m=0`, sent with an ordinary desktop User-Agent.
- **Filtering:** From the response's `Data` array, keep only items whose `User.UserId == 5609` (Hadar's own posts, root or reply).
- **Thread context:** Items share a thread via `L1` (a thread-group id, not a `MsgId`); the item with `Level == 1` in that group is the root. For a reply (`Level > 1`), record the root's `subject` as its context, resolved by a local lookup within the same response (the root may belong to any user).
- **Storage:** Single-file SQLite database, single writer, no concurrent-access needs. The `posts` table schema is fixed (see Task 2). Do not add columns beyond the spec without adding a task.
- **Notifications:** Telegram via `python-telegram-bot`, to the user's personal chat. One message per new post surfacing: subject line, tickers/tags (the user explicitly wants tickers visible, not just stored), a reply-context line when the post is a reply, the body, and — when `HasImages` is set — the attached picture sent as a photo (the user explicitly wants uploaded pictures shown, not just flagged). Same channel sends scrape-failure alerts.
- **Images:** Two independent sources. (a) **Manually attached pictures** — JSON `HasImages` + `MsgFileName`; download from `https://www.sponser.co.il/ForumFiles/{MsgFileName}` (plain HTTP) and send in the Telegram message. (b) **Ticker hover-popover charts** — OUT OF SCOPE for Phase 1: store the ticker symbols only, never fetch that chart image.
- **No silent failures:** Every `check.py` run either succeeds cleanly or fails loudly — non-zero exit code **and** a clear log line **and** a Telegram alert (`"scraper run failed: ..."`). A missing/empty `Data` where posts were expected is a failure, not an empty success.
- **Backfill is an unresolved open item.** The live endpoint covers only ~1 day of activity, not Hadar's full archive; the mechanism for full history is not yet discovered. `backfill.py` is therefore an honest stub in this plan (see Task 9 and Notes). Not required before Phase 1 launch; required before Phase 2.
- **Access model:** Passive, logged-out reading only. No login, no cookies, no session.
- **Testing discipline:** Unit tests exercise parsing/filtering/thread-resolution and all I/O wrappers against hand-authored fixtures and monkeypatched HTTP — **never** the live network. Manual smoke test against the live endpoint before deploying each change to the VPS.
- **Deployment target:** Runs continuously on the user's Oracle Cloud VPS via systemd timer (or cron); built and tested locally first. Poll interval starts at every 10–15 minutes.

**Fixed request parameters:** `UserId=5609`, `ForumId=1`, `IsFull=1`, `m=0`.

---

## File Structure

Every path is relative to the repo root (worktree) `c:/Users/offir/Desktop/Projects/HadarTracker/.claude/worktrees/phase1-tracker`.

| Path | Responsibility | Status |
|---|---|---|
| `requirements.txt` | Pinned dependency floors: `requests`, `python-telegram-bot`, `pytest`. | **Modify** (drop playwright/bs4) |
| `.env.example` | Documented env-var template (no secrets). | **Modify** |
| `hadar_tracker/models.py` | The `Post` dataclass — the shared shape passed scraper → check. | **Modify** (new fields) |
| `hadar_tracker/config.py` | `Config` + `load_config()`; fails loudly on missing required vars. | **Modify** (new fields) |
| `hadar_tracker/util.py` | `now_iso()`. | Unchanged (Task 1) |
| `hadar_tracker/db.py` | All SQLite access: connect, schema init, existence check, insert-or-ignore, count. No business logic. | **Create** |
| `hadar_tracker/scraper/__init__.py` | Marks the scraper sub-package. Empty. | **Create** |
| `hadar_tracker/scraper/parse.py` | Pure `parse_posts(payload) -> list[Post]` + `parse_date`, `extract_tags`, `ScrapeError`, `HADAR_USER_ID`. No network. | **Create** |
| `hadar_tracker/scraper/client.py` | Thin `requests` POST: `fetch_raw(...)`, `fetch_posts(...) -> list[Post]`. | **Create** |
| `hadar_tracker/images.py` | `download_image(msg_file_name, images_dir) -> str` over plain HTTP. | **Create** |
| `hadar_tracker/notifier.py` | Telegram sending: `format_message(...)`, `send_post(...)`, `send_alert(...)`. | **Create** |
| `hadar_tracker/check.py` | Incremental cron job: `process_new_posts(...)`, `run_check(...)`, `main()`. | **Create** |
| `hadar_tracker/backfill.py` | Honest CLI stub — mechanism undetermined; exits informatively. | **Create** |
| `tests/fixtures/sample_stream.json` | Hand-authored JSON payload matching the real endpoint shape, for parser tests. | **Create** |
| `tests/test_models.py` | Tests for the new `Post` shape. | **Create** |
| `tests/test_config.py` | Tests for `load_config()` (rewritten for new fields). | **Modify** |
| `tests/test_db.py` | Tests for the db layer against a temp/in-memory database. | **Create** |
| `tests/test_parse.py` | Tests for `parse_posts()` against `sample_stream.json`. | **Create** |
| `tests/test_client.py` | Tests for `fetch_raw`/`fetch_posts` with `requests` monkeypatched. | **Create** |
| `tests/test_images.py` | Tests for `download_image` with `requests` monkeypatched. | **Create** |
| `tests/test_notifier.py` | Tests for `format_message`/`send_post`/`send_alert` with a fake `Bot`. | **Create** |
| `tests/test_check.py` | Tests for `process_new_posts` and `run_check` with fakes/mocks. | **Create** |
| `tests/test_backfill.py` | Test that the stub exits informatively. | **Create** |
| `deploy/run_check.sh` | VPS wrapper: load `.env`, run `python -m hadar_tracker.check`. | **Create** |
| `deploy/hadar-tracker.service` | systemd oneshot unit running `run_check.sh`. | **Create** |
| `deploy/hadar-tracker.timer` | systemd timer firing the service every 10 minutes. | **Create** |
| `deploy/README.md` | Oracle VPS install + systemd/cron instructions (no Chromium). | **Create** |

### Note on the existing `test_config.py`

Original Task 1 shipped `tests/test_config.py` asserting the old `Config` fields (`forum_url`, `charts_dir`, `headless`). Task 1 of **this** plan rewrites that file to match the new `Config`. That is a deliberate replacement, not an accident.

---

## Task 1: Migrate the data model, config, and dependencies to the JSON architecture

Replace the browser-era `Post` and `Config` shapes with the JSON-endpoint shapes, and drop the browser dependencies. `util.py` (`now_iso`) is unchanged and untouched.

**Files:**
- Modify: `hadar_tracker/models.py` (replace `Post`)
- Modify: `hadar_tracker/config.py` (replace `Config` + `load_config`)
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `tests/test_config.py`
- Test: `tests/test_models.py` (new), `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from later tasks. Keeps `hadar_tracker.util.now_iso() -> str` (shipped, unchanged).
- Produces:
  - `hadar_tracker.models.Post` — `@dataclass(frozen=True)` with fields, in order:
    `msg_id: str`, `posted_at: str`, `level: int`, `thread_group: str`, `subject: str`, `body: str`, `tags: tuple[str, ...]`, `root_subject: str | None = None`, `image_file_name: str | None = None`, `image_local_path: str | None = None`.
  - `hadar_tracker.config.Config` — `@dataclass(frozen=True)` with fields `db_path: str`, `images_dir: str`, `telegram_bot_token: str`, `telegram_chat_id: str`, `user_id: int`, `forum_id: int`.
  - `hadar_tracker.config.ConfigError(Exception)` (unchanged name), `hadar_tracker.config.DEFAULT_FORUM_URL: str` (retained, unused by app code), `hadar_tracker.config.load_config(env: dict[str, str] | None = None) -> Config`.

- [ ] **Step 1: Replace `hadar_tracker/models.py`**

```python
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
```

- [ ] **Step 2: Replace `hadar_tracker/config.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass

# Retained for reference / the throwaway Task-2 inspection script. The app no
# longer scrapes this HTML page — it hits the JSON endpoint (see scraper/client).
DEFAULT_FORUM_URL = (
    "https://www.sponser.co.il/ForumViewUserMessages.aspx"
    "?UserId=5609&ForumId=1&IsFull=1"
)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    db_path: str
    images_dir: str
    telegram_bot_token: str
    telegram_chat_id: str
    user_id: int
    forum_id: int


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
        db_path=source.get("DB_PATH", "data/hadar.sqlite3"),
        images_dir=source.get("IMAGES_DIR", "data/images"),
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        user_id=int(source.get("USER_ID", "5609")),
        forum_id=int(source.get("FORUM_ID", "1")),
    )
```

- [ ] **Step 3: Replace `requirements.txt`**

```
requests>=2.31
python-telegram-bot>=21.0
pytest>=8.0
```

- [ ] **Step 4: Replace `.env.example`**

```
# Telegram bot credentials (required) — no defaults, load_config() raises without them.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Optional overrides (defaults shown).
DB_PATH=data/hadar.sqlite3
IMAGES_DIR=data/images
USER_ID=5609
FORUM_ID=1
```

- [ ] **Step 5: Write the failing tests**

`tests/test_models.py`:

```python
from hadar_tracker.models import Post


def test_post_defaults_are_none_for_optional_fields():
    p = Post(
        msg_id="1",
        posted_at="2026-07-21T10:00:00",
        level=1,
        thread_group="900",
        subject="s",
        body="b",
        tags=("TEVA",),
    )
    assert p.root_subject is None
    assert p.image_file_name is None
    assert p.image_local_path is None
    assert p.tags == ("TEVA",)


def test_post_is_frozen():
    import dataclasses

    p = Post(
        msg_id="1", posted_at="t", level=2, thread_group="900",
        subject="", body="b", tags=(),
    )
    try:
        p.msg_id = "2"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Post should be frozen")
```

`tests/test_config.py` (replace the whole file):

```python
import pytest

from hadar_tracker.config import Config, ConfigError, load_config


def test_load_config_uses_defaults_when_only_required_present():
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    config = load_config(env)
    assert isinstance(config, Config)
    assert config.db_path == "data/hadar.sqlite3"
    assert config.images_dir == "data/images"
    assert config.user_id == 5609
    assert config.forum_id == 1


def test_load_config_honors_overrides():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "DB_PATH": "/tmp/x.sqlite3",
        "IMAGES_DIR": "/tmp/images",
        "USER_ID": "42",
        "FORUM_ID": "7",
    }
    config = load_config(env)
    assert config.db_path == "/tmp/x.sqlite3"
    assert config.images_dir == "/tmp/images"
    assert config.user_id == 42
    assert config.forum_id == 7


def test_load_config_raises_when_required_missing():
    with pytest.raises(ConfigError) as exc:
        load_config({"TELEGRAM_BOT_TOKEN": "tok"})
    assert "TELEGRAM_CHAT_ID" in str(exc.value)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py tests/test_config.py -v`
Expected: PASS (5 tests). If a `test_config` assertion fails, fix `config.py`, not the test.

- [ ] **Step 7: Commit**

```bash
git add hadar_tracker/models.py hadar_tracker/config.py requirements.txt .env.example tests/test_models.py tests/test_config.py
git commit -m "refactor: migrate Post and Config to JSON-endpoint architecture"
```

---

## Task 2: SQLite storage layer (`db.py`)

**Files:**
- Create: `hadar_tracker/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing from other tasks (stdlib `sqlite3`, `json`).
- Produces:
  - `hadar_tracker.db.SCHEMA: str`
  - `hadar_tracker.db.connect(db_path: str) -> sqlite3.Connection` — ensures the parent directory exists; sets `row_factory = sqlite3.Row`.
  - `hadar_tracker.db.init_db(conn: sqlite3.Connection) -> None`
  - `hadar_tracker.db.post_exists(conn: sqlite3.Connection, msg_id: str) -> bool`
  - `hadar_tracker.db.insert_post(conn, msg_id: str, posted_at: str, level: int, thread_group: str, root_subject: str | None, subject: str, body: str, tags: Sequence[str], image_file_name: str | None, image_local_path: str | None, scraped_at: str) -> bool` — INSERT OR IGNORE; `tags` is JSON-encoded to TEXT internally; returns `True` iff a new row was inserted.
  - `hadar_tracker.db.count_posts(conn: sqlite3.Connection) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/test_db.py`:

```python
import json

from hadar_tracker import db


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_insert_and_exists():
    conn = make_conn()
    assert db.post_exists(conn, "p1") is False
    inserted = db.insert_post(
        conn, "p1", "2026-07-21T10:00:00", 1, "900", None,
        "subj", "body", ("TEVA", "ICL"), None, None, "2026-07-21T10:05:00",
    )
    assert inserted is True
    assert db.post_exists(conn, "p1") is True
    assert db.count_posts(conn) == 1
    row = conn.execute("SELECT * FROM posts WHERE msg_id = 'p1'").fetchone()
    assert row["level"] == 1
    assert row["thread_group"] == "900"
    assert row["subject"] == "subj"
    assert json.loads(row["tags"]) == ["TEVA", "ICL"]


def test_insert_is_idempotent_on_msg_id():
    conn = make_conn()
    assert db.insert_post(
        conn, "p1", "t1", 1, "900", None, "s", "first", (), None, None, "s1"
    ) is True
    # Same msg_id again — ignored, not duplicated, reports not-new.
    assert db.insert_post(
        conn, "p1", "t1", 1, "900", None, "s", "changed", (), None, None, "s2"
    ) is False
    assert db.count_posts(conn) == 1
    row = conn.execute("SELECT body FROM posts WHERE msg_id = 'p1'").fetchone()
    assert row["body"] == "first"


def test_stores_reply_and_image_fields():
    conn = make_conn()
    db.insert_post(
        conn, "p2", "t", 2, "900", "root subj", "", "reply body",
        (), "abc.gif", "data/images/abc.gif", "s",
    )
    row = conn.execute("SELECT * FROM posts WHERE msg_id = 'p2'").fetchone()
    assert row["level"] == 2
    assert row["root_subject"] == "root subj"
    assert row["image_file_name"] == "abc.gif"
    assert row["image_local_path"] == "data/images/abc.gif"


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

import json
import os
import sqlite3
from typing import Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    msg_id           TEXT PRIMARY KEY,
    posted_at        TEXT NOT NULL,
    level            INTEGER NOT NULL,
    thread_group     TEXT NOT NULL,
    root_subject     TEXT,
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    tags             TEXT NOT NULL,
    image_file_name  TEXT,
    image_local_path TEXT,
    scraped_at       TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite database at db_path.

    Ensures the parent directory exists so the first run on a fresh VPS does
    not fail on a missing `data/` folder.
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


def post_exists(conn: sqlite3.Connection, msg_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM posts WHERE msg_id = ?", (msg_id,)
    ).fetchone()
    return row is not None


def insert_post(
    conn: sqlite3.Connection,
    msg_id: str,
    posted_at: str,
    level: int,
    thread_group: str,
    root_subject: str | None,
    subject: str,
    body: str,
    tags: Sequence[str],
    image_file_name: str | None,
    image_local_path: str | None,
    scraped_at: str,
) -> bool:
    """Insert a post, ignoring it if msg_id already exists.

    `tags` is JSON-encoded to a TEXT column here (single source of truth for
    the serialization format). Returns True iff a new row was inserted — safe
    for both the incremental check and any idempotent re-run.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO posts "
        "(msg_id, posted_at, level, thread_group, root_subject, subject, "
        " body, tags, image_file_name, image_local_path, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            msg_id,
            posted_at,
            level,
            thread_group,
            root_subject,
            subject,
            body,
            json.dumps(list(tags)),
            image_file_name,
            image_local_path,
            scraped_at,
        ),
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
git commit -m "feat: add SQLite storage layer with new posts schema"
```

---

## Task 3: Pure JSON parsing / filtering / thread resolution (`scraper/parse.py`)

**Files:**
- Create: `hadar_tracker/scraper/__init__.py`
- Create: `hadar_tracker/scraper/parse.py`
- Create: `tests/fixtures/sample_stream.json`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: `hadar_tracker.models.Post`.
- Produces:
  - `hadar_tracker.scraper.parse.HADAR_USER_ID: int` (= `5609`)
  - `hadar_tracker.scraper.parse.ScrapeError(Exception)`
  - `hadar_tracker.scraper.parse.parse_date(raw: str) -> str` — parses `"DD/MM/YY | HH:MM"` (Israel local time) to a naive ISO 8601 string (see Notes on the timezone decision).
  - `hadar_tracker.scraper.parse.extract_tags(raw) -> tuple[str, ...]` — accepts a delimited string or a list (of strings or `{"Symbol": ...}` dicts); returns cleaned ticker symbols.
  - `hadar_tracker.scraper.parse.parse_posts(payload: dict, user_id: int = HADAR_USER_ID) -> list[Post]` — pure; filters to `user_id`, resolves reply→root subjects, extracts tags/image. Raises `ScrapeError` if the `"Data"` key is missing (shape changed).

- [ ] **Step 1: Create the fixture**

`tests/fixtures/sample_stream.json` (hand-authored to the real endpoint shape seen during the Task-2 investigation; small but exercises filter, thread-resolution, multi-ticker, and image cases):

```json
{
  "Data": [
    {
      "MsgId": 5001,
      "DateCreated": "21/07/26 | 10:32",
      "Level": 1,
      "L1": 900,
      "subject": "תל אביב 35",
      "Msg": "פתיחה חיובית בשוק",
      "Tags": "TA35",
      "HasImages": 0,
      "MsgFileName": null,
      "User": {"UserId": 5609}
    },
    {
      "MsgId": 5002,
      "DateCreated": "21/07/26 | 11:00",
      "Level": 2,
      "L1": 900,
      "subject": "",
      "Msg": "מוסיף פוזיציה, גרף מצורף",
      "Tags": "",
      "HasImages": 1,
      "MsgFileName": "c310bc13-abcd.gif",
      "User": {"UserId": 5609}
    },
    {
      "MsgId": 5003,
      "DateCreated": "21/07/26 | 11:05",
      "Level": 2,
      "L1": 900,
      "subject": "",
      "Msg": "תגובה של משתמש אחר",
      "Tags": "",
      "HasImages": 0,
      "MsgFileName": null,
      "User": {"UserId": 9999}
    },
    {
      "MsgId": 5004,
      "DateCreated": "21/07/26 | 12:00",
      "Level": 1,
      "L1": 901,
      "subject": "טבע",
      "Msg": "קונה טבע היום",
      "Tags": "TEVA, ICL",
      "HasImages": 0,
      "MsgFileName": null,
      "User": {"UserId": 5609}
    }
  ],
  "NumberOfPages": 0,
  "IsMoreMsg": 0
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parse.py`:

```python
import json
import pathlib

import pytest

from hadar_tracker.scraper.parse import (
    HADAR_USER_ID,
    ScrapeError,
    extract_tags,
    parse_date,
    parse_posts,
)

PAYLOAD = json.loads(
    pathlib.Path("tests/fixtures/sample_stream.json").read_text(encoding="utf-8")
)


def test_hadar_user_id_constant():
    assert HADAR_USER_ID == 5609


def test_parse_date_converts_israeli_format_to_iso():
    assert parse_date("21/07/26 | 10:32") == "2026-07-21T10:32:00"


def test_extract_tags_from_delimited_string():
    assert extract_tags("TEVA, ICL") == ("TEVA", "ICL")
    assert extract_tags("") == ()
    assert extract_tags(None) == ()


def test_extract_tags_from_list_of_strings_and_dicts():
    assert extract_tags(["TEVA", "ICL"]) == ("TEVA", "ICL")
    assert extract_tags([{"Symbol": "TEVA"}, {"Symbol": "ICL"}]) == ("TEVA", "ICL")


def test_parse_filters_to_hadar_only():
    posts = parse_posts(PAYLOAD)
    assert [p.msg_id for p in posts] == ["5001", "5002", "5004"]


def test_parse_root_post_fields():
    posts = parse_posts(PAYLOAD)
    root = posts[0]
    assert root.msg_id == "5001"
    assert root.level == 1
    assert root.thread_group == "900"
    assert root.root_subject is None
    assert root.subject == "תל אביב 35"
    assert root.posted_at == "2026-07-21T10:32:00"
    assert root.tags == ("TA35",)
    assert root.image_file_name is None


def test_parse_reply_resolves_root_subject_and_image():
    posts = parse_posts(PAYLOAD)
    reply = posts[1]
    assert reply.msg_id == "5002"
    assert reply.level == 2
    assert reply.root_subject == "תל אביב 35"
    assert reply.image_file_name == "c310bc13-abcd.gif"
    assert reply.image_local_path is None


def test_parse_multi_ticker_post():
    posts = parse_posts(PAYLOAD)
    teva = posts[2]
    assert teva.msg_id == "5004"
    assert teva.tags == ("TEVA", "ICL")


def test_parse_raises_when_data_key_missing():
    with pytest.raises(ScrapeError):
        parse_posts({"NumberOfPages": 0})


def test_parse_empty_data_returns_empty_list():
    assert parse_posts({"Data": []}) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.scraper.parse'`.

- [ ] **Step 4: Write the implementation**

`hadar_tracker/scraper/__init__.py`: empty file.

`hadar_tracker/scraper/parse.py`:

```python
from __future__ import annotations

import re
from datetime import datetime

from hadar_tracker.models import Post

HADAR_USER_ID = 5609

# DateCreated arrives as "DD/MM/YY | HH:MM" in Israel local time. We store the
# parsed value as a naive ISO 8601 string (no tz offset) to stay dependency-free
# on Windows/VPS (see plan Notes on the timezone decision).
_DATE_FORMAT = "%d/%m/%y | %H:%M"


class ScrapeError(Exception):
    """Raised when the JSON payload is missing expected structure.

    Surfaces a changed response shape loudly instead of as an empty success
    (Global Constraint: no silent failures).
    """


def parse_date(raw: str) -> str:
    """Convert "DD/MM/YY | HH:MM" (Israel local) to a naive ISO 8601 string."""
    return datetime.strptime(raw.strip(), _DATE_FORMAT).isoformat()


def extract_tags(raw) -> tuple[str, ...]:
    """Normalize the `Tags` field into a tuple of ticker symbols.

    Defensive about shape: accepts a comma/semicolon-delimited string, or a
    list of strings, or a list of dicts carrying a `Symbol`/`symbol` key.
    Returns () for anything empty or unrecognized.
    """
    if not raw:
        return ()
    if isinstance(raw, str):
        parts = re.split(r"[,;]", raw)
    elif isinstance(raw, list):
        parts = [
            part if isinstance(part, str)
            else str(part.get("Symbol") or part.get("symbol") or "")
            for part in raw
        ]
    else:
        return ()
    return tuple(p.strip() for p in parts if p and p.strip())


def parse_posts(payload: dict, user_id: int = HADAR_USER_ID) -> list[Post]:
    """Turn a raw stream payload into Hadar's Post objects. Pure — no network.

    Filters to items whose User.UserId == user_id, resolves each reply's root
    subject via the L1 thread group (root = the Level==1 sibling, which may be
    any user), and extracts tickers and the attached image file name.
    """
    if "Data" not in payload:
        raise ScrapeError("response payload missing 'Data' key — shape changed")

    data = payload["Data"]

    # Root subjects across ALL users, keyed by thread group (L1).
    root_subjects: dict[str, str] = {}
    for item in data:
        if item.get("Level") == 1:
            root_subjects[str(item.get("L1"))] = item.get("subject") or ""

    posts: list[Post] = []
    for item in data:
        user = item.get("User") or {}
        if user.get("UserId") != user_id:
            continue

        level = int(item.get("Level"))
        thread_group = str(item.get("L1"))
        root_subject = root_subjects.get(thread_group) if level > 1 else None

        has_image = bool(item.get("HasImages")) and bool(item.get("MsgFileName"))
        image_file_name = item.get("MsgFileName") if has_image else None

        posts.append(
            Post(
                msg_id=str(item.get("MsgId")),
                posted_at=parse_date(item.get("DateCreated")),
                level=level,
                thread_group=thread_group,
                subject=item.get("subject") or "",
                body=item.get("Msg") or "",
                tags=extract_tags(item.get("Tags")),
                root_subject=root_subject,
                image_file_name=image_file_name,
                image_local_path=None,
            )
        )

    return posts
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_parse.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/scraper/__init__.py hadar_tracker/scraper/parse.py tests/fixtures/sample_stream.json tests/test_parse.py
git commit -m "feat: add pure JSON parser with filtering and thread resolution"
```

---

## Task 4: Thin HTTP client (`scraper/client.py`)

**Files:**
- Create: `hadar_tracker/scraper/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `requests`, `hadar_tracker.scraper.parse` (`parse_posts`, `ScrapeError`, `HADAR_USER_ID`), `hadar_tracker.models.Post`.
- Produces:
  - `hadar_tracker.scraper.client.ENDPOINT: str`, `hadar_tracker.scraper.client.USER_AGENT: str`
  - `hadar_tracker.scraper.client.fetch_raw(user_id: int = HADAR_USER_ID, forum_id: int = 1, timeout: int = 30) -> dict` — POSTs the form body, raises for HTTP errors, returns parsed JSON.
  - `hadar_tracker.scraper.client.fetch_posts(user_id: int = HADAR_USER_ID, forum_id: int = 1, timeout: int = 30) -> list[Post]` — calls `fetch_raw` then `parse_posts`; raises `ScrapeError` if the parsed list is empty (posts were expected).
  - Re-exports `ScrapeError` (imported from `parse`) for callers.

**Note:** unit tests monkeypatch `client.requests`, so no live network is touched. `fetch_raw` is the only function that talks to the site.

- [ ] **Step 1: Write the failing tests**

`tests/test_client.py`:

```python
import json
import pathlib

import pytest

from hadar_tracker.scraper import client
from hadar_tracker.scraper.parse import ScrapeError

PAYLOAD = json.loads(
    pathlib.Path("tests/fixtures/sample_stream.json").read_text(encoding="utf-8")
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return self.response


def test_fetch_raw_posts_expected_form_body(monkeypatch):
    fake = FakeRequests(FakeResponse(PAYLOAD))
    monkeypatch.setattr(client, "requests", fake)
    result = client.fetch_raw(user_id=5609, forum_id=1)
    assert result == PAYLOAD
    call = fake.calls[0]
    assert call["url"] == client.ENDPOINT
    assert call["data"] == {"ForumId": 1, "IsFull": 1, "UserId": 5609, "m": 0}
    assert "User-Agent" in call["headers"]


def test_fetch_raw_raises_on_http_error(monkeypatch):
    fake = FakeRequests(FakeResponse({}, status=403))
    monkeypatch.setattr(client, "requests", fake)
    with pytest.raises(RuntimeError):
        client.fetch_raw()


def test_fetch_posts_returns_parsed_posts(monkeypatch):
    fake = FakeRequests(FakeResponse(PAYLOAD))
    monkeypatch.setattr(client, "requests", fake)
    posts = client.fetch_posts()
    assert [p.msg_id for p in posts] == ["5001", "5002", "5004"]


def test_fetch_posts_raises_when_no_posts(monkeypatch):
    fake = FakeRequests(FakeResponse({"Data": []}))
    monkeypatch.setattr(client, "requests", fake)
    with pytest.raises(ScrapeError):
        client.fetch_posts()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.scraper.client'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/scraper/client.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Live smoke test (manual, not committed)**

Confirm the real endpoint works and the fixture shape matches reality:

```bash
python -c "from hadar_tracker.scraper.client import fetch_posts; ps = fetch_posts(); print(len(ps), 'posts'); p = ps[0]; print(p.posted_at, p.subject, p.tags, p.body[:50])"
```

Expected: prints a non-zero post count and the newest post's fields. If `Tags` comes back in a shape `extract_tags` does not handle, or a field name differs, update `parse.py` / the fixture together, re-run `pytest tests/test_parse.py tests/test_client.py`, and re-commit.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/scraper/client.py tests/test_client.py
git commit -m "feat: add thin HTTP client for the stream endpoint"
```

---

## Task 5: Attachment image download (`images.py`)

**Files:**
- Create: `hadar_tracker/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Consumes: `requests`.
- Produces:
  - `hadar_tracker.images.IMAGE_BASE: str` (= `"https://www.sponser.co.il/ForumFiles/"`)
  - `hadar_tracker.images.download_image(msg_file_name: str, images_dir: str, timeout: int = 30) -> str` — creates `images_dir` if needed, GETs `IMAGE_BASE + msg_file_name`, writes the bytes to `images_dir/msg_file_name`, returns the local path. Raises for HTTP errors.

- [ ] **Step 1: Write the failing tests**

`tests/test_images.py`:

```python
import pytest

from hadar_tracker import images


class FakeResponse:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.response


def test_download_image_writes_file_and_returns_path(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"\x89PNG\r\nfake"))
    monkeypatch.setattr(images, "requests", fake)
    dest = images.download_image("abc123.gif", str(tmp_path / "imgs"))
    assert dest.endswith("abc123.gif")
    with open(dest, "rb") as handle:
        assert handle.read() == b"\x89PNG\r\nfake"
    assert fake.calls[0]["url"] == images.IMAGE_BASE + "abc123.gif"


def test_download_image_raises_on_http_error(tmp_path, monkeypatch):
    fake = FakeRequests(FakeResponse(b"", status=404))
    monkeypatch.setattr(images, "requests", fake)
    with pytest.raises(RuntimeError):
        images.download_image("missing.gif", str(tmp_path / "imgs"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_images.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.images'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/images.py`:

```python
from __future__ import annotations

import os

import requests

IMAGE_BASE = "https://www.sponser.co.il/ForumFiles/"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def download_image(msg_file_name: str, images_dir: str, timeout: int = 30) -> str:
    """Download an attached picture to images_dir and return its local path.

    Plain HTTP GET of https://www.sponser.co.il/ForumFiles/{msg_file_name}.
    Raises for HTTP errors so a missing/blocked file surfaces loudly.
    """
    os.makedirs(images_dir, exist_ok=True)
    response = requests.get(
        IMAGE_BASE + msg_file_name,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    dest = os.path.join(images_dir, msg_file_name)
    with open(dest, "wb") as handle:
        handle.write(response.content)
    return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_images.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/images.py tests/test_images.py
git commit -m "feat: add attachment image downloader"
```

---

## Task 6: Telegram notifier (`notifier.py`)

**Files:**
- Create: `hadar_tracker/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `telegram.Bot` (from python-telegram-bot).
- Produces:
  - `hadar_tracker.notifier.format_message(subject: str, tags: Sequence[str], body: str, root_subject: str | None = None) -> str` — pure formatter: subject line, `🏷 ...` tags line (when tags), `↩️ Replying to: ...` line (when root_subject), blank line, body.
  - `hadar_tracker.notifier.send_post(bot_token: str, chat_id: str, subject: str, tags: Sequence[str], body: str, root_subject: str | None = None, image_path: str | None = None) -> None` — sends one message; photo+caption when `image_path` is set, else a text message.
  - `hadar_tracker.notifier.send_alert(bot_token: str, chat_id: str, message: str) -> None` — prefixed failure alert.

**Design note:** python-telegram-bot v21 is async; `notifier` exposes synchronous wrappers (`asyncio.run(...)`) so `check.py` stays a simple sync script. Telegram photo captions cap at 1024 chars, so a photo caption is truncated to 1024; text-only messages use the full formatted text (the 4096 message limit is far above typical post length).

- [ ] **Step 1: Write the failing tests**

`tests/test_notifier.py`:

```python
import hadar_tracker.notifier as notifier


class FakeBot:
    """Records calls; supports `async with bot` like telegram.Bot."""

    last: dict = {}

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


def test_format_message_root_post_with_tags():
    out = notifier.format_message("טבע", ("TEVA", "ICL"), "קונה טבע")
    assert out == "טבע\n🏷 TEVA, ICL\n\nקונה טבע"


def test_format_message_reply_has_context_line():
    out = notifier.format_message("", (), "מוסיף", root_subject="תל אביב 35")
    assert out == "↩️ Replying to: תל אביב 35\n\nמוסיף"


def test_format_message_body_only():
    assert notifier.format_message("", (), "just body") == "just body"


def test_send_post_text_only(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "טבע", ("TEVA",), "קונה טבע")
    assert FakeBot.last["kind"] == "message"
    assert FakeBot.last["chat_id"] == "42"
    assert FakeBot.last["token"] == "tok"
    assert "🏷 TEVA" in FakeBot.last["text"]


def test_send_post_with_image(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.gif"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "טבע", (), "עם גרף", image_path=str(img))
    assert FakeBot.last["kind"] == "photo"
    assert "עם גרף" in FakeBot.last["caption"]


def test_send_post_truncates_long_caption(monkeypatch, tmp_path):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    img = tmp_path / "chart.gif"
    img.write_bytes(b"\x89PNG\r\n")
    notifier.send_post("tok", "42", "", (), "x" * 2000, image_path=str(img))
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
from typing import Sequence

from telegram import Bot

_CAPTION_LIMIT = 1024


def format_message(
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
) -> str:
    """Build the notification text for a post.

    Layout (each present part on its own line, then a blank line, then body):
        <subject>
        🏷 TEVA, ICL
        ↩️ Replying to: <root_subject>

        <body>
    Empty/omitted parts are skipped.
    """
    lines: list[str] = []
    if subject:
        lines.append(subject)
    if tags:
        lines.append("🏷 " + ", ".join(tags))
    if root_subject:
        lines.append("↩️ Replying to: " + root_subject)
    lines.append("")
    lines.append(body)
    return "\n".join(lines).strip()


def send_post(
    bot_token: str,
    chat_id: str,
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
    image_path: str | None = None,
) -> None:
    """Send one Telegram message for a post: photo+caption if image_path is
    set, otherwise a plain text message."""
    text = format_message(subject, tags, body, root_subject)
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
        await bot.send_message(chat_id=chat_id, text=f"[HadarTracker] {message}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notifier.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram notifier with tags and reply-context formatting"
```

---

## Task 7: Incremental download/insert/notify core (`check.py` — `process_new_posts`)

**Files:**
- Create: `hadar_tracker/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `hadar_tracker.models.Post`, `hadar_tracker.config.Config`, `hadar_tracker.db` (`post_exists`, `insert_post`), `hadar_tracker.images.download_image`, `hadar_tracker.notifier.send_post`, `hadar_tracker.util.now_iso`.
- Produces:
  - `hadar_tracker.check.process_new_posts(conn, config: Config, posts: list[Post], download=None, send_post=None) -> list[Post]` — inserts only unseen posts, downloads any attachment, sends one notification each, returns the newly-processed posts. `download`/`send_post` are injected for testability; when left `None` they resolve to `images.download_image` / `notifier.send_post` **at call time** (so `run_check` in Task 8 can be tested by monkeypatching `notifier.send_post`).

- [ ] **Step 1: Write the failing tests**

`tests/test_check.py`:

```python
from hadar_tracker import check, db
from hadar_tracker.config import Config
from hadar_tracker.models import Post


def make_config(tmp_path):
    return Config(
        db_path=":memory:",
        images_dir=str(tmp_path / "images"),
        telegram_bot_token="tok",
        telegram_chat_id="42",
        user_id=5609,
        forum_id=1,
    )


def make_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_process_inserts_downloads_and_notifies(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    sent = []
    downloaded = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None):
        sent.append((subject, tags, body, root_subject, image_path))

    def fake_download(msg_file_name, images_dir):
        downloaded.append((msg_file_name, images_dir))
        return f"{images_dir}/{msg_file_name}"

    posts = [
        Post("1001", "t1", 1, "900", "טבע", "no image", ("TEVA",)),
        Post("1002", "t2", 2, "900", "", "has image", (), root_subject="טבע",
             image_file_name="pic.gif"),
    ]
    new = check.process_new_posts(
        conn, config, posts, download=fake_download, send_post=fake_send
    )

    assert [p.msg_id for p in new] == ["1001", "1002"]
    assert db.count_posts(conn) == 2
    # Only the second post had an attachment.
    assert downloaded == [("pic.gif", config.images_dir)]
    # The second notification carried the downloaded path and reply-context.
    assert sent[0] == ("טבע", ("TEVA",), "no image", None, None)
    assert sent[1][4] == f"{config.images_dir}/pic.gif"
    assert sent[1][3] == "טבע"
    # The image path was persisted.
    row = conn.execute("SELECT image_local_path FROM posts WHERE msg_id='1002'").fetchone()
    assert row["image_local_path"] == f"{config.images_dir}/pic.gif"


def test_process_skips_already_seen_posts(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    db.insert_post(conn, "1001", "t1", 1, "900", None, "s", "old", (), None, None, "s1")
    sent = []

    posts = [Post("1001", "t1", 1, "900", "s", "old", ())]
    new = check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: "x",
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

from hadar_tracker import db, images, notifier
from hadar_tracker.config import Config
from hadar_tracker.models import Post
from hadar_tracker.util import now_iso


def process_new_posts(
    conn,
    config: Config,
    posts: list[Post],
    download=None,
    send_post=None,
) -> list[Post]:
    """Insert unseen posts, download any attachment, and notify — one message
    each. Returns the posts newly processed.

    `download` and `send_post` are injected so this is unit-testable without a
    live network or Telegram. They resolve to the real functions at call time
    (not as def-time defaults) so callers like run_check can be tested by
    monkeypatching `notifier.send_post`.
    """
    if download is None:
        download = images.download_image
    if send_post is None:
        send_post = notifier.send_post

    new_posts: list[Post] = []
    for post in posts:
        if db.post_exists(conn, post.msg_id):
            continue

        image_local_path: str | None = None
        if post.image_file_name:
            image_local_path = download(post.image_file_name, config.images_dir)

        db.insert_post(
            conn,
            post.msg_id,
            post.posted_at,
            post.level,
            post.thread_group,
            post.root_subject,
            post.subject,
            post.body,
            post.tags,
            post.image_file_name,
            image_local_path,
            now_iso(),
        )
        send_post(
            config.telegram_bot_token,
            config.telegram_chat_id,
            post.subject,
            post.tags,
            post.body,
            post.root_subject,
            image_local_path,
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
git commit -m "feat: add incremental download/insert/notify core"
```

---

## Task 8: Check orchestration + error handling + CLI (`check.py` — `run_check`, `main`)

**Files:**
- Modify: `hadar_tracker/check.py` (append `run_check` and `main`)
- Test: `tests/test_check.py` (add cases)

**Interfaces:**
- Consumes: `hadar_tracker.config.load_config`/`Config`, `hadar_tracker.db` (`connect`, `init_db`), `hadar_tracker.scraper.client.fetch_posts`, `hadar_tracker.scraper.parse.ScrapeError`, `hadar_tracker.notifier.send_alert`, and `process_new_posts` from Task 7.
- Produces:
  - `hadar_tracker.check.run_check(config: Config | None = None) -> int` — full incremental run; returns `0` on success, `1` on scrape failure (after logging + sending a Telegram alert). No silent failures.
  - `hadar_tracker.check.main() -> None` — CLI entry: `sys.exit(run_check())`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_check.py`)**

```python
from hadar_tracker.scraper import client, parse


def test_run_check_success_path(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    fetched = [Post("2001", "t", 1, "900", "טבע", "brand new post", ("TEVA",))]
    monkeypatch.setattr(client, "fetch_posts", lambda **k: fetched)
    sent = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_post",
        lambda token, chat_id, subject, tags, body, root_subject=None, image_path=None: sent.append(body),
    )
    rc = check.run_check(config)
    assert rc == 0
    assert sent == ["brand new post"]


def test_run_check_reports_failure_and_alerts(tmp_path, monkeypatch):
    config = make_config(tmp_path)

    def boom(**k):
        raise parse.ScrapeError("shape changed")

    monkeypatch.setattr(client, "fetch_posts", boom)
    alerts = []
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_alert",
        lambda token, chat_id, message: alerts.append(message),
    )
    rc = check.run_check(config)
    assert rc == 1
    assert len(alerts) == 1
    assert "shape changed" in alerts[0]
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
from hadar_tracker.scraper import client
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
        posts = client.fetch_posts(user_id=config.user_id, forum_id=config.forum_id)
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
Expected: PASS — all tests from Tasks 1–8.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/check.py tests/test_check.py
git commit -m "feat: add check orchestration, error handling, and CLI entry"
```

---

## Task 9: Backfill stub (`backfill.py`)

The historical-backfill mechanism is an **unresolved open item** (spec §"Open items": the live endpoint covers only ~1 day; the way to reach the multi-year archive is not yet discovered). This plan ships an **honest, invocable stub** rather than a fake implementation: `main()` logs that the mechanism is undetermined and exits with a distinct non-zero code (`2`), so the deploy docs and any future systemd unit have a real entry point to reference that fails informatively instead of a missing module. See Notes for why a stub was chosen over silently dropping the file.

**Files:**
- Create: `hadar_tracker/backfill.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: nothing (stdlib `logging`, `sys`).
- Produces:
  - `hadar_tracker.backfill.NOT_IMPLEMENTED_EXIT_CODE: int` (= `2`)
  - `hadar_tracker.backfill.run_backfill() -> int` — logs the "mechanism undetermined" message; returns `NOT_IMPLEMENTED_EXIT_CODE`.
  - `hadar_tracker.backfill.main() -> None` — CLI entry: `sys.exit(run_backfill())`.

- [ ] **Step 1: Write the failing test**

`tests/test_backfill.py`:

```python
import logging

from hadar_tracker import backfill


def test_run_backfill_returns_not_implemented_code():
    assert backfill.run_backfill() == backfill.NOT_IMPLEMENTED_EXIT_CODE
    assert backfill.NOT_IMPLEMENTED_EXIT_CODE == 2


def test_run_backfill_logs_undetermined_message(caplog):
    with caplog.at_level(logging.WARNING):
        backfill.run_backfill()
    assert any("mechanism" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hadar_tracker.backfill'`.

- [ ] **Step 3: Write the implementation**

`hadar_tracker/backfill.py`:

```python
from __future__ import annotations

import logging
import sys

# Distinct from success (0) and the check job's runtime-error code (1): the
# backfill mechanism is simply not built yet.
NOT_IMPLEMENTED_EXIT_CODE = 2

_MESSAGE = (
    "Historical backfill is not implemented: the discovery mechanism is "
    "undetermined. The live stream endpoint "
    "(HD_STREAM_FORUM_USER_MESSAGES.ashx) only covers ~1 day of activity, not "
    "Hadar's full archive. A follow-up investigation is required (does the `m` "
    "parameter accept a cursor/offset? is there a separate paginated per-user "
    "history endpoint?) before this can be built. Not required for Phase 1 "
    "launch; required before Phase 2. See "
    "docs/superpowers/specs/2026-07-21-phase1-tracker-design.md, 'Open items'."
)


def run_backfill() -> int:
    """Report that backfill is undetermined and exit informatively.

    Deliberately does NOT touch the network or the database — there is no
    mechanism to implement yet, and pretending otherwise would be a silent
    no-op. Returns NOT_IMPLEMENTED_EXIT_CODE.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("hadar_tracker.backfill").warning(_MESSAGE)
    return NOT_IMPLEMENTED_EXIT_CODE


def main() -> None:
    sys.exit(run_backfill())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backfill.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add hadar_tracker/backfill.py tests/test_backfill.py
git commit -m "feat: add honest backfill stub for the undetermined history mechanism"
```

---

## Task 10: Deployment to Oracle VPS (systemd/cron + docs)

Simpler than the original plan: no Playwright, no `playwright install --with-deps chromium`. Dependencies are just `requests`, `python-telegram-bot`, and `pytest`.

**Files:**
- Create: `deploy/run_check.sh`
- Create: `deploy/hadar-tracker.service`
- Create: `deploy/hadar-tracker.timer`
- Create: `deploy/README.md`

**Interfaces:**
- Consumes: `python -m hadar_tracker.check` (Task 8 `main`), `.env` (variables from Task 1's `.env.example`).
- Produces: shell wrapper + systemd units + install docs. No Python interfaces.

- [ ] **Step 1: Write the wrapper script**

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

- [ ] **Step 2: Verify the script is valid bash**

Run: `bash -n deploy/run_check.sh && echo OK`
Expected: prints `OK` (no syntax errors).

- [ ] **Step 3: Write the systemd units**

`deploy/hadar-tracker.service`:

```ini
[Unit]
Description=HadarTracker incremental check (fetch -> store -> notify)
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

Phase 1 is a plain-HTTP JSON client — **no browser, no Chromium**. Build and
test locally first (`python -m pytest` must be green). Then, on the VPS:

## 1. Clone and set up

```bash
cd ~
git clone <repo-url> HadarTracker
cd HadarTracker
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

That is the whole install — `requests`, `python-telegram-bot`, and `pytest`.
There is no `playwright install` step (the old browser-based design was
dropped after the site's JSON endpoint proved reachable with plain HTTP).

## 2. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
chmod 600 .env
```

Get a bot token from @BotFather; get your chat id by messaging the bot and
reading `https://api.telegram.org/bot<TOKEN>/getUpdates`.

## 3. Make the wrapper executable and smoke-test

```bash
chmod +x deploy/run_check.sh
./deploy/run_check.sh
```

Expected: exit code 0, a log line `check complete: N new post(s)`, and — on the
first run against the live feed — Telegram messages for the recent posts
(subject, 🏷 tickers, ↩️ reply-context where applicable, body, and the attached
picture when one is present).

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

Add (every 10 minutes; adjust to 15 once cadence is known):

```
*/10 * * * * /home/ubuntu/HadarTracker/deploy/run_check.sh >> /home/ubuntu/HadarTracker/data/check.log 2>&1
```

`check.py` exits non-zero and sends a Telegram alert on failure, so both the
log file / `journalctl` and Telegram surface problems — no silent misses.

## 5. Historical backfill — NOT available yet

`python -m hadar_tracker.backfill` is currently a **stub**: it logs that the
history-crawl mechanism is undetermined and exits with code 2. The live
endpoint only covers ~1 day of activity; reaching Hadar's full archive needs a
follow-up investigation (see the design spec's "Open items"). Backfill is not
required for Phase 1 launch — only before Phase 2 analysis.

## 6. Tuning

Once real posting cadence is known, adjust the interval (`OnUnitActiveSec` in
the timer, or the cron `*/N`) toward the 10–15 min target.
````

- [ ] **Step 5: Commit**

```bash
git add deploy/run_check.sh deploy/hadar-tracker.service deploy/hadar-tracker.timer deploy/README.md
git commit -m "feat: add VPS deployment wrapper, systemd units, and docs"
```

---

## Final verification

- [ ] **Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS — all tests across Tasks 1–9 (models, config, db, parse, client, images, notifier, check, backfill).

- [ ] **Confirm the entry points import and expose `main`**

Run: `python -c "import hadar_tracker.check as c, hadar_tracker.backfill as b; assert callable(c.main) and callable(b.main); print('entry points OK')"`
Expected: prints `entry points OK`.

---

## Self-review

**1. Spec coverage** (each spec requirement → task):

| Spec requirement | Task |
|---|---|
| Plain-HTTP JSON client, no browser/Playwright/HTML parsing | Global Constraints; Tasks 3–4 (parse + client); Task 1 (deps dropped) |
| POST `HD_STREAM_..ashx` with `ForumId=1&IsFull=1&UserId=5609&m=0`, desktop UA | Task 4 (`fetch_raw`) |
| Filter to `User.UserId == 5609` | Task 3 (`parse_posts`) |
| Extract `MsgId`, `DateCreated`, `Level`, `L1`, `subject`, `Msg`, `Tags`, `HasImages`, `MsgFileName` | Task 3 |
| Resolve reply→root subject via `L1` + `Level==1` (root may be any user) | Task 3 (`root_subjects` built across all users) |
| `posts` table with the 11 spec columns, dedup by `msg_id` | Task 2 |
| Idempotent insert-or-ignore returning was-new | Task 2 (`insert_post`) |
| Download attached picture from `ForumFiles/{MsgFileName}` | Task 5 |
| Do NOT fetch ticker hover-popover chart; store symbols only | Task 3 stores `tags`; no code fetches that chart (Non-goal honored) |
| Telegram message: subject, tags line, reply-context line, body, attached photo | Task 6 (`format_message` + `send_post`) |
| Tickers surfaced visibly in the message | Task 6 (`🏷 ...` line) |
| Attached picture shown as a photo | Tasks 5 + 6 + 7 |
| `check.py` diff → insert → download → notify | Tasks 7–8 |
| No silent failures: non-zero exit + log + Telegram alert; empty-where-expected is failure | Task 8 (`run_check`); Task 4 (`fetch_posts` raises on empty) |
| Missing/changed response shape surfaces as failure | Task 3 (`parse_posts` raises on missing `Data`), Task 4 |
| Unit tests against fixtures, no live network | Tasks 3–9 (fixture + monkeypatched HTTP/Bot) |
| Manual smoke test before deploy | Task 4 Step 5 |
| Backfill mechanism is an open item — not silently dropped | Task 9 (honest stub) + Notes |
| Runs on Oracle VPS, systemd/cron, no Chromium | Task 10 |
| Keep `now_iso`, `Config`/`load_config` (adapted) from Task 1 | Task 1 (util untouched; config adapted with justification) |

No gaps found.

**2. Placeholder scan:** No `TBD`/`TODO`/"handle edge cases"/"similar to Task N" placeholders. Every code step contains complete, runnable code. The only "not implemented" is Task 9, which is a *deliberate, tested* stub per the spec's open-item, not a placeholder.

**3. Type/signature consistency (checked across tasks):**
- `Post` field names/order (Task 1) match every constructor call in Tasks 3, 7, 8 and every attribute read in Tasks 7–8. ✓
- `Config` fields (Task 1: `db_path`, `images_dir`, `telegram_bot_token`, `telegram_chat_id`, `user_id`, `forum_id`) match `make_config` in Tasks 7–8 and reads in Tasks 8, 10. ✓
- `db.insert_post(conn, msg_id, posted_at, level, thread_group, root_subject, subject, body, tags, image_file_name, image_local_path, scraped_at)` (Task 2) — argument order matches the call in Task 7 and the test calls in Tasks 2, 7. ✓
- `ScrapeError` defined once in `parse.py` (Task 3), imported/re-exported by `client.py` (Task 4) and referenced in Task 8 as `parse.ScrapeError`. ✓
- `parse_posts(payload, user_id=...)` (Task 3) called by `client.fetch_posts` with `user_id=` (Task 4). ✓
- `download_image(msg_file_name, images_dir, timeout=30)` (Task 5) — the injected `download(post.image_file_name, config.images_dir)` in Task 7 matches (positional `msg_file_name`, `images_dir`). ✓
- `notifier.send_post(bot_token, chat_id, subject, tags, body, root_subject=None, image_path=None)` (Task 6) — Task 7's real call passes those seven positionally in order, and the test fakes use the same signature. ✓
- `client.fetch_posts(user_id=, forum_id=)` (Task 4) — Task 8 calls it with those kwargs and the test fakes accept `**k`. ✓

No inconsistencies found.

---

## Notes on judgment calls (decisions this plan makes on the spec's behalf)

A downstream engineer should treat these as the plan's decisions, not the spec's:

1. **`Post` and `Config` are replaced in place** (edited, not duplicated). Keeping a second parallel dataclass would leave dead browser-era fields around and invite confusion. `util.now_iso` is genuinely unchanged and left untouched, per the task's instruction.
2. **`Config` gains `user_id`/`forum_id` and drops `forum_url`/`charts_dir`/`headless`.** `headless` is meaningless without a browser; `charts_dir` becomes `images_dir` (the spec renamed the concept from "charts" to downloaded attached pictures). `user_id`/`forum_id` are added because they parameterize the one request the app makes; defaults (5609/1) preserve the fixed spec values. `DEFAULT_FORUM_URL` is retained (unused by app code) so the already-committed Task-2 inspection script still imports.
3. **`db.insert_post` owns tag serialization** (accepts a `Sequence[str]`, JSON-encodes internally). One source of truth for the storage format; callers pass `post.tags` directly. The column stays a plain opaque `TEXT` from SQLite's point of view.
4. **`posted_at` is stored as a *naive* local ISO string** (no timezone offset), parsed from `DD/MM/YY | HH:MM`. Israel local time is what the site reports; attaching a real tz would drag in `zoneinfo`/`tzdata` (a Windows/VPS packaging wrinkle) for no Phase-1 benefit. If Phase 2 needs absolute UTC ordering, convert then. Documented in `parse.py`.
5. **`extract_tags` is shape-defensive** (handles a delimited string OR a list of strings/dicts). The exact JSON shape of `Tags` was not captured verbatim in the spec; the smoke test in Task 4 Step 5 is the reconciliation point — if reality differs, `parse.py` + the fixture are updated together (localized change).
6. **`scraper/` is split into `parse.py` (pure) + `client.py` (thin HTTP)** so parsing is unit-testable with zero network, satisfying the spec's fixture-based testing requirement, mirroring the original plan's parser/engine separation.
7. **`fetch_posts` treats an empty parsed result as a `ScrapeError`.** The endpoint covers ~1 day of activity, so a well-formed but *empty* Hadar result is abnormal (block or shape change), which the spec says must surface as a failure, not an empty success.
8. **Telegram photo caption truncated to 1024 chars** (Telegram's hard limit); the full body is still stored in SQLite, so no data is lost — only a rare long charted post's caption is clipped.
9. **Backfill is an honest, invocable stub (Task 9), not a dropped file.** Rationale: the deploy docs and any future scheduler need a real module/entry point to point at, and an operator who runs it deserves a clear, logged "not built yet, here's why" with a distinct exit code (`2`) rather than a `ModuleNotFoundError` or — worse — a silent success. It touches neither network nor DB, so it cannot masquerade as real work. When the follow-up investigation finds the mechanism, this file becomes the natural home for the real implementation (a new plan/task), with its own idempotent upsert-by-`msg_id` contract.
10. **Deployment dropped the Chromium install** entirely and uses a single `run_check.sh` wrapper (no `run_backfill.sh`, since backfill is a stub). The systemd timer/units are otherwise carried over from the original plan.

---

## Execution handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration (REQUIRED SUB-SKILL: superpowers:subagent-driven-development).
2. **Inline Execution** — execute tasks in this session with checkpoints (REQUIRED SUB-SKILL: superpowers:executing-plans).
