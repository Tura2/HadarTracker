# HadarTracker — Phase 2 Design: LLM Trade-Signal Classification

**Date:** 2026-07-21
**Status:** Approved

## Context

Phase 1 (scrape → store → notify) is live: every new post from Hadar reaches the user via
Telegram with subject, tags, reply context, body, and any attached image. That's raw data —
the user still has to read each message himself and judge whether it represents an actual
trading action (and what it is) versus commentary/banter/noise.

Phase 2's goal, per the Phase 1 spec, is to "understand his trader-specific language well
enough to classify which posts represent real trading actions." This spec covers that: adding
an LLM classification step to the existing live pipeline that reads each new post (plus its
thread context and any attached chart image) and returns a structured trade signal, appended to
the Telegram notification and stored alongside the post.

**Data investigation before designing this** (against the real 1,491-row backfilled DB and one
live payload pull):

- **Formal ticker tags are sparse and unreliable.** Only 10.7% of all stored posts carry any
  `Tags` value; even root (`Level == 1`) posts are only tagged 26.3% of the time. Checked
  site-wide (not just Hadar's authored posts) via a live payload: root posts across *all* users
  are tagged 36% of the time, replies only 3.8%. **Conclusion: there is no reliable structured
  field to key a signal on a ticker — the classifier has to read free text.**
- **The live "per-user" endpoint is not server-side filtered.** A single call to
  `HD_STREAM_FORUM_USER_MESSAGES.ashx` with `UserId=5609` returned 287 items from 97 distinct
  users — filtering to Hadar happens entirely client-side in `parse_posts`. This means the full
  multi-user conversation around each of Hadar's posts is already present in the very payload
  `check.py` fetches every run; nothing beyond the root's subject is currently kept from it.
- **The trade thesis usually lives in the reply itself, not the root.** Sampling real replies:
  root subjects mostly just name the company ("Djin at daily lows but...", "Aerodrome looks
  headed up"); the reply carries the actual call ("needs a close above 460, I estimate — that
  there'll be a breakout", "support, maybe a bull flag"). Root context matters most for
  resolving *which company*, especially for a bare "look at this"/image-only-style reply whose
  own text doesn't name anything.
- **Company names are informal, not ticker symbols** (e.g. "Aerodrome" for ARDM) — resolvable
  by a capable LLM from real-world knowledge of the text, not forum-specific slang requiring a
  custom glossary.
- **Images are common but never text-free.** 15% of posts (223/1,491) have an attached chart
  image; none of those have both an empty subject *and* empty body — there's always some
  accompanying text, though it may be too sparse to carry the actual price levels/annotations
  drawn on the chart itself.

## Goals

- For every new post `check.py` sends to Telegram, also produce a structured trade-signal
  read: is this actually a trade action (vs. noise/banter/admin chatter), which company, what
  action, how confident, what price levels were mentioned, and a one-line rationale.
- Give the classifier the full in-payload thread transcript (every item sharing the post's
  `L1`, any user, already present in the fetched payload) so it has the same conversational
  context a human reader would, at zero extra network cost.
- When a post has an attached chart image, include that image in the classification call (via
  a vision-capable model) since chart annotations often carry information the caption text
  doesn't.
- Append the signal to the existing Telegram message and persist it alongside the post so it's
  queryable later (e.g., "show me every 'buy' call this month").
- Never let a classification failure block, delay, or lose a notification — fail open.

## Non-goals (Phase 2 v1)

- No backfill/batch classification of the ~1,491 already-stored historical posts — live-only
  for now. (Revisit once the live pipeline is proven; the same `classify_post` function should
  be directly reusable against stored posts later without redesign.)
- No thread-transcript reconstruction beyond what's already in the fetched payload — no new
  scrape calls, no fetching a thread's older history from before the payload's ~1 day window.
- No automatic trade execution or portfolio tracking — this is advisory text in Telegram, not
  an execution system.
- No custom company-name → ticker glossary. The LLM's own knowledge resolves informal company
  names; if this proves unreliable in practice, a glossary is a later addition, not part of v1.

## Architecture

```text
hadar_tracker/
  scraper/
    parse.py        # extended: also builds Post.thread_transcript
  signal.py          # NEW: OpenRouter call, structured trade-signal classification
  check.py           # extended: classify_post hooked in before send_post
  notifier.py        # extended: format_message gains a signal section
  db.py              # extended: posts.signal_json column
  models.py          # extended: Post.thread_transcript, ThreadItem, Signal
```

### `models.py` additions

```python
@dataclass(frozen=True)
class ThreadItem:
    author: str       # "hadar" | "other" — no real usernames needed, only Hadar's own
                       # trade actions are the thing being analyzed
    level: int
    subject: str
    body: str
    posted_at: str

@dataclass(frozen=True)
class Signal:
    is_signal: bool
    ticker_mentioned: str | None    # company/ticker text as it appeared in the post
    ticker_guess: str | None        # LLM's best-guess resolved ticker symbol
    action: str                     # "buy" | "sell" | "trim" | "add" | "watch" | "none"
    conviction: str                 # "low" | "medium" | "high"
    price_levels: str | None        # free text, e.g. "close above 460"
    rationale: str                  # one-line summary of the reasoning
```

`Post` gains `thread_transcript: tuple[ThreadItem, ...] = ()`.

### `scraper/parse.py` — thread transcript capture

`parse_posts` already scans the entire raw `Data` array once to resolve `root_subject` (see
Phase 1's full-payload-scan invariant). Extend that same scan: for every item sharing a given
`L1`, keep `(author, level, subject, body, posted_at)` instead of discarding everything but the
root's subject. When building each Hadar `Post`, attach the ordered (`posted_at` ascending)
list of thread items whose `posted_at` is at or before that post's own, from the same thread
group — this is the "conversation so far" as Hadar would have seen it.

This preserves the existing invariant (full-payload scan, not just the filtered subset) and
requires no new network calls — it's the same payload `client.fetch_posts` already fetches.

### `signal.py` (new module)

- `classify_post(post: Post, image_path: str | None, client=None) -> Signal | None`
- Builds a prompt from: the post's own subject/body/tags, and the thread transcript rendered as
  a chronological "Thread so far: [root]: '...' → [reply]: '...' → ..." block.
- If `image_path` is set, calls a vision-capable model on OpenRouter with the image attached;
  otherwise a text-only model. Both paths request the same `Signal` JSON schema back (structured
  output / JSON mode).
- `client` is injected (defaults to a real OpenRouter HTTP client at call time, not at def-time
  — same pattern as `notifier.send_post`/`images.download_image`) so tests never hit the network.
- Returns `None` on *any* failure — bad HTTP status, timeout, malformed/unparseable response —
  never raises. This is the fail-open contract: a classification problem must never look like a
  post-processing problem to the caller.
- New config: `OPENROUTER_API_KEY` (required to actually classify; if unset, `classify_post`
  short-circuits to `None` immediately rather than erroring — Phase 2 is additive, Phase 1's
  notify/store contract must keep working even with no key configured).

### `check.py` change

In `process_new_posts`, between the existing image-download step and `send_post`:

```python
signal = classify_post(post, image_local_path)   # None on any failure — see Error handling
send_post(..., signal=signal)
db.insert_post(..., signal_json=json.dumps(asdict(signal)) if signal else None)
```

### `notifier.py` change

`format_message` gains an optional `signal: Signal | None` parameter. When present and
`is_signal` is true, append a trailing section:

```text
🤖 Signal: ADD — DJIN (conviction: medium)
   "close above 460 → breakout"
```

When `signal` is `None`, or `is_signal` is `False`, the message is unchanged from Phase 1 (no
section added) — noise gets flagged internally via storage, not surfaced as a Telegram line
per new post.

### `db.py` change

Add nullable `signal_json TEXT` column to `posts`. Stores the full `Signal` as JSON (same
serialization pattern already used for `tags`) — queryable later, e.g. filtering by `action`
via `json_extract`.

## Data flow

```text
check.py run (unchanged cadence, every 10-15 min)
  → scraper POSTs to HD_STREAM_FORUM_USER_MESSAGES.ashx (site-wide payload, ~97 users)
  → parse_posts filters to Hadar's new items, AND resolves each one's thread_transcript
    from the same payload (all users, all levels, up to that post's own timestamp)
  → for each new post:
      → download attached image if present (unchanged)
      → classify_post(post, image_path) → Signal | None
          (fail-open: any error → None, logged, notification proceeds unaffected)
      → send_post(... , signal)         → Telegram message, +signal section if classified
      → db.insert_post(..., signal_json)
  → on failure (scrape/DB/Telegram): log + Telegram alert + non-zero exit, unchanged from Phase 1
```

## Error handling

- Classification failures are fail-open by design (see `signal.py` above) — they must never
  cause a post to be retried, delayed, or dropped. This is a deliberate divergence from Phase
  1's "everything in `process_new_posts` is fail-loud" contract: a broken/rate-limited LLM
  provider is a much more likely and much lower-stakes failure mode than a broken Telegram send,
  and blocking real trade notifications on it would defeat the point of the tracker.
- A classification failure is still logged (so the gap is visible in logs) but does NOT trigger
  a Telegram alert or non-zero exit on its own — only genuine Phase-1-covered failures (scrape,
  DB, Telegram send) do that.
- If `OPENROUTER_API_KEY` is unset, the feature is simply inactive (every post gets `signal=None`)
  rather than erroring — Phase 1 behavior is the fallback, not a broken state.

## Testing

- Unit tests for `parse_posts`' thread_transcript construction against a multi-user sample
  payload fixture (extending `tests/fixtures/sample_stream.json` or adding a sibling fixture) —
  mirrors the existing `test_parse_reply_resolves_root_subject_when_root_is_another_user` test,
  proving the full-payload scan captures the whole thread, not just the root.
- Unit tests for `signal.py` with an injected fake OpenRouter client: success (well-formed JSON
  parses into `Signal`), malformed response (returns `None`), timeout/HTTP error (returns
  `None`), and the "no API key configured" short-circuit.
- Unit tests for `notifier.format_message` with `signal=None`, `signal.is_signal=False`, and a
  populated signal — confirming the section only appears in the last case.
- Extend `tests/test_check.py::test_run_check_end_to_end_through_real_parser` (or a sibling
  test) to cover a fake classifier returning both a real signal and `None`, confirming the
  Telegram send and DB insert both succeed either way.

## Open items to resolve during implementation (not blockers for v1)

1. **Specific OpenRouter model choice** (text and vision) — needs a small real-data eval:
   sample real subject/body/thread-transcript text (and a few chart images) and check output
   quality/cost across candidate models before locking one in.
2. **Ticker resolution accuracy** — how often `ticker_guess` actually resolves informal company
   names correctly is unverified until tested against real posts; if it's unreliable, a manual
   company-name → ticker glossary becomes a fast-follow.
3. **Backfill/batch classification** of the existing 1,491 stored posts is out of scope for v1
   but should be straightforward later: `classify_post` takes a `Post`, not a live payload, so
   it can run over `SELECT * FROM posts` directly once proven live.
