// Idle Hours curator — vanilla JS, no build step.
// Every fetch is relative so we inherit the page's origin; token auth lives
// entirely on the server side and is only required for LAN binds (see README).

const $ = (id) => document.getElementById(id);

// Token storage. Loopback binds need no token (server ignores the header);
// LAN binds reject every POST — and every JSON GET (#233) — with 401 unless
// `X-Idle-Hours-Token` matches the configured value. We persist the operator's token in localStorage so a
// page reload doesn't re-prompt, and reactively recover from 401 by asking
// the operator to paste the current token. No token is ever embedded in
// the served HTML — that would leak it into shoulder-surf and HTTP caches.
const TOKEN_KEY = "idle-hours.web.token";
const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
};
const setToken = (value) => {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* localStorage may be disabled; degrade silently */ }
};

const log = (msg, cls = "") => {
  const el = $("action-log");
  if (!el) return;
  const line = document.createElement("div");
  line.textContent = `${new Date().toLocaleTimeString()}  ${msg}`;
  if (cls) line.className = cls;
  el.prepend(line);
  while (el.children.length > 8) el.removeChild(el.lastChild);
};

// One token prompt per burst of concurrent 401s. `inFlightRequests` is what
// distinguishes "five siblings from the same page load" from "the operator
// clicked something a minute later": a jsonFetch that starts while nothing
// else is in flight begins a new burst and clears the memo, so a prompt the
// operator cancelled does not suppress every later attempt for the lifetime
// of the page.
let tokenPromptAttempt = null;
let inFlightRequests = 0;

async function jsonFetch(url, opts = {}, retryAfterAuth = true) {
  if (inFlightRequests === 0) tokenPromptAttempt = null;
  inFlightRequests += 1;
  try {
    return await jsonFetchInner(url, opts, retryAfterAuth);
  } finally {
    inFlightRequests -= 1;
  }
}

async function jsonFetchInner(url, opts = {}, retryAfterAuth = true) {
  const headers = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers["X-Idle-Hours-Token"] = token;
  // Remember which token this request used, so a 401 handler can tell "nobody
  // has a working token yet" from "a sibling request already fixed it".
  const resp = await fetch(url, { ...opts, headers });
  const text = await resp.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { error: text }; }
  }
  // 401 recovery: prompt for the token, store it, and retry once. Loopback
  // binds never 401 (server ignores tokens), so this only fires on LAN
  // deployments where the operator must supply the configured value.
  if (resp.status === 401 && retryAfterAuth) {
    const entered = promptForToken(token);
    if (entered) {
      return jsonFetchInner(url, opts, false);
    }
  }
  return { status: resp.status, ok: resp.ok, data };
}

function promptForToken(staleToken) {
  // Browser prompt is intentionally minimal — operators don't need a fancy
  // modal for a one-time token paste. The README's LAN deploy section
  // documents that they'll be asked. Returning the trimmed value (or "")
  // lets the caller decide whether to retry the failed request.
  //
  // `staleToken` is the value the caller's request actually failed with. If
  // storage now holds something different, another concurrent 401 handler has
  // already prompted and stored a fresh token, so we adopt it instead of
  // asking again. Without this, `refreshAll()`'s five parallel GETs plus the
  // wizard's /api/setup each raised their own dialog — six stacked prompts on
  // a single first page load, once GETs became token-gated (#233).
  const current = getToken();
  if (current && current !== staleToken) return current;
  // Storage being unchanged is NOT proof that nobody has asked: if the
  // operator cancelled the dialog or submitted an empty value there is
  // nothing to store, and every sibling handler would prompt in turn —
  // stacking six dialogs precisely when the operator does not have the token
  // to hand. Remember the attempt itself, not just its stored outcome.
  if (tokenPromptAttempt && tokenPromptAttempt.stale === staleToken) {
    return tokenPromptAttempt.value;
  }
  const value = window.prompt(
    "This Idle Hours instance requires a token.\n" +
    "Paste the contents of --web-token-file:",
    "",
  );
  const trimmed = value == null ? "" : value.trim();
  tokenPromptAttempt = { stale: staleToken, value: trimmed };
  if (trimmed) setToken(trimmed);
  return trimmed;
}

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Corpus row identity line, shared verbatim by the bucket inspector and the
// search results. Factored out because it was duplicated byte-for-byte in both
// renderers and both copies were the only unescaped interpolations in the file.
//
// These three fields are numeric in every corpus the pipeline produces — the
// miner only ever sets source_id to a Gutenberg ID or null, and the curator
// API range-checks quality_score to an int in [0, 100]. But "everything from
// the corpus is escaped before it reaches innerHTML" is a far cheaper
// invariant to audit than "everything except the three fields we reasoned are
// always numeric", and a hand-edited or externally-merged JSONL is a supported
// input to this UI. escapeHtml stringifies, so the ?? fallbacks pass through.
const rowIdLine = (row) =>
  `source ${escapeHtml(row.source_id ?? "?")} · line ${escapeHtml(row.line_number ?? "?")}`
  + ` · q=${escapeHtml(row.quality_score ?? "?")}`;

const fmtMs = (v) => (v == null ? "—" : `${v} ms`);

// ------- Tab nav ------------------------------------------------------------

function wireTabs() {
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((t) => {
    t.addEventListener("click", () => activateTab(t.dataset.tab));
  });
  // Default: open the tab in the URL hash if it exists, otherwise "now".
  const initial = (location.hash || "#now").slice(1);
  activateTab(["now", "curate", "coverage", "activity"].includes(initial) ? initial : "now");
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t.dataset.tab === name;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.hidden = p.id !== `tab-${name}`;
  });
  if (location.hash !== `#${name}`) {
    history.replaceState(null, "", `#${name}`);
  }
  // Lazy-loads on first activation: search & content overrides aren't fetched
  // on initial page load to keep first paint snappy.
  if (name === "curate" && !state.contentOverridesLoaded) {
    loadContentOverrides();
    state.contentOverridesLoaded = true;
  }
  if (name === "coverage" && !state.gapsLoaded) {
    refreshGaps();
    state.gapsLoaded = true;
  }
  if (name === "now" && !state.themePreviewLoaded) {
    refreshThemePreview();
    state.themePreviewLoaded = true;
  }
}

// Module-level state. Tab activation tracks which sections have ever been
// loaded so a tab switch doesn't re-fetch the same data on every flip.
const state = {
  contentOverridesLoaded: false,
  gapsLoaded: false,
  themePreviewLoaded: false,
  currentQuoteId: null,  // [source_id, line_number] for the ban button
  themes: [],            // populated by /api/themes
};

// ------- Now Showing ---------------------------------------------------------

async function refreshCurrent() {
  const { ok, data } = await jsonFetch("/api/current");
  if (!ok || !data) return;
  $("clock").textContent = data.time || "--:--";
  $("bucket").textContent = data.bucket || "--";
  $("theme").textContent = data.theme || "--";
  $("mode").textContent = data.mode || "--";
  $("quote").textContent = data.display_quote || "—";
  const src = data.source_id ? `source ${data.source_id}` : "no source";
  const line = data.line_number != null ? ` line ${data.line_number}` : "";
  $("attribution").textContent = `${src}${line}`;
  $("matched").textContent = data.matched_text ? `matched: ${data.matched_text}` : "";
  $("current-png").src = `/current.png?t=${Date.now()}`;
  // Track identity for the ban button. Disabled when there's no source/line —
  // (e.g. cold start before first render).
  state.currentQuoteId = data.source_id != null && data.line_number != null
    ? [String(data.source_id), data.line_number]
    : null;
  const banBtn = $("ban-current");
  if (banBtn) banBtn.disabled = state.currentQuoteId == null;
}

// ------- Telemetry -----------------------------------------------------------

async function refreshTelemetry() {
  const hours = 24;
  $("telemetry-hours").textContent = hours;
  const { ok, data } = await jsonFetch(`/api/telemetry?hours=${hours}`);
  if (!ok || !data) return;
  $("t-renders").textContent = data.render_count ?? "—";
  $("t-errors").textContent = data.error_count ?? "—";
  $("t-render-p50").textContent = fmtMs(data.render_p50_ms);
  $("t-render-p95").textContent = fmtMs(data.render_p95_ms);
  $("t-display-p50").textContent = fmtMs(data.display_p50_ms);
  $("t-display-p95").textContent = fmtMs(data.display_p95_ms);
  $("t-last-error").textContent = data.last_error ? `last error: ${data.last_error}` : "";
}

// ------- Coverage grid -------------------------------------------------------

const STATES = [
  "exact", "five_past", "ten_past", "quarter_past", "twenty_past",
  "twenty_five_past", "half_past", "twenty_five_to", "twenty_to",
  "quarter_to", "ten_to", "five_to",
];

async function refreshCoverage() {
  const { ok, data } = await jsonFetch("/api/coverage");
  if (!ok || !data) return;
  const grid = $("coverage-grid");
  grid.innerHTML = "";
  const counts = data.bucket_counts || {};
  for (let h = 1; h <= 12; h++) {
    for (const s of STATES) {
      const bucket = `h${h}_${s}`;
      const n = counts[bucket] || 0;
      const cell = document.createElement("div");
      cell.className = `coverage-cell ${bucketClass(n)}`;
      cell.textContent = n;
      cell.title = `${bucket}: ${n} candidate${n === 1 ? "" : "s"}`;
      cell.onclick = () => {
        $("inspector-bucket").value = bucket;
        activateTab("curate");
        $("inspector-form").dispatchEvent(new Event("submit"));
      };
      grid.appendChild(cell);
    }
  }
}

function bucketClass(n) {
  if (n === 0) return "zero";
  if (n < 3) return "low";
  if (n < 10) return "mid";
  return "high";
}

// ------- Bucket gaps --------------------------------------------------------

async function refreshGaps() {
  const threshold = parseInt($("gap-threshold").value, 10) || 0;
  const results = $("gap-results");
  results.textContent = "Loading…";
  const { ok, data } = await jsonFetch(`/api/gaps?threshold=${threshold}`);
  if (!ok) {
    results.textContent = `Error: ${data?.error || "?"}`;
    return;
  }
  const buckets = data.buckets || [];
  if (!buckets.length) {
    results.textContent = `No buckets at or below ${threshold} candidate${threshold === 1 ? "" : "s"}. ✨`;
    return;
  }
  results.innerHTML = "";
  for (const gap of buckets) {
    const card = document.createElement("div");
    card.className = "gap-row";
    const phrases = (gap.phrases || []).map(escapeHtml).map(p => `<code>${p}</code>`).join(" · ");
    card.innerHTML = `
      <div class="gap-head">
        <strong>${escapeHtml(gap.bucket)}</strong>
        <span class="gap-count">${gap.count} row${gap.count === 1 ? "" : "s"}</span>
      </div>
      <div class="gap-phrases">${phrases || "<em>no template</em>"}</div>
    `;
    card.querySelector("strong").style.cursor = "pointer";
    card.querySelector("strong").onclick = () => {
      $("inspector-bucket").value = gap.bucket;
      activateTab("curate");
      $("inspector-form").dispatchEvent(new Event("submit"));
    };
    results.appendChild(card);
  }
}

// ------- Bucket inspector ----------------------------------------------------

async function inspectBucket(event) {
  event.preventDefault();
  const bucket = $("inspector-bucket").value.trim();
  const time = $("inspector-time").value.trim();
  const results = $("inspector-results");
  if (!bucket) {
    results.textContent = "Enter a bucket name like h3_half_past.";
    return;
  }
  results.textContent = "Loading…";
  const query = time ? `?time=${encodeURIComponent(time)}&top=15` : "?top=15";
  const { ok, data } = await jsonFetch(`/api/bucket/${encodeURIComponent(bucket)}${query}`);
  if (!ok) {
    results.textContent = `Error: ${data?.error || "request failed"}`;
    return;
  }
  results.innerHTML = "";
  const list = data.candidates || [];
  if (!list.length) {
    results.textContent = "No candidates in this bucket.";
    return;
  }
  list.forEach((entry, idx) => {
    results.appendChild(renderCandidate(entry, idx));
  });
}

function renderCandidate(entry, idx) {
  const row = entry.row || {};
  const score = entry.score || {};
  const el = document.createElement("div");
  el.className = `candidate${entry.is_winner ? " winner" : ""}`;
  const title = row.title ? `${row.title}${row.author ? " · " + row.author : ""}` : (row.author || "—");
  const key = row.source_id != null && row.line_number != null
    ? `${row.source_id}:${row.line_number}` : "";
  el.innerHTML = `
    <div class="candidate-head">
      <strong>#${idx + 1} ${entry.is_winner ? "★ winner" : ""}</strong>
      <span>${rowIdLine(row)}</span>
    </div>
    <div class="candidate-quote">${escapeHtml(row.display_quote || "—")}</div>
    <div class="candidate-meta">${escapeHtml(title)}</div>
    <div class="candidate-score"></div>
    <div class="candidate-actions">
      ${key ? `<button class="btn btn-small btn-danger" data-ban-key="${escapeHtml(key)}">Ban this quote</button>` : ""}
    </div>
  `;
  const scoreEl = el.querySelector(".candidate-score");
  for (const [k, v] of Object.entries(score)) {
    const span = document.createElement("span");
    span.textContent = `${k}: ${v}`;
    if (v && v !== 0) span.classList.add("nonzero");
    scoreEl.appendChild(span);
  }
  const banBtn = el.querySelector("[data-ban-key]");
  if (banBtn) banBtn.addEventListener("click", () => banQuoteKey(banBtn.dataset.banKey));
  return el;
}

// ------- Search -------------------------------------------------------------

async function runSearch(event) {
  event.preventDefault();
  const params = new URLSearchParams();
  const q = $("search-q").value.trim();
  const author = $("search-author").value.trim();
  const title = $("search-title").value.trim();
  const bucket = $("search-bucket").value.trim();
  if (q) params.set("q", q);
  if (author) params.set("author", author);
  if (title) params.set("title", title);
  if (bucket) params.set("bucket", bucket);
  params.set("limit", "50");
  const results = $("search-results");
  if (!params.toString()) {
    results.textContent = "Enter at least one filter.";
    return;
  }
  results.textContent = "Searching…";
  const { ok, data } = await jsonFetch(`/api/search?${params.toString()}`);
  if (!ok) {
    results.textContent = `Error: ${data?.error || "?"}`;
    return;
  }
  const rows = data.results || [];
  if (!rows.length) {
    results.textContent = `No matches (scanned ${data.scanned ?? "?"} rows).`;
    return;
  }
  results.innerHTML = `<div class="search-summary">${rows.length} of ${data.scanned} scanned · showing first ${rows.length}</div>`;
  for (const row of rows) {
    const el = document.createElement("div");
    el.className = "candidate";
    const title = row.title ? `${row.title}${row.author ? " · " + row.author : ""}` : (row.author || "—");
    const key = row.source_id != null && row.line_number != null
      ? `${row.source_id}:${row.line_number}` : "";
    el.innerHTML = `
      <div class="candidate-head">
        <strong>${escapeHtml(row.fuzzy_bucket || row.normalized_time || "—")}</strong>
        <span>${rowIdLine(row)}</span>
      </div>
      <div class="candidate-quote">${escapeHtml(row.display_quote || "—")}</div>
      <div class="candidate-meta">${escapeHtml(title)}</div>
      <div class="candidate-actions">
        ${key ? `<button class="btn btn-small btn-danger" data-ban-key="${escapeHtml(key)}">Ban this quote</button>` : ""}
      </div>
    `;
    const banBtn = el.querySelector("[data-ban-key]");
    if (banBtn) banBtn.addEventListener("click", () => banQuoteKey(banBtn.dataset.banKey));
    results.appendChild(el);
  }
}

// ------- Theme preview grid -------------------------------------------------

async function refreshThemePreview() {
  const grid = $("theme-preview-grid");
  if (!grid) return;
  // Make sure /api/themes has populated state.themes; if not, fetch now.
  if (!state.themes.length) {
    const { ok, data } = await jsonFetch("/api/themes");
    if (ok && data) state.themes = data.themes || [];
  }
  grid.innerHTML = "";
  for (const theme of state.themes) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "theme-thumb";
    cell.title = `Apply ${theme}`;
    // Cache-bust per page-load — once is enough; server returns no-store.
    const url = `/api/preview?theme=${encodeURIComponent(theme)}&width=320&height=192&t=${Date.now()}`;
    cell.innerHTML = `
      <img alt="${escapeHtml(theme)} preview" loading="lazy" src="${url}" />
      <span>${escapeHtml(theme)}</span>
    `;
    cell.onclick = () => fireAction("theme", { theme });
    grid.appendChild(cell);
  }
}

// ------- Controls (mirror buttons) ------------------------------------------

async function fireAction(action, body = {}) {
  log(`→ ${action}${body.theme ? ` (${body.theme})` : ""}`);
  const { status, ok, data } = await jsonFetch(`/api/action/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (status === 409) {
    log(`${action}: busy (render in flight)`, "warn");
    return;
  }
  if (!ok) {
    log(`${action}: error ${status} ${data?.error || ""}`, "err");
    return;
  }
  log(`${action}: ok${data?.theme ? ` → ${data.theme}` : ""}`, "ok");
  await Promise.all([refreshCurrent(), refreshThemes()]);
}

function wireControls() {
  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => fireAction(btn.dataset.action));
  });
  const apply = $("theme-apply");
  if (apply) {
    apply.addEventListener("click", () => {
      const target = $("theme-select").value;
      if (!target) return;
      fireAction("theme", { theme: target });
    });
  }
  const banBtn = $("ban-current");
  if (banBtn) {
    banBtn.addEventListener("click", () => {
      if (!state.currentQuoteId) return;
      const [src, line] = state.currentQuoteId;
      banQuoteKey(`${src}:${line}`);
    });
  }
}

// ------- Theme picker --------------------------------------------------------

async function refreshThemes() {
  const select = $("theme-select");
  if (!select) return;
  const { ok, data } = await jsonFetch("/api/themes");
  if (!ok || !data) return;
  state.themes = data.themes || [];
  const isFocused = document.activeElement === select;
  if (!isFocused) {
    const prev = select.value;
    const current = data.manual_theme || data.effective;
    select.innerHTML = "";
    for (const name of data.themes || []) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name + (name === data.effective ? " (active)" : "");
      if (name === (prev || current)) opt.selected = true;
      select.appendChild(opt);
    }
  }
  const pill = $("theme-current");
  if (pill) {
    if (data.manual_theme) {
      pill.textContent = `manual: ${data.manual_theme}`;
    } else if (data.theme_arg === "auto") {
      pill.textContent = `auto: ${data.effective}`;
    } else {
      pill.textContent = `fixed: ${data.effective}`;
    }
  }
}

// ------- Selection overrides editor -----------------------------------------

async function loadOverrides() {
  const { ok, data } = await jsonFetch("/api/overrides");
  if (ok) {
    $("overrides-text").value = JSON.stringify(data, null, 2);
    setStatus("overrides-status", "loaded from disk", "ok");
  } else {
    setStatus("overrides-status", `load failed: ${data?.error || "?"}`, "err");
  }
}

async function saveOverrides() {
  let payload;
  try {
    payload = JSON.parse($("overrides-text").value);
  } catch (err) {
    setStatus("overrides-status", `invalid JSON: ${err.message}`, "err");
    return;
  }
  const { ok, status, data } = await jsonFetch("/api/overrides", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (ok) setStatus("overrides-status", `saved to ${data.path}`, "ok");
  else setStatus("overrides-status", `save failed (${status}): ${data?.error || "?"}`, "err");
}

// ------- Content overrides editor -------------------------------------------

async function loadContentOverrides() {
  const { ok, data } = await jsonFetch("/api/content-overrides");
  if (ok) {
    $("content-overrides-text").value = JSON.stringify(data, null, 2);
    setStatus("content-overrides-status", `loaded ${Object.keys(data).length} entries`, "ok");
  } else {
    setStatus("content-overrides-status", `load failed: ${data?.error || "?"}`, "err");
  }
}

async function saveContentOverrides() {
  let payload;
  try {
    payload = JSON.parse($("content-overrides-text").value);
  } catch (err) {
    setStatus("content-overrides-status", `invalid JSON: ${err.message}`, "err");
    return;
  }
  const { ok, status, data } = await jsonFetch("/api/content-overrides", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (ok) setStatus("content-overrides-status", `saved ${data.entries} entries to ${data.path} — click "Bake now" to make them visible`, "ok");
  else setStatus("content-overrides-status", `save failed (${status}): ${data?.error || "?"}`, "err");
}

// ------- Bake ---------------------------------------------------------------

async function bakeNow() {
  const btn = $("bake-now");
  btn.disabled = true;
  setStatus("bake-status", "Baking…", "");
  // Content-Type is required on every POST, body or not (#233) — a bodyless
  // POST with no Content-Type is a CORS simple request and would let any page
  // the operator has open trigger a bake.
  const { ok, status, data } = await jsonFetch("/api/bake", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  btn.disabled = false;
  if (status === 409) {
    setStatus("bake-status", "busy: render in flight, try again in a moment", "warn");
    return;
  }
  if (!ok) {
    setStatus("bake-status", `bake failed (${status}): ${data?.error || "?"}`, "err");
    return;
  }
  const drops = data.drops || {};
  setStatus(
    "bake-status",
    `baked ${data.kept} rows from ${data.input} input (overrides applied: ${data.applied_overrides}, ` +
    `dropped ${drops.no_bucket} no-bucket / ${drops.no_display_quote} no-quote / ${drops.low_quality} low-quality). ` +
    `Next tick will pick up the new database.`,
    "ok",
  );
  // Refresh the now-showing block so the operator sees the updated pick.
  setTimeout(refreshCurrent, 1500);
}

// ------- Per-row ban --------------------------------------------------------

async function banQuoteKey(key) {
  if (!key) return;
  if (!confirm(`Add ${key} to ban_quote_keys? The picker will skip this exact quote forever.`)) return;
  // Read-modify-write the selection_overrides sidecar through the existing
  // POST endpoint. Server-side validation will reject an already-banned dup
  // with a clean error if we hit it, but the de-dup happens here too.
  const { ok: okGet, data: current } = await jsonFetch("/api/overrides");
  if (!okGet) {
    alert(`Could not load overrides: ${current?.error || "?"}`);
    return;
  }
  const next = {
    ban_source_ids: current.ban_source_ids || [],
    boost_source_ids: current.boost_source_ids || [],
    preferred_buckets: current.preferred_buckets || {},
    ban_quote_keys: Array.from(new Set([...(current.ban_quote_keys || []), key])),
  };
  const { ok, status, data } = await jsonFetch("/api/overrides", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(next),
  });
  if (!ok) {
    alert(`Save failed (${status}): ${data?.error || "?"}`);
    return;
  }
  log(`banned ${key}`, "ok");
  // Re-render so the panel jumps to a new pick that doesn't include the banned row.
  await fireAction("rerender");
  await loadOverrides();
}

// ------- Utils --------------------------------------------------------------

function setStatus(id, msg, cls) {
  const el = $(id);
  if (!el) return;
  el.textContent = msg;
  el.className = `override-status ${cls || ""}`;
}

// ------- History ------------------------------------------------------------

async function refreshHistory() {
  const { ok, data } = await jsonFetch("/api/history?limit=30");
  if (!ok || !data) return;
  const list = $("history-list");
  list.innerHTML = "";
  for (const entry of data.entries || []) {
    const li = document.createElement("li");
    li.className = "history-entry";
    // The server joins each ledger entry against the corpus, but a row can
    // be gone (dropped by a re-bake, or removed outright). Fall back to the
    // bare IDs in that case rather than rendering an empty line — the ledger
    // is a record of what was displayed, so the entry still belongs here.
    const key = entry.source_id != null && entry.line_number != null
      ? `${entry.source_id}:${entry.line_number}` : "";
    const attribution = entry.title
      ? `${entry.title}${entry.author ? " · " + entry.author : ""}`
      : (entry.author || "");
    li.innerHTML = `
      <div class="history-ts">${escapeHtml(entry.ts || "?")}</div>
      ${entry.display_quote
        ? `<div class="history-quote">${escapeHtml(entry.display_quote)}</div>`
        : `<div class="history-quote history-missing">(quote no longer in corpus)</div>`}
      <div class="history-meta">
        ${attribution ? `<span>${escapeHtml(attribution)}</span>` : ""}
        <span class="history-id">source ${escapeHtml(String(entry.source_id ?? "?"))} · line ${escapeHtml(String(entry.line_number ?? "?"))}</span>
        ${key ? `<button class="btn btn-small btn-danger" data-ban-key="${escapeHtml(key)}">Ban</button>` : ""}
      </div>
    `;
    const banBtn = li.querySelector("[data-ban-key]");
    if (banBtn) {
      banBtn.addEventListener("click", async () => {
        await banQuoteKey(banBtn.dataset.banKey);
        refreshHistory();
      });
    }
    list.appendChild(li);
  }
}

// ------- Wiring -------------------------------------------------------------

// ------- First-run wizard ---------------------------------------------------

async function maybeShowWizard() {
  const { ok, data } = await jsonFetch("/api/setup");
  if (!ok || !data || data.setup_complete) return;
  const overlay = $("setup-wizard");
  if (!overlay) return;
  // Populate the quiet-hours line with whatever the loop is configured to use.
  const quietEl = $("wizard-quiet");
  if (quietEl) {
    if (data.quiet_off) {
      quietEl.textContent = "Quiet hours are disabled (--quiet-off). The clock renders 24/7.";
    } else if (data.quiet_start && data.quiet_end) {
      quietEl.textContent = `Currently configured for ${data.quiet_start}–${data.quiet_end}.`;
    } else {
      quietEl.textContent = "Quiet hours not configured.";
    }
  }
  // Lazy-load the theme grid using /api/preview so the wizard mirrors the
  // Now tab's thumbnail UX (and the operator picks a theme by clicking, not
  // by reading names off a dropdown they haven't learned yet).
  const grid = $("wizard-theme-grid");
  grid.innerHTML = "";
  for (const theme of data.themes || []) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "theme-thumb";
    cell.title = `Use ${theme}`;
    if (theme === (data.manual_theme || data.theme_arg)) cell.classList.add("selected");
    const url = `/api/preview?theme=${encodeURIComponent(theme)}&width=320&height=192&t=${Date.now()}`;
    cell.innerHTML = `
      <img alt="${escapeHtml(theme)} preview" loading="lazy" src="${url}" />
      <span>${escapeHtml(theme)}</span>
    `;
    cell.onclick = () => completeWizard(theme);
    grid.appendChild(cell);
  }
  overlay.hidden = false;
}

async function completeWizard(theme) {
  setStatus("wizard-status", theme ? `Applying ${theme}…` : "Saving…", "");
  const body = theme ? { theme } : {};
  const { ok, status, data } = await jsonFetch("/api/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!ok) {
    setStatus("wizard-status", `Setup save failed (${status}): ${data?.error || "?"}`, "err");
    return;
  }
  // Hide the overlay, refresh the underlying view so the freshly-applied
  // theme is reflected on the Now tab once the operator looks.
  $("setup-wizard").hidden = true;
  await Promise.all([refreshCurrent(), refreshThemes()]);
}

function init() {
  wireTabs();
  wireControls();
  $("inspector-form").addEventListener("submit", inspectBucket);
  $("search-form").addEventListener("submit", runSearch);
  $("overrides-save").addEventListener("click", (e) => { e.preventDefault(); saveOverrides(); });
  $("overrides-reload").addEventListener("click", loadOverrides);
  $("content-overrides-save").addEventListener("click", (e) => { e.preventDefault(); saveContentOverrides(); });
  $("content-overrides-reload").addEventListener("click", loadContentOverrides);
  $("bake-now").addEventListener("click", bakeNow);
  $("gap-refresh").addEventListener("click", refreshGaps);
  const dismiss = $("wizard-dismiss");
  if (dismiss) dismiss.addEventListener("click", () => completeWizard(null));

  refreshAll();
  // Wizard check runs after refreshAll so the underlying UI is populated
  // when the operator dismisses the overlay.
  maybeShowWizard();
  setInterval(refreshCurrent, 30000);
  setInterval(refreshTelemetry, 30000);
  setInterval(refreshHistory, 60000);
}

async function refreshAll() {
  await Promise.all([
    refreshCurrent(),
    refreshTelemetry(),
    refreshCoverage(),
    refreshHistory(),
    refreshThemes(),
  ]);
  await loadOverrides();
}

document.addEventListener("DOMContentLoaded", init);
