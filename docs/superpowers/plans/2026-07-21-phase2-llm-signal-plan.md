# Phase 2 LLM Trade-Signal Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an OpenRouter-based classification step to the live `check.py` pipeline that reads each new post (plus its in-payload thread transcript and any attached chart image) and returns a structured trade signal, appended to the Telegram notification and stored alongside the post.

**Architecture:** Extend `parse_posts` to capture each post's full in-payload thread transcript (already-fetched data, no new network calls). A new `hadar_tracker/signal.py` module calls OpenRouter (plain `requests`, matching this repo's no-SDK HTTP style) and returns a `Signal` or `None`, never raising. `check.py` calls it between the existing image-download and Telegram-send steps; the result flows into both the Telegram message (`notifier.py`) and the DB (`db.py`).

**Tech Stack:** Python 3, `requests` (already a dependency — no new packages needed), `pytest`, SQLite.

## Global Constraints

- No browser, no new HTTP client library — plain `requests`, same as every other network call in this repo (`scraper/client.py`, `scraper/history.py`, `images.py`).
- Every network/Telegram boundary is monkeypatched in tests, never hit live — same discipline as the rest of the test suite (see `tests/test_client.py`'s `FakeRequests`/`FakeResponse` pattern; reuse that shape, don't invent a new one).
- Classification is fail-open: `classify_post` must never raise. Any failure (no API key, HTTP error, malformed response) returns `None`, and the pipeline proceeds exactly as it did in Phase 1.
- `Post`, `Config`, and `db.insert_post` all gain new fields/params with defaults, appended at the end of their existing signatures — every existing call site (tests, `backfill.py`) must keep working unmodified unless this plan explicitly says otherwise.
- Existing tests are the source of truth for current behavior — read the file before editing it, and only change what a task requires.

---

### Task 1: `models.py` — `ThreadItem`, `Signal`, `Post.thread_transcript`

**Files:**
- Modify: `hadar_tracker/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `ThreadItem(author: str, level: int, subject: str, body: str, posted_at: str)` — frozen dataclass.
- Produces: `Signal(is_signal: bool, ticker_mentioned: str | None, ticker_guess: str | None, action: str, conviction: str, price_levels: str | None, rationale: str)` — frozen dataclass.
- Produces: `Post.thread_transcript: tuple[ThreadItem, ...] = ()` — new field, defaults to empty tuple, appended after `image_local_path` (last existing field) so no existing positional `Post(...)` construction anywhere in the codebase breaks.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py` (keep the existing `from hadar_tracker.models import Post` import and the two existing tests untouched; change the import line and append these tests):

```python
from hadar_tracker.models import Post, Signal, ThreadItem


def test_post_thread_transcript_defaults_to_empty_tuple():
    p = Post(
        msg_id="1", posted_at="t", level=2, thread_group="900",
        subject="", body="b", tags=(),
    )
    assert p.thread_transcript == ()


def test_post_thread_transcript_holds_thread_items():
    item = ThreadItem(
        author="other", level=1, subject="root subj", body="root body",
        posted_at="2026-07-21T10:00:00",
    )
    p = Post(
        msg_id="1", posted_at="2026-07-21T10:05:00", level=2, thread_group="900",
        subject="s", body="b", tags=(), thread_transcript=(item,),
    )
    assert p.thread_transcript == (item,)


def test_signal_holds_all_fields_and_is_frozen():
    import dataclasses

    s = Signal(
        is_signal=True,
        ticker_mentioned="Aerodrome",
        ticker_guess="ARDM",
        action="add",
        conviction="medium",
        price_levels="close above 460",
        rationale="expects breakout",
    )
    assert s.action == "add"
    assert s.ticker_guess == "ARDM"
    try:
        s.action = "sell"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Signal should be frozen")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'Signal' from 'hadar_tracker.models'` (and `ThreadItem`).

- [ ] **Step 3: Implement**

Replace the full contents of `hadar_tracker/models.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_models.py -v`
Expected: PASS (5 tests: the 2 existing plus the 3 new ones)

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All currently-passing tests still PASS (this change is purely additive).

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/models.py tests/test_models.py
git commit -m "feat: add ThreadItem and Signal models, Post.thread_transcript field"
```

---

### Task 2: `scraper/parse.py` — build `thread_transcript` in `parse_posts`

**Files:**
- Modify: `hadar_tracker/scraper/parse.py`
- Test: `tests/test_parse.py`

**Interfaces:**
- Consumes: `Post`, `ThreadItem` from `hadar_tracker.models` (Task 1).
- Produces: `parse_posts` now fills `Post.thread_transcript` for every returned post. No signature change — same `parse_posts(payload: dict, user_id: int = HADAR_USER_ID) -> list[Post]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parse.py` (existing imports/tests unchanged):

```python
def test_parse_reply_thread_transcript_includes_prior_items_up_to_itself():
    posts = parse_posts(PAYLOAD)
    reply = next(p for p in posts if p.msg_id == "5002")
    # L1=900 in the fixture: 5001 (10:32, hadar, root), 5002 (11:00, hadar),
    # 5003 (11:05, user 9999). 5002's transcript should include itself and
    # the earlier root, but NOT 5003, which comes after it.
    assert [ti.posted_at for ti in reply.thread_transcript] == [
        "2026-07-21T10:32:00", "2026-07-21T11:00:00",
    ]
    assert reply.thread_transcript[0].author == "hadar"
    assert reply.thread_transcript[0].subject == "תל אביב 35"
    assert reply.thread_transcript[1].body == "מוסיף פוזיציה, גרף מצורף"


def test_parse_reply_thread_transcript_includes_other_users_root():
    posts = parse_posts(PAYLOAD)
    reply = next(p for p in posts if p.msg_id == "5006")
    # L1=902's root (5005) is authored by a different user (8888) — proves
    # the transcript captures cross-user thread items, not just Hadar's own,
    # mirroring the existing root_subject cross-user invariant above.
    assert len(reply.thread_transcript) == 2
    root_item, own_item = reply.thread_transcript
    assert root_item.author == "other"
    assert root_item.subject == "פועלים"
    assert root_item.body == "מה דעתכם על הבנק"
    assert own_item.author == "hadar"
    assert own_item.body == "מסכים עם הניתוח, נראה חיובי"


def test_parse_root_post_thread_transcript_is_just_itself():
    posts = parse_posts(PAYLOAD)
    root = posts[0]  # msg_id 5001, L1=900, the thread's own root
    assert len(root.thread_transcript) == 1
    assert root.thread_transcript[0].author == "hadar"
    assert root.thread_transcript[0].subject == "תל אביב 35"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_parse.py -v`
Expected: FAIL — `AttributeError`/`AssertionError` since `thread_transcript` is currently always `()`.

- [ ] **Step 3: Implement**

Replace `hadar_tracker/scraper/parse.py`'s imports and `parse_posts` function:

```python
from __future__ import annotations

import re
from datetime import datetime

from hadar_tracker.models import Post, ThreadItem
```

(keep `HADAR_USER_ID`, `ScrapeError`, `parse_date`, `extract_tags` exactly as they are today — only `parse_posts` changes)

```python
def parse_posts(payload: dict, user_id: int = HADAR_USER_ID) -> list[Post]:
    """Turn a raw stream payload into Hadar's Post objects. Pure — no network.

    Filters to items whose User.UserId == user_id, resolves each reply's root
    subject via the L1 thread group (root = the Level==1 sibling, which may be
    any user), extracts tickers and the attached image file name, and builds
    each post's thread_transcript: every item sharing its L1 thread group
    (any user, any level) already present in this same payload with
    posted_at <= this post's own posted_at, in original payload order. This
    is "the conversation so far" as Hadar would have seen it when he
    posted — built entirely from data already in the payload, no extra
    network calls (see the Phase 2 design spec's data-flow investigation).
    """
    if "Data" not in payload:
        raise ScrapeError("response payload missing 'Data' key — shape changed")

    data = payload["Data"]

    # Root subjects across ALL users, keyed by thread group (L1).
    root_subjects: dict[str, str] = {}
    for item in data:
        if item.get("Level") == 1:
            root_subjects[str(item.get("L1"))] = item.get("subject") or ""

    # Every item (any user), grouped by thread group, in original payload
    # order — used to build each Hadar post's thread_transcript below.
    # posted_at is a naive ISO 8601 string, so plain string comparison
    # ("<=") already gives correct chronological filtering.
    threads: dict[str, list[ThreadItem]] = {}
    for item in data:
        thread_group = str(item.get("L1"))
        user = item.get("User") or {}
        author = "hadar" if user.get("UserId") == user_id else "other"
        threads.setdefault(thread_group, []).append(
            ThreadItem(
                author=author,
                level=int(item.get("Level")),
                subject=item.get("subject") or "",
                body=item.get("Msg") or "",
                posted_at=parse_date(item.get("DateCreated")),
            )
        )

    posts: list[Post] = []
    for item in data:
        user = item.get("User") or {}
        if user.get("UserId") != user_id:
            continue

        level = int(item.get("Level"))
        thread_group = str(item.get("L1"))
        root_subject = root_subjects.get(thread_group) if level > 1 else None
        posted_at = parse_date(item.get("DateCreated"))

        thread_transcript = tuple(
            ti for ti in threads.get(thread_group, ()) if ti.posted_at <= posted_at
        )

        has_image = bool(item.get("HasImages")) and bool(item.get("MsgFileName"))
        image_file_name = item.get("MsgFileName") if has_image else None

        posts.append(
            Post(
                msg_id=str(item.get("MsgId")),
                posted_at=posted_at,
                level=level,
                thread_group=thread_group,
                subject=item.get("subject") or "",
                body=item.get("Msg") or "",
                tags=extract_tags(item.get("Tags")),
                root_subject=root_subject,
                image_file_name=image_file_name,
                image_local_path=None,
                thread_transcript=thread_transcript,
            )
        )

    return posts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_parse.py -v`
Expected: PASS (all existing `test_parse_*` tests plus the 3 new ones — the existing ones must be untouched by this change; if any existing assertion fails, the refactor broke something and needs fixing before moving on).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All PASS. In particular `tests/test_client.py`, `tests/test_history.py`, `tests/test_backfill.py`, and `tests/test_check.py::test_run_check_end_to_end_through_real_parser` all call `parse_posts` transitively — they must be unaffected since `thread_transcript` is additive.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/scraper/parse.py tests/test_parse.py
git commit -m "feat: build thread_transcript in parse_posts from already-fetched payload"
```

---

### Task 3: `db.py` — `signal_json` column, migration, `insert_post` param

**Files:**
- Modify: `hadar_tracker/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `insert_post(..., signal_json: str | None = None) -> bool` — new last parameter, default `None`, fully backward compatible with all 11-positional-arg call sites (`backfill.py`, existing tests).
- Produces: `init_db(conn)` now also runs a one-time migration adding `signal_json` to a `posts` table created before this column existed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_insert_stores_signal_json():
    conn = make_conn()
    db.insert_post(
        conn, "p3", "t", 1, "900", None, "s", "body", (), None, None, "s1",
        signal_json='{"is_signal": true, "action": "add"}',
    )
    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='p3'").fetchone()
    assert row["signal_json"] == '{"is_signal": true, "action": "add"}'


def test_insert_signal_json_defaults_to_none():
    conn = make_conn()
    db.insert_post(conn, "p4", "t", 1, "900", None, "s", "body", (), None, None, "s1")
    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='p4'").fetchone()
    assert row["signal_json"] is None


def test_init_db_migrates_table_created_before_signal_json_existed():
    conn = db.connect(":memory:")
    # Simulate a pre-Phase-2 database: the exact CREATE TABLE Phase 1 shipped,
    # with no signal_json column.
    conn.executescript(
        """
        CREATE TABLE posts (
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
    )
    conn.commit()
    columns_before = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    assert "signal_json" not in columns_before

    db.init_db(conn)  # must not raise, and must add the missing column

    columns_after = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    assert "signal_json" in columns_after
    assert db.insert_post(conn, "p5", "t", 1, "900", None, "s", "b", (), None, None, "s1") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_db.py -v`
Expected: FAIL — `sqlite3.OperationalError: table posts has no column named signal_json` (or `TypeError: insert_post() got an unexpected keyword argument 'signal_json'`).

- [ ] **Step 3: Implement**

In `hadar_tracker/db.py`, replace `SCHEMA`:

```python
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
    signal_json      TEXT,
    scraped_at       TEXT NOT NULL
);
"""
```

Replace `init_db` and add the migration helper right after it:

```python
def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_add_signal_json_column(conn)
    conn.commit()


def _migrate_add_signal_json_column(conn: sqlite3.Connection) -> None:
    """Add signal_json to a posts table created before Phase 2 existed.

    SCHEMA's `CREATE TABLE IF NOT EXISTS` is a no-op against an
    already-created table, so a DB file from before this column existed
    needs an explicit ALTER TABLE — this makes init_db safe against both a
    fresh DB (SCHEMA already has the column, so this is a no-op) and an
    existing one (VPS deployments already running Phase 1).
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if "signal_json" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN signal_json TEXT")
```

Replace `insert_post`'s signature and body:

```python
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
    signal_json: str | None = None,
) -> bool:
    """Insert a post, ignoring it if msg_id already exists.

    `tags` is JSON-encoded to a TEXT column here (single source of truth for
    the serialization format). `signal_json` is the caller's already-
    serialized `Signal` (see hadar_tracker.signal.classify_post) or None if
    classification didn't run/succeed. Returns True iff a new row was
    inserted — safe for both the incremental check and any idempotent
    re-run.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO posts "
        "(msg_id, posted_at, level, thread_group, root_subject, subject, "
        " body, tags, image_file_name, image_local_path, scraped_at, signal_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            signal_json,
        ),
    )
    conn.commit()
    return cur.rowcount == 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_db.py -v`
Expected: PASS (all existing tests plus the 3 new ones).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All PASS, including `tests/test_backfill.py` (its `db.insert_post` calls are all 11-positional-arg, unaffected by the new trailing default param).

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/db.py tests/test_db.py
git commit -m "feat: add signal_json column with migration for existing databases"
```

---

### Task 4: `config.py` — `openrouter_api_key`, `openrouter_model`

**Files:**
- Modify: `hadar_tracker/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.openrouter_api_key: str | None = None`, `Config.openrouter_model: str = "anthropic/claude-sonnet-4.5"` — both new trailing fields with defaults.
- Produces: `load_config` reads `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` from env, neither required (Phase 2 is additive — a deployment with no key set must keep loading successfully, per the design spec's Error handling section).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_load_config_openrouter_defaults_to_none_and_default_model():
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    config = load_config(env)
    assert config.openrouter_api_key is None
    assert config.openrouter_model == "anthropic/claude-sonnet-4.5"


def test_load_config_reads_openrouter_overrides():
    env = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "123",
        "OPENROUTER_API_KEY": "sk-or-abc",
        "OPENROUTER_MODEL": "some/other-model",
    }
    config = load_config(env)
    assert config.openrouter_api_key == "sk-or-abc"
    assert config.openrouter_model == "some/other-model"


def test_load_config_does_not_require_openrouter_api_key():
    # Phase 2 is additive: a deployment with no OpenRouter key configured
    # must still load successfully (classify_post short-circuits to None).
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}
    config = load_config(env)  # must not raise
    assert config.openrouter_api_key is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'openrouter_api_key'`.

- [ ] **Step 3: Implement**

In `hadar_tracker/config.py`, replace the `Config` dataclass and `load_config`:

```python
@dataclass(frozen=True)
class Config:
    db_path: str
    images_dir: str
    telegram_bot_token: str
    telegram_chat_id: str
    user_id: int
    forum_id: int
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-sonnet-4.5"


def load_config(env: dict[str, str] | None = None) -> Config:
    """Build a Config from environment variables.

    Raises ConfigError (loudly) if a required variable is missing, so a
    misconfigured cron run fails fast instead of silently doing nothing.
    OPENROUTER_API_KEY is intentionally NOT required — Phase 2 (LLM trade-
    signal classification) is additive; with no key set, classify_post
    short-circuits to None and the pipeline behaves exactly as Phase 1 did.
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
        openrouter_api_key=source.get("OPENROUTER_API_KEY") or None,
        openrouter_model=source.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5"),
    )
```

Update `.env.example` (append after the existing `FORUM_ID=1` line):

```
# Optional: LLM trade-signal classification (Phase 2). If OPENROUTER_API_KEY
# is unset, classification is simply skipped (signal=None) — every post
# still gets scraped, stored, and notified exactly as in Phase 1.
OPENROUTER_API_KEY=
OPENROUTER_MODEL=anthropic/claude-sonnet-4.5
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS (all existing tests plus the 3 new ones).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/config.py .env.example tests/test_config.py
git commit -m "feat: add optional OpenRouter config for Phase 2 classification"
```

---

### Task 5: `hadar_tracker/signal.py` — `classify_post` (new module)

**Files:**
- Create: `hadar_tracker/signal.py`
- Create: `tests/test_signal.py`

**Interfaces:**
- Consumes: `Post`, `Signal`, `ThreadItem` from `hadar_tracker.models` (Task 1).
- Produces: `classify_post(post: Post, image_path: str | None, api_key: str | None, model: str = DEFAULT_MODEL) -> Signal | None`. Never raises. Module-level `requests` import (monkeypatched in tests, same convention as `scraper/client.py`).
- Produces: `OPENROUTER_ENDPOINT`, `DEFAULT_MODEL` constants.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signal.py`:

```python
import json

from hadar_tracker import signal
from hadar_tracker.models import Post, Signal


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

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return self.response


def _openrouter_payload(content_dict):
    return {"choices": [{"message": {"content": json.dumps(content_dict)}}]}


def make_post(**overrides):
    fields = dict(
        msg_id="1", posted_at="2026-07-21T10:00:00", level=2, thread_group="900",
        subject="s", body="b", tags=(),
    )
    fields.update(overrides)
    return Post(**fields)


def test_classify_post_returns_none_when_no_api_key(monkeypatch):
    fake = FakeRequests(FakeResponse({}))
    monkeypatch.setattr(signal, "requests", fake)
    result = signal.classify_post(make_post(), None, api_key=None)
    assert result is None
    assert fake.calls == []


def test_classify_post_parses_well_formed_response(monkeypatch):
    fake = FakeRequests(
        FakeResponse(
            _openrouter_payload(
                {
                    "is_signal": True,
                    "ticker_mentioned": "Aerodrome",
                    "ticker_guess": "ARDM",
                    "action": "add",
                    "conviction": "medium",
                    "price_levels": "close above 460",
                    "rationale": "expects breakout",
                }
            )
        )
    )
    monkeypatch.setattr(signal, "requests", fake)

    result = signal.classify_post(make_post(), None, api_key="test-key")

    assert result == Signal(
        is_signal=True,
        ticker_mentioned="Aerodrome",
        ticker_guess="ARDM",
        action="add",
        conviction="medium",
        price_levels="close above 460",
        rationale="expects breakout",
    )
    assert fake.calls[0]["url"] == signal.OPENROUTER_ENDPOINT
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer test-key"


def test_classify_post_returns_none_on_http_error(monkeypatch):
    fake = FakeRequests(FakeResponse({}, status=500))
    monkeypatch.setattr(signal, "requests", fake)
    assert signal.classify_post(make_post(), None, api_key="k") is None


def test_classify_post_returns_none_on_malformed_json(monkeypatch):
    fake = FakeRequests(
        FakeResponse({"choices": [{"message": {"content": "not json"}}]})
    )
    monkeypatch.setattr(signal, "requests", fake)
    assert signal.classify_post(make_post(), None, api_key="k") is None


def test_classify_post_coerces_invalid_action_and_conviction_to_safe_defaults(monkeypatch):
    fake = FakeRequests(
        FakeResponse(
            _openrouter_payload({"is_signal": True, "action": "yolo", "conviction": "extreme"})
        )
    )
    monkeypatch.setattr(signal, "requests", fake)
    result = signal.classify_post(make_post(), None, api_key="k")
    assert result.action == "none"
    assert result.conviction == "low"


def test_classify_post_includes_image_content_block_when_image_path_set(monkeypatch, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    signal.classify_post(make_post(), str(img), api_key="k")

    content = fake.calls[0]["json"]["messages"][0]["content"]
    assert len(content) == 2
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_classify_post_proceeds_text_only_when_image_unreadable(monkeypatch):
    fake = FakeRequests(
        FakeResponse(_openrouter_payload({"is_signal": False, "action": "none", "conviction": "low"}))
    )
    monkeypatch.setattr(signal, "requests", fake)

    result = signal.classify_post(make_post(), "/no/such/file.png", api_key="k")

    assert result is not None
    content = fake.calls[0]["json"]["messages"][0]["content"]
    assert len(content) == 1  # text only, image block skipped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_signal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hadar_tracker.signal'`.

- [ ] **Step 3: Implement**

Create `hadar_tracker/signal.py`:

```python
from __future__ import annotations

import base64
import json
import logging
import mimetypes

import requests

from hadar_tracker.models import Post, Signal, ThreadItem

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"

_VALID_ACTIONS = {"buy", "sell", "trim", "add", "watch", "none"}
_VALID_CONVICTIONS = {"low", "medium", "high"}

log = logging.getLogger("hadar_tracker.signal")

__all__ = ["OPENROUTER_ENDPOINT", "DEFAULT_MODEL", "classify_post"]


def classify_post(
    post: Post,
    image_path: str | None,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
) -> Signal | None:
    """Classify a post into a structured trade signal via OpenRouter.

    Fail-open by design (see the Phase 2 design spec's Error handling
    section): returns None — never raises — if api_key is unset, the HTTP
    call fails, or the response can't be parsed into a Signal. A
    classification problem must never look like a notification-pipeline
    problem to the caller.
    """
    if not api_key:
        return None

    content: list[dict] = [{"type": "text", "text": _build_prompt(post)}]
    if image_path:
        try:
            content.append(_image_content_block(image_path))
        except OSError as exc:
            log.warning(
                "could not read image %s for classification: %s", image_path, exc
            )

    try:
        response = requests.post(
            OPENROUTER_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        return _to_signal(parsed)
    except Exception as exc:  # noqa: BLE001 - fail-open: never raise out of classify_post
        log.warning("post classification failed for msg_id=%s: %s", post.msg_id, exc)
        return None


def _render_transcript(transcript: tuple[ThreadItem, ...]) -> str:
    if not transcript:
        return "(no thread context available)"
    parts = []
    for item in transcript:
        speaker = "Hadar" if item.author == "hadar" else "Other user"
        subject = item.subject or "(no subject)"
        body = item.body or "(no body)"
        parts.append(f"[{speaker}] {subject}: {body}")
    return " -> ".join(parts)


def _build_prompt(post: Post) -> str:
    tags = ", ".join(post.tags) if post.tags else "(none)"
    return (
        "You are analyzing a forum post by a trader named Hadar on an "
        "Israeli stock trading forum, to determine whether it represents an "
        "actual trade action (buy/sell/trim/add/watch a specific stock) or "
        "is just commentary/noise. Company names are often informal "
        '(e.g. "Aerodrome" for ticker ARDM) — resolve them to a real ticker '
        "symbol using your own knowledge where possible.\n\n"
        f"Thread so far: {_render_transcript(post.thread_transcript)}\n\n"
        "Hadar's post being classified:\n"
        f"Subject: {post.subject or '(none)'}\n"
        f"Body: {post.body or '(none)'}\n"
        f"Tags: {tags}\n\n"
        "Respond with ONLY a JSON object with exactly these fields:\n"
        '{"is_signal": bool, "ticker_mentioned": string or null, '
        '"ticker_guess": string or null, '
        '"action": one of "buy"/"sell"/"trim"/"add"/"watch"/"none", '
        '"conviction": one of "low"/"medium"/"high", '
        '"price_levels": string or null, "rationale": short string}'
    )


def _image_content_block(image_path: str) -> dict:
    mime_type, _ = mimetypes.guess_type(image_path)
    mime_type = mime_type or "image/jpeg"
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def _to_signal(parsed: dict) -> Signal:
    action = parsed.get("action")
    if action not in _VALID_ACTIONS:
        action = "none"
    conviction = parsed.get("conviction")
    if conviction not in _VALID_CONVICTIONS:
        conviction = "low"
    return Signal(
        is_signal=bool(parsed.get("is_signal", False)),
        ticker_mentioned=parsed.get("ticker_mentioned"),
        ticker_guess=parsed.get("ticker_guess"),
        action=action,
        conviction=conviction,
        price_levels=parsed.get("price_levels"),
        rationale=str(parsed.get("rationale") or ""),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_signal.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/signal.py tests/test_signal.py
git commit -m "feat: add classify_post — OpenRouter trade-signal classification"
```

---

### Task 6: `notifier.py` — signal section in `format_message`/`send_post`

**Files:**
- Modify: `hadar_tracker/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `Signal` from `hadar_tracker.models` (Task 1).
- Produces: `format_message(subject, tags, body, root_subject=None, signal=None) -> str` — new trailing `signal` param.
- Produces: `send_post(bot_token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None) -> None` — new trailing `signal` param, passed through to `format_message`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notifier.py` (add `from hadar_tracker.models import Signal` to the imports at the top):

```python
from hadar_tracker.models import Signal


def _signal(**overrides):
    fields = dict(
        is_signal=True,
        ticker_mentioned="Aerodrome",
        ticker_guess="ARDM",
        action="add",
        conviction="medium",
        price_levels="close above 460",
        rationale="expects breakout",
    )
    fields.update(overrides)
    return Signal(**fields)


def test_format_message_appends_signal_section_when_is_signal_true():
    out = notifier.format_message("s", (), "b", signal=_signal())
    assert out == 's\n\nb\n\n🤖 Signal: ADD — ARDM (conviction: medium)\n   "expects breakout"'


def test_format_message_omits_signal_section_when_is_signal_false():
    out = notifier.format_message("s", (), "b", signal=_signal(is_signal=False))
    assert out == "s\n\nb"


def test_format_message_omits_signal_section_when_signal_is_none():
    out = notifier.format_message("s", (), "b", signal=None)
    assert out == "s\n\nb"


def test_format_message_signal_without_ticker_guess_omits_dash():
    out = notifier.format_message("s", (), "b", signal=_signal(ticker_guess=None))
    assert "🤖 Signal: ADD (conviction: medium)" in out


def test_send_post_passes_signal_through_to_format_message(monkeypatch):
    FakeBot.last = {}
    monkeypatch.setattr(notifier, "Bot", FakeBot)
    notifier.send_post("tok", "42", "s", (), "b", signal=_signal())
    assert "🤖 Signal: ADD" in FakeBot.last["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifier.py -v`
Expected: FAIL — `TypeError: format_message() got an unexpected keyword argument 'signal'`.

- [ ] **Step 3: Implement**

In `hadar_tracker/notifier.py`, add the import and replace `format_message` and `send_post`:

```python
from __future__ import annotations

import asyncio
from typing import Sequence

from telegram import Bot

from hadar_tracker.models import Signal

_CAPTION_LIMIT = 1024


def format_message(
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
    signal: Signal | None = None,
) -> str:
    """Build the notification text for a post.

    Layout (each present part on its own line, then a blank line, then body,
    then an optional trailing signal section):
        <subject>
        🏷 TEVA, ICL
        ↩️ Replying to: <root_subject>

        <body>

        🤖 Signal: ADD — DJIN (conviction: medium)
           "close above 460 → breakout"
    Empty/omitted parts are skipped. The signal section only appears when
    `signal` is given AND `signal.is_signal` is true — a classified-as-noise
    post (or a classification failure, where `signal` is None) renders
    exactly as it did in Phase 1.
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
    if signal is not None and signal.is_signal:
        lines.append("")
        header = f"🤖 Signal: {signal.action.upper()}"
        if signal.ticker_guess:
            header += f" — {signal.ticker_guess}"
        header += f" (conviction: {signal.conviction})"
        lines.append(header)
        if signal.rationale:
            lines.append(f'   "{signal.rationale}"')
    return "\n".join(lines).strip()


def send_post(
    bot_token: str,
    chat_id: str,
    subject: str,
    tags: Sequence[str],
    body: str,
    root_subject: str | None = None,
    image_path: str | None = None,
    signal: Signal | None = None,
) -> None:
    """Send one Telegram message for a post: photo+caption if image_path is
    set, otherwise a plain text message. Appends a trade-signal section if
    `signal` is given and classified as a real signal."""
    text = format_message(subject, tags, body, root_subject, signal)
    asyncio.run(_send_post_async(bot_token, chat_id, text, image_path))
```

(leave `send_alert`, `_send_post_async`, `_send_alert_async` exactly as they are)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifier.py -v`
Expected: PASS (all existing tests plus the 5 new ones).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add hadar_tracker/notifier.py tests/test_notifier.py
git commit -m "feat: append trade-signal section to Telegram notifications"
```

---

### Task 7: `check.py` — wire classification into `process_new_posts`

**Files:**
- Modify: `hadar_tracker/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `classify_post` from `hadar_tracker.signal` (Task 5), `Signal` from `hadar_tracker.models` (Task 1), updated `send_post`/`insert_post` (Tasks 6, 3).
- Produces: `process_new_posts(conn, config, posts, download=None, send_post=None, classify=None) -> list[Post]` — new trailing `classify` injection param, defaulting to the real `classify_post` at call time (same pattern as `download`/`send_post`).

- [ ] **Step 1: Update existing test fakes so they accept the new `signal` argument**

`process_new_posts` will call `send_post(...)` with `signal` as an 8th positional argument. Any test double with an explicit fixed signature (not `*args, **kwargs`) must accept it, or it'll raise `TypeError: too many positional arguments`. In `tests/test_check.py`:

Change the import line at the top:
```python
from hadar_tracker.models import Post, Signal
```

In `test_process_inserts_downloads_and_notifies`, change:
```python
def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None):
```
to:
```python
def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None):
```

In `test_process_keeps_earlier_successes_when_later_post_send_fails`, change:
```python
def flaky_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None):
```
to:
```python
def flaky_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None):
```

In `test_run_check_success_path`, change:
```python
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_post",
        lambda token, chat_id, subject, tags, body, root_subject=None, image_path=None: sent.append(body),
    )
```
to:
```python
    monkeypatch.setattr(
        "hadar_tracker.notifier.send_post",
        lambda token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None: sent.append(body),
    )
```

In `test_run_check_end_to_end_through_real_parser`, change:
```python
    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None):
        sent.append((subject, tags, body, root_subject, image_path))
```
to:
```python
    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None):
        sent.append((subject, tags, body, root_subject, image_path))
```
and, at the end of that same test (after the existing `assert len(sent) == 4`), add:
```python
    # No OPENROUTER_API_KEY configured in this test's Config, so
    # classify_post short-circuits to None for every post — the whole real
    # pipeline (parser -> check -> db) must stay fully inert for Phase 2
    # when no key is set, exactly like Phase 1 behaved.
    signal_rows = conn.execute("SELECT signal_json FROM posts").fetchall()
    assert all(row["signal_json"] is None for row in signal_rows)
```

(`test_process_skips_already_seen_posts`, `test_process_does_not_persist_post_when_send_fails`, and `test_run_check_reports_failure_and_alerts_when_processing_fails` already use `lambda *a, **k: ...` / `def failing_send(*args, **kwargs)`, which already accept any number of positional args — no change needed there. `test_run_check_reports_failure_and_alerts` never reaches `send_post` at all — no change needed.)

- [ ] **Step 2: Write new tests for the classify integration**

Append to `tests/test_check.py`:

```python
def test_process_calls_classify_with_post_image_path_and_config_and_persists_signal(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)
    calls = []

    def fake_classify(post, image_path, api_key, model):
        calls.append((post.msg_id, image_path, api_key, model))
        return Signal(
            is_signal=True,
            ticker_mentioned="Aerodrome",
            ticker_guess="ARDM",
            action="add",
            conviction="medium",
            price_levels="close above 460",
            rationale="expects breakout",
        )

    sent = []

    def fake_send(token, chat_id, subject, tags, body, root_subject=None, image_path=None, signal=None):
        sent.append(signal)

    posts = [Post("2001", "t", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=fake_send,
        classify=fake_classify,
    )

    assert calls == [("2001", None, config.openrouter_api_key, config.openrouter_model)]
    assert sent[0].action == "add"
    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='2001'").fetchone()
    stored = json.loads(row["signal_json"])
    assert stored["action"] == "add"
    assert stored["ticker_guess"] == "ARDM"


def test_process_persists_null_signal_json_when_classify_returns_none(tmp_path):
    conn = make_conn()
    config = make_config(tmp_path)

    posts = [Post("2002", "t", 1, "900", "s", "b", ())]
    check.process_new_posts(
        conn, config, posts,
        download=lambda *a, **k: None,
        send_post=lambda *a, **k: None,
        classify=lambda *a, **k: None,
    )

    row = conn.execute("SELECT signal_json FROM posts WHERE msg_id='2002'").fetchone()
    assert row["signal_json"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_check.py -v`
Expected: FAIL — `TypeError: process_new_posts() got an unexpected keyword argument 'classify'` (and the updated fakes will fail differently until `check.py` itself is updated — that's expected at this point).

- [ ] **Step 4: Implement**

Replace `hadar_tracker/check.py`'s imports and `process_new_posts`:

```python
from __future__ import annotations

import dataclasses
import json
import logging
import sys

from hadar_tracker import db, images, notifier
from hadar_tracker.config import Config, load_config
from hadar_tracker.models import Post
from hadar_tracker.scraper import client
from hadar_tracker.signal import classify_post
from hadar_tracker.util import now_iso


def process_new_posts(
    conn,
    config: Config,
    posts: list[Post],
    download=None,
    send_post=None,
    classify=None,
) -> list[Post]:
    """Download any attachment, classify it into a trade signal, notify, then
    persist unseen posts — one message each. Returns the posts newly
    processed.

    Classification (`classify`) runs between download and notify, and is
    fail-open by contract (classify_post never raises — see signal.py): a
    classification problem must never block, delay, or duplicate-send a
    notification, unlike a genuine Telegram/DB failure below, which stays
    fail-loud exactly as it was in Phase 1.

    Notification happens before the DB insert so that if `send_post` raises
    (e.g. a real Telegram API error), the post is NOT marked as seen and will
    be retried on the next run instead of being silently and permanently
    dropped. Earlier posts in the same batch that already succeeded remain
    committed even if a later post's send fails.

    `download`, `send_post`, and `classify` are injected so this is
    unit-testable without a live network, Telegram, or OpenRouter call. They
    resolve to the real functions at call time (not as def-time defaults) so
    callers like run_check can be tested by monkeypatching
    `notifier.send_post` / `hadar_tracker.signal.classify_post`.
    """
    if download is None:
        download = images.download_image
    if send_post is None:
        send_post = notifier.send_post
    if classify is None:
        classify = classify_post

    new_posts: list[Post] = []
    for post in posts:
        if db.post_exists(conn, post.msg_id):
            continue

        image_local_path: str | None = None
        if post.image_file_name:
            image_local_path = download(post.image_file_name, config.images_dir)

        signal = classify(
            post,
            image_local_path,
            config.openrouter_api_key,
            config.openrouter_model,
        )
        signal_json = json.dumps(dataclasses.asdict(signal)) if signal else None

        send_post(
            config.telegram_bot_token,
            config.telegram_chat_id,
            post.subject,
            post.tags,
            post.body,
            post.root_subject,
            image_local_path,
            signal,
        )
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
            signal_json,
        )
        new_posts.append(post)

    return new_posts
```

(leave `run_check` and `main` exactly as they are — they call `process_new_posts` with only 3 positional args, so the new trailing `classify=None` default keeps them working unmodified)

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_check.py -v`
Expected: PASS (all existing tests, updated to accept `signal`, plus the 2 new classify-integration tests).

- [ ] **Step 6: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: All PASS — this is the last task, so this is the full green suite for the feature.

- [ ] **Step 7: Commit**

```bash
git add hadar_tracker/check.py tests/test_check.py
git commit -m "feat: wire LLM trade-signal classification into the live check pipeline"
```

---

## Manual smoke test (after all tasks complete, before deploying)

Per the project's existing testing discipline ("manual smoke test against the live endpoint before deploying each change to the VPS"), and mirroring the dry run already done during brainstorming:

```bash
OPENROUTER_API_KEY=<a real key> TELEGRAM_BOT_TOKEN=<real> TELEGRAM_CHAT_ID=<real> ./.venv/Scripts/python.exe -m hadar_tracker.check
```

Confirm in the resulting Telegram message(s) that a genuinely new post either shows no signal section (classified as noise, or `is_signal=False`) or shows a `🤖 Signal: ...` line with a plausible action/ticker/conviction. Check `data/hadar.sqlite3`'s `signal_json` column for the corresponding row to confirm it was persisted.

## Self-Review Notes

- **Spec coverage:** Every section of `docs/superpowers/specs/2026-07-21-phase2-llm-signal-design.md` maps to a task — models (Task 1), thread transcript (Task 2), storage/migration (Task 3), config (Task 4), the classifier itself including vision (Task 5), Telegram formatting (Task 6), and the check.py wiring + fail-open contract (Task 7). Backfill/batch classification, model-choice tuning, and ticker-resolution accuracy are explicitly out of scope for v1 per the spec's Non-goals/Open items, so no task exists for them — that's intentional, not a gap.
- **Placeholder scan:** No TBD/TODO; every step has complete, runnable code.
- **Type consistency:** `Signal`'s field names (`is_signal`, `ticker_mentioned`, `ticker_guess`, `action`, `conviction`, `price_levels`, `rationale`) are identical across Task 1 (definition), Task 5 (`_to_signal`), Task 6 (`format_message`'s rendering), and Task 7 (`dataclasses.asdict(signal)`/tests) — checked field-by-field. `classify_post`'s signature (`post, image_path, api_key, model`) matches exactly between Task 5's definition and Task 7's call site and test fakes. `process_new_posts`'s new `classify` param name matches its use in Task 7's tests.
