# Page structure investigation — Hadar's Sponser forum feed

Date: 2026-07-21
URL under test: `DEFAULT_FORUM_URL` = `https://www.sponser.co.il/ForumViewUserMessages.aspx?UserId=5609&ForumId=1&IsFull=1`

## Important deviation up front

`scripts/inspect_page.py` (headless Playwright, as adapted for this non-interactive
environment) **gets blocked by the site's WAF (Cloudflare) with an HTTP 403** before
any forum content renders. `tests/fixtures/user_messages_page1.html` therefore
contains the real, live-captured **block page**, not forum content — this is the
true, reproducible output of a plain headless-Playwright request to this URL, run
twice, with identical results both times.

Because that blocked the intended "read the rendered DOM" approach, the five
questions below were answered instead by:

1. Reading the network/response evidence from the blocked Playwright run itself
   (status code, headers, `navigator.webdriver`, UA string) — this **is** the
   answer to question 5 (bot detection), not a workaround.
2. Making a plain, unauthenticated HTTP GET (Python `urllib`, no browser engine,
   no JS execution, no cookies) to the exact same URL. This request was **not**
   blocked (HTTP 200) and returned the real ASP.NET page shell.
3. Reading the page shell's `<script>` includes to find `assets2022/forum.js`
   (the client-side renderer) and fetching that file the same way. It contains
   the real AJAX endpoint URLs, the exact HTML templates used to render each
   message, and the pagination logic — i.e., the ground truth for questions
   1, 3, and 4.
4. Calling the discovered JSON endpoint directly (same plain-HTTP approach) to
   confirm it returns real, complete post bodies with no login/session — the
   ground truth for question 2.

This plain-HTTP path was only used to gather **evidence for this findings
document** (to avoid fabricating answers). It does not touch or replace the
committed `scripts/inspect_page.py`, and it is not proposed here as the Task 5
scraping strategy — that decision (direct HTTP endpoint vs. browser automation
vs. Scrapling) is out of scope for this task and is flagged below under item 5.

All Hebrew strings below are UTF-8; some intermediate response bytes were
Windows-1255 (`cp1255`)-encoded despite claiming `charset=utf-8` in headers/meta
(the site has a real charset-mislabeling bug) — this was handled by decoding as
`cp1255` before parsing.

---

## 1. Load mechanism

**Client-side AJAX to a JSON endpoint**, confirmed from `assets2022/forum.js`:

```js
// forum.js, endPoints object
userMessagesRealTime: 'https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx',

// forum.js, getRealTimeUserMessages()
function getRealTimeUserMessages(forumId = 1, uid = 0, isFull = 1) {
  ...
  $.ajax({
    type: "POST",
    url: url,                       // endPoints.userMessagesRealTime
    data: { ForumId: forumId, IsFull: isFull, UserId: uid, m: onlyMessages },
    dataType: "json",
    ...
  });
}
```

The static page shell (`ForumViewUserMessages.aspx`) ships with an **empty**
`<ul id="forumThread" class="">` (only a hidden header `<li>`) plus a loading
spinner:

```html
<ul id="forumThread" class="">
    <li id="regularMessagesHeader" class="hide"> ... </li>
</ul>
<section class="forum-loader-svg"><img src="assets2022/loading.gif" /></section>
```

and an inline bootstrap call:

```js
forum.init({ pageType: 'user', commentsToShow: 10, rootElement: 'forumThread',
             watchlist: true, charts: true, ob: false });
```

`forum.init` (pageType `'user'`) calls `getRealTimeUserMessages(forumId, uid, isFull)`,
which **POST**s to `Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx` with body
`ForumId`, `IsFull`, `UserId`, `m` (m = 1 iff `IsFull=0`), gets back JSON, and
builds the message HTML client-side via `buildMessagesTree()` / `renderMessage()`.

**Conclusion for Task 5: hit `POST https://www.sponser.co.il/Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx`
directly** (form-encoded body `ForumId=1&IsFull=1&UserId=5609&m=0`) rather than
rendering the page in a browser — it is faster, and (per item 5) it is also the
version of this request that is *not* blocked by the WAF.

Verified live: this POST, made with a plain `urllib` client and no cookies,
returned HTTP 200 and a 356,712-byte JSON body: `{"Data": [...304 items...],
"Info": {"MainMsgCount": "1", "NumberOfPages": "0", "IsMoreMsg": "0", "IsMG": "0"}}`.

## 2. Login required?

**No.** The endpoint above was called with no session cookies at all and
returned full, untruncated post bodies. Example (the longest `Msg` in the
304-item response):

- `MsgId: 8964352`, user `הדר` (`UserId 5609`), `DateCreated: "20/07/26 | 10:02"`
- `subject`: `"הודעה קצת תוקעת לחברות הדה סנטרס|21|"`
- `Msg` (2,484 characters, shown truncated here):

  > `שות החשמל פירסמה ביום שני החלטה תקדימית שקובעת כי חברת מנהל המערכת נגה לא תאפשר חיבור של חוות שרתים חדשות לרשת החשמל. ... [full 2,484-char article-length post follows, unclipped, ending] ... הציבור מוזמן להעביר את התייחסותו להוראת השעה עד ל-19 באוגוסט.`

There is a `login-link` in the page header (`loginPopup2022.aspx`, `rel="nofollow"`,
opens a popup) but it gates only interactive actions (posting, liking,
bookmarking) — `CanPost: false` appears in the anonymous JSON response's
`Forum` object, but message bodies themselves are fully present regardless.

## 3. Selectors (for Task 4)

Derived from `renderMessage()` / `buildMessagesTree()` in `forum.js`, which is
the exact template used to build what ends up in `#forumThread`:

```js
// buildMessagesTree(): opens one <li>/<article> per thread (root post)
response += '<li class="li_' + msgId + '">' +
            '<article class="forum-card  msg_' + msgId + '" msg-id="' + msgId + '">';

// renderMessage(): each individual message (root post OR nested comment)
let template = '<article class="forum-thread-item ' + commentClass + ' ' + msgWatchedFlag +
               ' ' + showComment + ' ' + stickyMsgHeaderClass + '" id="' + msgId + '" ' +
               videoAttribute + ' >';
...
let header = '<header ...>' +
  '<article><a ... class="forum-title ' + rootMsg + ' ...">' +
    '<h2>' + title + emptyBody + '</h2></a>' + tagsContainer + '</article>' +
  '<ul class="header-meta">' + headerIcons +
    '<address><a class="inline-popup ' + userColor + '" href=".../StreamForumUserData.aspx?u=' + userId + '&f=' + forumId + '">' + userIcon + userName + '</a></address>' +
    '<time class="' + dateClassName + '">' + timestamp + '</time>' +
  '</ul></header>';

let bodyContainerOpen = '<section class="msg-body-container msg-body-' + msgBodyId +
                        '  s-ph-s ' + showMsgBody + ' " msg-id="' + msgId + '">';
let bodyContainerMsg = '<section class="msg-body">' +
  '<article class="msg-text s-mb-s">' + body + '</article>' + fileContainer + linksBodyContainer +
  '</section>';
```

Concrete constants for Task 4:

| Constant | Value |
|---|---|
| `POST_CONTAINER_SELECTOR` | `article.forum-thread-item` (each root post *and* each nested reply is one of these; the root post additionally sits inside an outer `li.li_{msgId} > article.forum-card.msg_{msgId}[msg-id]` thread wrapper) |
| `POST_ID_ATTR` | the `id` HTML attribute on `article.forum-thread-item` (e.g. `id="8965472"`) — numeric `MsgId` from the JSON. (Also duplicated as the `msg-id` attribute on the outer thread `<article class="forum-card">` and on `<section class="msg-body-container msg-id="...">`.) |
| `POST_TIMESTAMP_SELECTOR` | `time` inside `ul.header-meta` → `article.forum-thread-item time` (or, scoped: `.header-meta time`). Text format: `DD/MM/YY \| HH:MM`, e.g. `"21/07/26 \| 13:23"` (Israel local time; `forum.js`'s `forumDateToIsoTimestamp()` parses it as `20{YY}-{MM}-{DD} {HH:MM}`). |
| `POST_TEXT_SELECTOR` | `article.msg-text` inside `section.msg-body` → `.msg-body article.msg-text` (post title/subject is separately in `.forum-title h2`). |
| author identification | `article.forum-thread-item address a.inline-popup` text = display name (`"הדר"`); `href` contains `?u={UserId}` — needed to distinguish Hadar's own root posts (`UserId=5609`) from other users' replies, since the `IsFull=1` feed interleaves both (see item 4). |

Confirmed directly from the live JSON response (`Handlers/HD_STREAM_FORUM_USER_MESSAGES.ashx`,
one representative item):

```json
{
  "MsgId": 8965472, "Level": 1, "L1": 1319199,
  "User": {"UserId": 5609, "Login": "הדר"},
  "subject": "תיקון יפה בבאפ..מעל 1400 התיקון ימשך",
  "Msg": "", "DateCreated": "21/07/26 | 13:23",
  "Forum": {"ForumId": 1, "ForumName": "שוק ההון הישראלי", "CanPost": false}
}
```

**`CHART_IMG_SELECTOR` — real behavior differs from the brief's assumption.**
Charts are **not** embedded as a per-post `<img>` in the current, live template
(the code that would have done that is present but commented out in
`forum.js`, lines ~1302–1314: `chartContainer += '<figure class="forum-msg-chart"...`).
Instead there is a single shared, page-level popover element:

```html
<section id="popover-content">
  <figure>
    <img id="popover-image" src="https://chart.bursagraph.co.il/graph2013.php?what_to_do=chart&page=portfolio&mainsug=2&nrnum=230011&time_range=3M&chart_type=daily&chart_style=candles&thewidth=456&theheight=228&rezef=&mn=1" alt=""/>
    <figcaption><a id="popover-url" href="" target="_blank">לצפייה בגרף אינטראקטיבי לחץ כאן</a></figcaption>
  </figure>
</section>
```

which `forum.js` repoints (via `document.getElementById('popover-image')`, line
~2950) when the user hovers/clicks a stock-tag link inside a post:
`a.show-popover[data-symbol="{symbol}"]` (rendered per stock tag inside
`ul.tags.s-breadcrumb` in each message). The live chart URL host is confirmed
as **`chart.bursagraph.co.il`** (as the brief expected), current active path
`graphSponser.php?s={symbol}&thewidth=...&theheight=...&chart_type=daily&time_range=...`
(see `forum.js` lines ~1986, ~2995).

Practical implication for Task 4/5: to get a chart image for a post, resolve
`data-symbol` from that post's `a.show-popover` tag link(s) and construct the
`chart.bursagraph.co.il/graphSponser.php?s={symbol}&...` URL directly — do not
look for a static `<img>` chart element inside the post markup, there isn't one.

## 4. Pagination scheme

For **this specific page type** (`ForumViewUserMessages.aspx`, `pageType: 'user'`
in `forum.init`), **there is no page-number pagination** — the AJAX call
(`getRealTimeUserMessages`) takes no page parameter at all, and the live response
returned **all 304 items in a single call**, with:

```json
"Info": {"MainMsgCount": "1", "NumberOfPages": "0", "IsMoreMsg": "0", "IsMG": "0"}
```

`IsMoreMsg: "0"` and `NumberOfPages: "0"` confirm the server considers this
response complete — there is nothing more to fetch for this user/forum
combination via this endpoint.

(For contrast: the *general* forum listing, `pageType: 'forum'`, does use a
`PageId` query-string parameter — `getRealTimeForumMessages(forumId, pageId)` —
and the *tag* page uses `?p={page}&z={pageSize}`. Neither applies to the
user-messages feed this project targets.)

`IsFull=1` vs `IsFull=0` (both present as nav links on the page,
`href="ForumViewUserMessages.aspx?UserId=5609&ForumId=1&IsFull=1"` /
`...IsFull=0`) controls whether replies from other users are included
alongside Hadar's own root posts (`IsFull=1`, the configured `DEFAULT_FORUM_URL`)
or only Hadar's own messages (`IsFull=0`) — this is a content filter, not
pagination. Because `IsFull=1` interleaves other users' replies (confirmed: the
JSON response includes items with `User.UserId` other than 5609, e.g.
`UserId: 116209, Login: "אביהו1245"`), Task 4/5 must filter `Data[].User.UserId == 5609`
to isolate Hadar's own posts.

**Conclusion for Task 5's `page_url()` / paging loop:** there is nothing to
paginate for this endpoint — one request returns the complete history. `page_url()`
as originally conceived (query-string page number) does not apply here and
should be reconsidered/simplified for this data source.

## 5. Bot detection

**Confirmed and significant: plain headless Playwright is blocked by a WAF (Cloudflare) with HTTP 403.**

Reproduced twice (`scripts/inspect_page.py`, run independently on 2026-07-21),
identical result both times — `tests/fixtures/user_messages_page1.html` is the
real captured block page:

```html
<h1 class="s-h1 fw-bold">הגישה לאתר נחסמה!</h1>
...
<p class="mb-0 text-start">
    אתר זה משתמש בשירות אבטחה כדי להגן על עצמו מפני התקפות מקוונות. הפעולה שביצעת
    זה עתה הפעילה את פתרון האבטחה. ישנן מספר פעולות שעלולות להפעיל את החסימה הזו
    כולל חסימה מחוץ לגבולות מדינת ישראל
</p>
```

("This site uses a security service to protect itself from online attacks...
several actions may trigger this block including blocking from outside Israel's
borders" — a generic reason list, not necessarily the true trigger here, see
below.)

Confirmed via direct `page.goto()` response inspection (not just the rendered
HTML):

```
STATUS 403
HEADERS {..., 'cf-ray': 'a1e98d77bcd1c233-TLV', 'server': 'cloudflare', ...}
UA    Mozilla/5.0 (...) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/149.0.7827.55 Safari/537.36
navigator.webdriver = True
```

This is a real Cloudflare-served block (not a CAPTCHA/interstitial requiring
interaction) — the `cf-ray` header and `server: cloudflare` confirm Cloudflare
WAF/bot-management is the mechanism. Automation is plainly visible in the
request: `navigator.webdriver` is `true` and the UA string literally contains
`HeadlessChrome`, both textbook automated-browser signatures.

By contrast, a plain HTTP GET/POST with a normal desktop-Chrome `User-Agent`
string and **no JS engine at all** (Python `urllib`, no Playwright/CDP involved)
to the *same URLs* (both the page shell and the `HD_STREAM_FORUM_USER_MESSAGES.ashx`
JSON endpoint) reproducibly returned **HTTP 200** with full real content —
i.e., this specific block is tied to the automated-browser fingerprint
(CDP/`navigator.webdriver`/Headless UA), not to this sandbox's source IP/geography
in general (a pure IP/geo block would have blocked the plain HTTP client too).

**Flag for Task 5 (per the brief's instruction — not silently worked around
here):** plain Playwright, as used by `scripts/inspect_page.py`, cannot reach
this site. If Task 5's scraper is built on Playwright/browser automation, it
will hit this same 403 and needs either stealth configuration or escalation to
Scrapling, as the brief anticipates. Separately, since item 1's answer is "hit
the JSON endpoint directly," Task 5 may be able to sidestep browser automation
(and this specific block) entirely by using a plain HTTP client for the
`.ashx` endpoint — but that architectural decision is out of scope for this
investigation task and is left for whoever picks up Task 5.

---

## Files produced

- `scripts/inspect_page.py` — headless, non-interactive investigation script (adapted from the brief; captures HTML/screenshot/network log, no `input()`).
- `tests/fixtures/user_messages_page1.html` — real, live-captured output of that script (the Cloudflare block page — see deviation note above).
- `tests/fixtures/user_messages_page1.png` — matching screenshot (left untracked per the brief).
