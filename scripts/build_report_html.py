"""Assemble the final self-contained HTML labeling report from
scripts/_report_data.json (produced by generate_labeling_report.py).

Throwaway analysis tooling, not part of the shipped Phase 1/2 pipeline.
"""
from __future__ import annotations

import json

DATA_PATH = "scripts/_report_data.json"
OUT_PATH = (
    r"C:\Users\offir\AppData\Local\Temp\claude\c--Users-offir-Desktop-Projects-HadarTracker"
    r"\a7aaf1a5-32f4-4663-b9d7-d7014bbae2e5\scratchpad\hadar_labeling_report.html"
)

with open(DATA_PATH, "r", encoding="utf-8") as fh:
    report_data = json.load(fh)

data_json = json.dumps(report_data, ensure_ascii=False).replace("</", "<\\/")

BUCKET_META = {
    "own_root": {"label": "Own Threads (root posts)", "hint": "He started this thread — the primary candidate for real actions/analysis. Expand “full thread” to see how others reacted."},
    "reply_own": {"label": "Replies in His Own Threads", "hint": "Continuing a thread he started."},
    "reply_other": {"label": "Replies in Someone Else's Thread", "hint": "The hypothesis under test: mostly graphs / low-signal answers. Expand “full thread” to see what he was actually replying to."},
    "graphs": {"label": "Graphs (all buckets)", "hint": "Every post with an attached chart image, pooled across all 3 buckets above, for checking whether replies-elsewhere really are “mostly graphs”."},
}

html = r"""<!doctype html>
<title>Hadar Posts — Labeling Report</title>
<meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    background: #f6f7f9; color: #1a1a1a;
  }
  @media (prefers-color-scheme: dark) {
    body { background: #14161a; color: #e8e8e8; }
  }
  :root[data-theme="dark"] body { background: #14161a; color: #e8e8e8; }
  :root[data-theme="light"] body { background: #f6f7f9; color: #1a1a1a; }

  header { padding: 16px 20px; border-bottom: 1px solid rgba(128,128,128,.25); position: sticky; top: 0; background: inherit; z-index: 10; }
  header h1 { font-size: 18px; margin: 0 0 4px; }
  header p { margin: 0; font-size: 13px; opacity: .75; }
  .statbar { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
  .statbar span b { font-size: 14px; }
  .toolbar { display: flex; gap: 10px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  button, select, input[type=text] {
    font: inherit; border-radius: 6px; border: 1px solid rgba(128,128,128,.4);
    background: rgba(128,128,128,.08); color: inherit; padding: 6px 10px; cursor: pointer;
  }
  button:hover { background: rgba(128,128,128,.2); }
  button.primary { background: #3b6fe0; color: white; border-color: #3b6fe0; }
  button.primary:hover { background: #2f5bc4; }
  input[type=text] { cursor: text; min-width: 220px; }

  .tabs { display: flex; gap: 6px; padding: 10px 20px 0; }
  .tabs button { border-bottom: 3px solid transparent; border-radius: 6px 6px 0 0; }
  .tabs button.active { border-bottom-color: #3b6fe0; background: rgba(59,111,224,.15); font-weight: 600; }
  .tabhint { padding: 6px 20px 0; font-size: 12px; opacity: .7; }

  .filters { display: flex; gap: 10px; padding: 10px 20px; flex-wrap: wrap; align-items: center; font-size: 13px; }
  .filters label { display: flex; gap: 5px; align-items: center; }

  #cards { padding: 6px 20px 20px; display: flex; flex-direction: column; gap: 10px; max-width: 900px; margin: 0 auto; }
  .card { border: 1px solid rgba(128,128,128,.3); border-radius: 10px; padding: 12px 14px; background: rgba(128,128,128,.04); }
  .card-meta { display: flex; justify-content: space-between; font-size: 11px; opacity: .65; margin-bottom: 4px; }
  .card-subject { font-weight: 600; margin-bottom: 4px; }
  .card-root { font-size: 12px; opacity: .7; margin-bottom: 6px; }
  .card-body { white-space: pre-wrap; font-size: 14px; line-height: 1.45; margin-bottom: 8px; }
  .tags { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 8px; }
  .tag { font-size: 11px; background: rgba(59,111,224,.18); color: #3b6fe0; padding: 2px 7px; border-radius: 999px; }
  .card img { max-width: 100%; max-height: 340px; border-radius: 6px; display: block; margin-bottom: 8px; }
  .labelrow { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .labelrow button { font-size: 12px; padding: 5px 9px; }
  .labelrow button.confirmed[data-l="real"] { background: #1f9d55; color: white; border-color: #1f9d55; }
  .labelrow button.confirmed[data-l="graph"] { background: #b8860b; color: white; border-color: #b8860b; }
  .labelrow button.confirmed[data-l="noise"] { background: #888; color: white; border-color: #888; }
  .labelrow button.confirmed[data-l="unsure"] { background: #a83bd0; color: white; border-color: #a83bd0; }
  .labelrow button.suggested[data-l="real"] { border: 2px dashed #1f9d55; color: #1f9d55; }
  .labelrow button.suggested[data-l="graph"] { border: 2px dashed #b8860b; color: #b8860b; }
  .labelrow button.suggested[data-l="noise"] { border: 2px dashed #888; }
  .labelrow button.suggested[data-l="unsure"] { border: 2px dashed #a83bd0; color: #a83bd0; }
  .suggest-note { font-size: 11px; opacity: .6; }
  .card.confirmed { border-left: 4px solid #3b6fe0; }
  .card.suggested-only { border-left: 4px dashed rgba(128,128,128,.5); }

  .pager { display: flex; gap: 8px; align-items: center; justify-content: center; padding: 14px; font-size: 13px; }
  .empty { text-align: center; opacity: .6; padding: 40px; }

  .thread-toggle { margin-top: 6px; }
  .thread-toggle summary { cursor: pointer; font-size: 12px; opacity: .75; padding: 4px 0; }
  .thread-toggle summary:hover { opacity: 1; }
  .thread-list { margin-top: 6px; border-left: 2px solid rgba(128,128,128,.3); padding-left: 10px; display: flex; flex-direction: column; gap: 8px; }
  .thread-msg { font-size: 13px; padding: 6px 8px; border-radius: 6px; background: rgba(128,128,128,.06); }
  .thread-msg.is-hadar { background: rgba(59,111,224,.12); border-left: 3px solid #3b6fe0; }
  .thread-msg.is-current { outline: 2px solid #1f9d55; }
  .thread-msg .tm-meta { font-size: 11px; opacity: .6; display: flex; justify-content: space-between; }
  .thread-msg .tm-subject { font-weight: 600; margin: 2px 0; }
  .thread-msg .tm-body { white-space: pre-wrap; }
</style>

<header>
  <h1>Hadar — Post Labeling Report</h1>
  <p>Last 90 days · dashed buttons are MY suggested label (a heuristic guess) · click to confirm or click a different one to correct</p>
  <div class="statbar" id="statbar"></div>
  <div class="toolbar">
    <button class="primary" id="exportBtn">📋 Export my labels (copy JSON)</button>
    <button id="acceptPageBtn">✓ Accept all suggestions on this page</button>
    <button id="clearBtn">🗑 Clear all confirmed labels</button>
    <span id="labelTally" style="font-size:12px;opacity:.75;"></span>
  </div>
</header>

<nav class="tabs" id="tabs"></nav>
<div class="tabhint" id="tabhint"></div>

<div class="filters">
  <input type="text" id="search" placeholder="Search subject/body…">
  <label><input type="checkbox" id="fImage"> has image only</label>
  <label><input type="checkbox" id="fTags"> has ticker tag only</label>
  <select id="fLabel">
    <option value="">any effective label</option>
    <option value="unconfirmed">not yet confirmed</option>
    <option value="real">✅ real action</option>
    <option value="graph">📊 graph-only</option>
    <option value="noise">💬 doesn't matter</option>
    <option value="unsure">❓ unsure</option>
  </select>
</div>

<div id="cards"></div>
<div class="pager">
  <button id="prevPage">◀ Prev</button>
  <span id="pageInfo"></span>
  <button id="nextPage">Next ▶</button>
</div>

<script type="application/json" id="post-data">__DATA_JSON__</script>
<script type="application/json" id="bucket-meta">__BUCKET_META__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById('post-data').textContent);
  const ALL_POSTS = DATA.posts;
  const THREADS = DATA.threads; // thread_group -> [{id,is_hadar,level,subject,body,date}], full multi-user context
  const BUCKET_META = JSON.parse(document.getElementById('bucket-meta').textContent);
  const BUCKETS = Object.keys(BUCKET_META);
  const TAB_FILTERS = {
    own_root: p => p.bucket === 'own_root',
    reply_own: p => p.bucket === 'reply_own',
    reply_other: p => p.bucket === 'reply_other',
    graphs: p => !!p.image,
  };
  const PAGE_SIZE = 40;
  const LS_KEY = 'hadar_labels_v1';

  let labels = {}; // user-confirmed/corrected labels only — p.suggested holds the heuristic guess
  try { labels = JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch (e) { labels = {}; }

  let state = { bucket: BUCKETS[0], page: 0, search: '', onlyImage: false, onlyTags: false, labelFilter: '' };

  const byBucket = {};
  for (const b of BUCKETS) byBucket[b] = ALL_POSTS.filter(TAB_FILTERS[b]);
  const postById = new Map(ALL_POSTS.map(p => [p.id, p]));

  function effectiveLabel(p) { return labels[p.id] || p.suggested; }
  function isConfirmed(p) { return Object.prototype.hasOwnProperty.call(labels, p.id); }
  function saveLabels() { localStorage.setItem(LS_KEY, JSON.stringify(labels)); }

  function filtered() {
    let list = byBucket[state.bucket];
    if (state.search) {
      const q = state.search.toLowerCase();
      list = list.filter(p => (p.subject || '').toLowerCase().includes(q) || (p.body || '').toLowerCase().includes(q));
    }
    if (state.onlyImage) list = list.filter(p => p.image);
    if (state.onlyTags) list = list.filter(p => p.tags && p.tags.length);
    if (state.labelFilter === 'unconfirmed') list = list.filter(p => !isConfirmed(p));
    else if (state.labelFilter) list = list.filter(p => effectiveLabel(p) === state.labelFilter);
    return list;
  }

  function renderTabs() {
    const tabs = document.getElementById('tabs');
    tabs.innerHTML = '';
    for (const b of BUCKETS) {
      const btn = document.createElement('button');
      btn.textContent = BUCKET_META[b].label + ' (' + byBucket[b].length + ')';
      btn.className = b === state.bucket ? 'active' : '';
      btn.onclick = () => { state.bucket = b; state.page = 0; render(); };
      tabs.appendChild(btn);
    }
    document.getElementById('tabhint').textContent = BUCKET_META[state.bucket].hint;
  }

  function renderStatbar() {
    const bar = document.getElementById('statbar');
    bar.innerHTML = BUCKETS.map(b => {
      const total = byBucket[b].length;
      const withImg = byBucket[b].filter(p => p.image).length;
      const withTag = byBucket[b].filter(p => p.tags && p.tags.length).length;
      return `<span><b>${total}</b> ${BUCKET_META[b].label} <small>(${withImg} img · ${withTag} tagged)</small></span>`;
    }).join('');
  }

  function renderLabelTally() {
    const confirmedCount = Object.keys(labels).length;
    const counts = { real: 0, graph: 0, noise: 0, unsure: 0 };
    for (const p of ALL_POSTS) { const l = effectiveLabel(p); if (counts.hasOwnProperty(l)) counts[l]++; }
    document.getElementById('labelTally').textContent =
      `${confirmedCount} confirmed of ${ALL_POSTS.length} — effective totals: ✅${counts.real} 📊${counts.graph} 💬${counts.noise} ❓${counts.unsure}`;
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function threadHtml(p) {
    const msgs = THREADS[p.thread_group];
    if (!msgs || msgs.length <= 1) return '';
    const rows = msgs.map(m => `
      <div class="thread-msg ${m.is_hadar ? 'is-hadar' : ''} ${m.id === p.id ? 'is-current' : ''}">
        <div class="tm-meta"><span>${m.is_hadar ? 'Hadar' : 'Other user'}</span><span>${m.date}</span></div>
        ${m.subject ? `<div class="tm-subject" dir="auto">${escapeHtml(m.subject)}</div>` : ''}
        <div class="tm-body" dir="auto">${escapeHtml(m.body) || '<i style="opacity:.5">(empty)</i>'}</div>
      </div>`).join('');
    return `
      <details class="thread-toggle">
        <summary>🧵 Show full thread (${msgs.length} messages, all participants)</summary>
        <div class="thread-list">${rows}</div>
      </details>`;
  }

  function cardHtml(p) {
    const confirmed = isConfirmed(p);
    const active = effectiveLabel(p);
    const labelBtn = (l, icon, text) => {
      let cls = '';
      if (active === l) cls = confirmed ? 'confirmed' : 'suggested';
      return `<button data-l="${l}" class="${cls}" onclick="window.__setLabel('${p.id}','${l}')">${icon} ${text}</button>`;
    };
    const tagsHtml = (p.tags && p.tags.length)
      ? `<div class="tags">${p.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</div>` : '';
    const rootHtml = (p.level > 1 && p.root_subject)
      ? `<div class="card-root">↩ replying in thread: “${escapeHtml(p.root_subject)}”</div>` : '';
    const imgHtml = p.image ? `<img src="${p.image}" loading="lazy" alt="attached image">` : '';
    const bucketBadge = state.bucket === 'graphs'
      ? `<span>${BUCKET_META[p.bucket] ? BUCKET_META[p.bucket].label : p.bucket}</span>` : '';
    return `
      <div class="card ${confirmed ? 'confirmed' : 'suggested-only'}" id="card-${p.id}">
        <div class="card-meta"><span>${p.date}</span>${bucketBadge}<span>level ${p.level} · id ${p.id}</span></div>
        ${p.subject ? `<div class="card-subject" dir="auto">${escapeHtml(p.subject)}</div>` : ''}
        ${rootHtml}
        ${tagsHtml}
        ${imgHtml}
        <div class="card-body" dir="auto">${escapeHtml(p.body) || '<i style="opacity:.5">(empty body)</i>'}</div>
        ${threadHtml(p)}
        <div class="labelrow">
          ${labelBtn('real', '✅', 'Real action')}
          ${labelBtn('graph', '📊', 'Graph-only')}
          ${labelBtn('noise', '💬', "Doesn't matter")}
          ${labelBtn('unsure', '❓', 'Unsure')}
          <span class="suggest-note">${confirmed ? '(confirmed)' : '(suggested — click to confirm/correct)'}</span>
        </div>
      </div>`;
  }

  window.__setLabel = function (id, label) {
    // Clicking the already-confirmed value un-confirms it back to just the suggestion.
    if (labels[id] === label) delete labels[id]; else labels[id] = label;
    saveLabels();
    render();
  };

  let currentPageItems = [];

  function render() {
    renderTabs();
    renderStatbar();
    renderLabelTally();
    const list = filtered();
    const totalPages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    if (state.page >= totalPages) state.page = totalPages - 1;
    if (state.page < 0) state.page = 0;
    const start = state.page * PAGE_SIZE;
    currentPageItems = list.slice(start, start + PAGE_SIZE);
    const cardsEl = document.getElementById('cards');
    cardsEl.innerHTML = currentPageItems.length
      ? currentPageItems.map(cardHtml).join('')
      : '<div class="empty">No posts match the current filters.</div>';
    document.getElementById('pageInfo').textContent =
      `Page ${state.page + 1} / ${totalPages} — showing ${currentPageItems.length} of ${list.length} (bucket total ${byBucket[state.bucket].length})`;
  }

  document.getElementById('search').addEventListener('input', e => { state.search = e.target.value; state.page = 0; render(); });
  document.getElementById('fImage').addEventListener('change', e => { state.onlyImage = e.target.checked; state.page = 0; render(); });
  document.getElementById('fTags').addEventListener('change', e => { state.onlyTags = e.target.checked; state.page = 0; render(); });
  document.getElementById('fLabel').addEventListener('change', e => { state.labelFilter = e.target.value; state.page = 0; render(); });
  document.getElementById('prevPage').addEventListener('click', () => { state.page--; render(); window.scrollTo(0,0); });
  document.getElementById('nextPage').addEventListener('click', () => { state.page++; render(); window.scrollTo(0,0); });

  document.getElementById('acceptPageBtn').addEventListener('click', () => {
    for (const p of currentPageItems) if (!isConfirmed(p)) labels[p.id] = p.suggested;
    saveLabels();
    render();
  });

  document.getElementById('exportBtn').addEventListener('click', async () => {
    // Only the deltas you actually confirmed/corrected — Claude already has
    // the heuristic "suggested" value for everything else, so re-sending
    // all 4k+ rows would just be a huge, unreadable paste for no new info.
    const rows = Object.entries(labels).map(([id, label]) => {
      const p = postById.get(id);
      return {
        id, label,
        was_suggested: p ? p.suggested : null,
        corrected: p ? p.suggested !== label : null,
        bucket: p ? p.bucket : null,
        subject: p ? p.subject : null,
        date: p ? p.date : null,
      };
    });
    const payload = JSON.stringify({
      exported_at: new Date().toISOString(),
      total_posts: ALL_POSTS.length,
      confirmed_count: rows.length,
      corrections: rows.filter(r => r.corrected).length,
      labels: rows,
    });
    try {
      await navigator.clipboard.writeText(payload);
      alert('Copied ' + rows.length + ' confirmed labels to clipboard — paste them back into the chat.');
    } catch (e) {
      const w = window.open('', '_blank');
      w.document.write('<pre>' + payload.replace(/</g, '&lt;') + '</pre>');
    }
  });

  document.getElementById('clearBtn').addEventListener('click', () => {
    if (confirm('Clear all ' + Object.keys(labels).length + ' confirmed labels (suggestions stay)? This cannot be undone.')) {
      labels = {}; saveLabels(); render();
    }
  });

  render();
})();
</script>
"""

html = html.replace("__DATA_JSON__", data_json).replace("__BUCKET_META__", json.dumps(BUCKET_META))

with open(OUT_PATH, "w", encoding="utf-8") as fh:
    fh.write(html)

print(f"wrote {OUT_PATH} ({len(html)/1024/1024:.1f} MB)")
