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

// The one place a request leaves the page with credentials: attaches the
// token header and handles 401 recovery, for JSON and image bodies alike.
async function authFetch(url, opts = {}, retryAfterAuth = true) {
  const headers = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers["X-Idle-Hours-Token"] = token;
  // Remember which token this request used, so a 401 handler can tell "nobody
  // has a working token yet" from "a sibling request already fixed it".
  const resp = await fetch(url, { ...opts, headers });
  // 401 recovery: prompt for the token, store it, and retry once. Loopback
  // binds never 401 (server ignores tokens), so this only fires on LAN
  // deployments where the operator must supply the configured value.
  if (resp.status === 401 && retryAfterAuth) {
    const entered = promptForToken(token);
    if (entered) {
      return authFetch(url, opts, false);
    }
  }
  return resp;
}

async function jsonFetchInner(url, opts = {}, retryAfterAuth = true) {
  const resp = await authFetch(url, opts, retryAfterAuth);
  const text = await resp.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { error: text }; }
  }
  // `headers` rides along for the overrides editor's ETag (#289); fetch stubs
  // that don't model headers leave it undefined, and callers tolerate that.
  return { status: resp.status, ok: resp.ok, data, headers: resp.headers };
}

// Polled GETs used to drop a failure on the floor (`if (!ok) return;`), so a
// dead endpoint left the page silently showing stale data. Report it once per
// burst — the first failure of a run logs, repeats stay quiet, and the next
// success logs a recovery — so a 30 s poll against a sick appliance cannot
// flood the action log (#290).
const pollFailures = new Set();

async function pollFetch(name, url) {
  let res;
  try {
    res = await jsonFetch(url);
  } catch (err) {
    res = { ok: false, status: 0, data: { error: String(err) } };
  }
  if (!res.ok || !res.data) {
    if (!pollFailures.has(name)) {
      pollFailures.add(name);
      const why = res.status ? `HTTP ${res.status}` : "network error";
      log(`${name} refresh failed (${why}): ${res.data?.error || "?"}`, "err");
    }
    return null;
  }
  if (pollFailures.delete(name)) log(`${name} refresh recovered`, "ok");
  return res.data;
}

// ------- Token-gated images ------------------------------------------------
// `/current.png` and `/api/preview` are behind the token like every other
// read (#286), and an <img src> cannot attach a header. So the bytes are
// fetched with the header and handed to the tag as an object URL. The previous
// object URL for a tag is revoked when it is replaced, so a page left open
// polling /current.png every 30 s does not leak a frame per poll.
const objectUrls = new Map();
// Latest load started per <img>. A reload that starts while an earlier one is
// still in flight must win, and a tile released mid-fetch must not have an
// object URL minted for it afterwards — that URL would never be revoked.
const imageLoadSeq = new WeakMap();
// Pending "load when visible" observers, so a reload replaces rather than
// stacks them and a released tile stops waiting to be scrolled into view.
const imageObservers = new Map();

async function loadImage(img, url) {
  const seq = (imageLoadSeq.get(img) || 0) + 1;
  imageLoadSeq.set(img, seq);
  if (inFlightRequests === 0) tokenPromptAttempt = null;
  inFlightRequests += 1;
  let resp;
  try {
    resp = await authFetch(url);
  } catch (err) {
    log(`image ${url}: ${err}`);
    return false;
  } finally {
    inFlightRequests -= 1;
  }
  if (!resp.ok) {
    log(`image ${url}: HTTP ${resp.status}`);
    return false;
  }
  const blob = await resp.blob();
  if (imageLoadSeq.get(img) !== seq) return false; // superseded or released
  const objectUrl = URL.createObjectURL(blob);
  const previous = objectUrls.get(img);
  if (previous) URL.revokeObjectURL(previous);
  objectUrls.set(img, objectUrl);
  img.src = objectUrl;
  return true;
}

// Forget an <img> the page is discarding: revoke its object URL (the blob is
// otherwise pinned for the life of the page), drop the Map entry that would
// keep the detached element alive, and cancel any pending or in-flight load.
function releaseImage(img) {
  const url = objectUrls.get(img);
  if (url) URL.revokeObjectURL(url);
  objectUrls.delete(img);
  const observer = imageObservers.get(img);
  if (observer) observer.disconnect();
  imageObservers.delete(img);
  imageLoadSeq.set(img, -1);
}

// Thumbnail grids hold one <img> per theme, and each is a full render on the
// appliance: load a tile only once it scrolls into view (the job the old
// `loading="lazy"` attribute did before the src became a fetched blob).
//
// Calling it again for the same <img> (a reload after the quote changed)
// replaces the pending observer, so an off-screen tile is fetched once, when
// it is finally scrolled to, with the latest URL — not once per quote change.
function loadImageWhenVisible(img, url) {
  const pending = imageObservers.get(img);
  if (pending) pending.disconnect();
  imageObservers.delete(img);
  if (typeof IntersectionObserver === "undefined") {
    loadImage(img, url);
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.disconnect();
      if (imageObservers.get(img) === observer) imageObservers.delete(img);
      loadImage(img, url);
      return;
    }
  }, { rootMargin: "200px" });
  imageObservers.set(img, observer);
  observer.observe(img);
}

// Cache-busted per call; the server answers no-store anyway.
const previewUrl = (theme) =>
  `/api/preview?theme=${encodeURIComponent(theme)}&width=320&height=192&t=${Date.now()}`;

// Returns `{ cell, img }` so callers can keep the <img> for a later reload
// or release without walking the DOM.
function themeThumb(theme, title, onClick) {
  const cell = document.createElement("button");
  cell.type = "button";
  cell.className = "theme-thumb";
  cell.title = title;
  const img = document.createElement("img");
  img.alt = `${theme} preview`;
  const label = document.createElement("span");
  label.textContent = theme;
  cell.appendChild(img);
  cell.appendChild(label);
  cell.onclick = onClick;
  loadImageWhenVisible(img, previewUrl(theme));
  return { cell, img };
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
  if (name === "curate") lazyLoad("contentOverridesLoaded", loadContentOverrides);
  if (name === "coverage") lazyLoad("gapsLoaded", refreshGaps);
  if (name === "now") lazyLoad("themePreviewLoaded", refreshThemePreview);
}

// The "loaded" flag is set only once the loader reports success (#290). It was
// set beside the call, so a tab whose first fetch failed stayed empty until a
// full page reload. A loader already in flight is not started twice, so rapid
// tab flips still cost one request.
function lazyLoad(flag, loader) {
  if (state[flag] || state.lazyInFlight[flag]) return;
  state.lazyInFlight[flag] = true;
  Promise.resolve()
    .then(loader)
    .then((ok) => { if (ok) state[flag] = true; })
    .catch((err) => log(`${flag}: ${err}`, "err"))
    .finally(() => { state.lazyInFlight[flag] = false; });
}

// Module-level state. Tab activation tracks which sections have ever been
// loaded so a tab switch doesn't re-fetch the same data on every flip.
const state = {
  contentOverridesLoaded: false,
  gapsLoaded: false,
  themePreviewLoaded: false,
  lazyInFlight: {},      // lazy loaders currently running, by flag name
  currentQuoteId: null,  // [source_id, line_number] for the ban button
  asleep: false,         // panel shows the sleep frame (from /api/current)
  themes: [],            // populated by /api/themes (the dropdown's list)
  previewTiles: [],      // [{ theme, img }] currently in the Now-tab grid
  wizardTiles: [],       // [{ theme, img }] currently in the wizard grid
  liveTheme: null,       // the theme the panel shows, per the last /api/themes
  previewThemes: [],     // /api/themes preview_themes: the grid's list, no diags
  themeSelectDirty: false, // dropdown holds an unapplied choice that differs from the live theme
  overridesEtag: null,   // ETag the overrides editor was loaded from (#289)
  overridesLoadedText: null, // textarea contents as last loaded/saved — dirty = differs
};

// ------- Now Showing ---------------------------------------------------------

async function refreshCurrent() {
  const data = await pollFetch("current", "/api/current");
  if (!data) return;
  $("clock").textContent = data.time || "--:--";
  $("bucket").textContent = data.bucket || "--";
  $("theme").textContent = data.theme || "--";
  $("mode").textContent = data.mode || "--";
  $("quote").textContent = data.display_quote || "—";
  const src = data.source_id ? `source ${data.source_id}` : "no source";
  const line = data.line_number != null ? ` line ${data.line_number}` : "";
  $("attribution").textContent = `${src}${line}`;
  $("matched").textContent = data.matched_text ? `matched: ${data.matched_text}` : "";
  loadImage($("current-png"), `/current.png?t=${Date.now()}`);
  // Track identity for the ban button. Disabled when there's no source/line —
  // (e.g. cold start before first render).
  const previousId = state.currentQuoteId;
  state.currentQuoteId = data.source_id != null && data.line_number != null
    ? [String(data.source_id), data.line_number]
    : null;
  // The thumbnails render the quote on the panel, so a new quote makes every
  // one of them stale (#290). Only once the grid has loaded — before that the
  // lazy loader will draw it fresh anyway.
  const idKey = (id) => (id ? `${id[0]}:${id[1]}` : "");
  if (previousId && idKey(previousId) !== idKey(state.currentQuoteId) && state.themePreviewLoaded) {
    refreshThemePreview();
  }
  const banBtn = $("ban-current");
  if (banBtn) banBtn.disabled = state.currentQuoteId == null;
  reflectSleep(Boolean(data.asleep));
}

// While the panel shows the sleep frame, skip and un-skip have no quote to
// act on and the server refuses them (409 "asleep"), so the buttons say so
// up front instead of failing on click; button D reads as the wake it is.
function reflectSleep(asleep) {
  state.asleep = asleep;
  for (const id of ["action-skip", "action-unskip"]) {
    const btn = $(id);
    if (!btn) continue;
    btn.disabled = asleep;
    btn.title = asleep ? "The panel is asleep — wake it first (D)" : "";
  }
  const quietBtn = $("action-quiet");
  if (quietBtn) quietBtn.textContent = asleep ? "D · Wake" : "D · Sleep";
}

// ------- Telemetry -----------------------------------------------------------

async function refreshTelemetry() {
  const hours = 24;
  $("telemetry-hours").textContent = hours;
  const data = await pollFetch("telemetry", `/api/telemetry?hours=${hours}`);
  if (!data) return;
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
  const grid = $("coverage-grid");
  if (!grid) return false;
  const data = await pollFetch("coverage", "/api/coverage");
  if (!data) return false;
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
  return true;
}

function bucketClass(n) {
  if (n === 0) return "zero";
  if (n < 3) return "low";
  if (n < 10) return "mid";
  return "high";
}

// ------- Bucket gaps --------------------------------------------------------

async function refreshGaps() {
  const results = $("gap-results");
  if (!results) return false;
  const threshold = parseInt($("gap-threshold")?.value, 10) || 0;
  results.textContent = "Loading…";
  const { ok, data } = await jsonFetch(`/api/gaps?threshold=${threshold}`);
  if (!ok || !data) {
    results.textContent = `Error: ${data?.error || "?"}`;
    return false;
  }
  const buckets = data.buckets || [];
  if (!buckets.length) {
    results.textContent = `No buckets at or below ${threshold} candidate${threshold === 1 ? "" : "s"}. ✨`;
    return true;
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
  return true;
}

// A ban or a bake changes which rows the picker can reach, and coverage is
// computed live from them — so both views go stale the moment either lands.
// The gap finder only refreshes once it has been opened; before that the lazy
// loader draws it fresh (#290).
function refreshCoverageViews() {
  refreshCoverage();
  if (state.gapsLoaded) refreshGaps();
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
  if (!grid) return false;
  // Make sure /api/themes has populated the preview list; if not, fetch now.
  if (!state.previewThemes.length) {
    const { ok, data } = await jsonFetch("/api/themes");
    if (ok && data) rememberThemes(data);
  }
  if (!state.previewThemes.length) return false;
  // Same theme list as the tiles already on screen (the common case: the
  // quote changed): reload those tiles in place. Rebuilding the grid on every
  // quote change used to orphan every thumbnail's object URL (the map is keyed
  // by <img>, and new elements never matched the old keys) and re-render all
  // ~70 previews at once; reloading through the visibility observer fetches
  // only tiles on screen now, the rest when they are scrolled to.
  const themes = state.previewThemes;
  const tiles = state.previewTiles;
  if (tiles.length === themes.length && tiles.every((t, i) => t.theme === themes[i])) {
    for (const tile of tiles) loadImageWhenVisible(tile.img, previewUrl(tile.theme));
    return true;
  }
  for (const tile of tiles) releaseImage(tile.img);
  grid.innerHTML = "";
  state.previewTiles = [];
  for (const theme of themes) {
    const { cell, img } = themeThumb(theme, `Apply ${theme}`, () => fireAction("theme", { theme }));
    state.previewTiles.push({ theme, img });
    grid.appendChild(cell);
  }
  return true;
}

// The dropdown lists every theme (diags included, for an operator who wants
// it); the thumbnail grid and the wizard show only themes to live with (#292).
function rememberThemes(data) {
  state.themes = data.themes || [];
  state.previewThemes = data.preview_themes || state.themes.filter((t) => t !== "diags");
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
    // Two refusals share the status: a render already in flight, and an
    // action that needs a quote while the panel shows the sleep frame.
    if (data?.error === "asleep") {
      log(`${action}: the panel is asleep — wake it first (D)`, "warn");
      await refreshCurrent();
    } else {
      log(`${action}: busy (render in flight)`, "warn");
    }
    return false;
  }
  if (!ok) {
    log(`${action}: error ${status} ${data?.error || ""}`, "err");
    return false;
  }
  log(`${action}: ok${data?.theme ? ` → ${data.theme}` : ""}`, "ok");
  // Any applied theme supersedes a pending dropdown choice, so let the
  // dropdown follow the live theme again (#290).
  if (action === "theme") state.themeSelectDirty = false;
  await Promise.all([refreshCurrent(), refreshThemes()]);
  return true;
}

function wireControls() {
  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => fireAction(btn.dataset.action));
  });
  const select = $("theme-select");
  if (select) {
    // Dirty means "holds a choice other than what the panel shows". Picking
    // the live theme back clears it, so a later live change is followed
    // rather than hidden behind a choice the operator already undid.
    select.addEventListener("change", () => {
      state.themeSelectDirty = select.value !== state.liveTheme;
    });
  }
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
  const data = await pollFetch("themes", "/api/themes");
  if (!data) return;
  rememberThemes(data);
  state.liveTheme = data.manual_theme || data.effective || null;
  const isFocused = document.activeElement === select;
  if (!isFocused) {
    // Follow the live theme unless the operator has picked something they
    // haven't applied yet (#290). `prev || current` used to pin the dropdown
    // to whatever it first showed, so a button-B press or an auto flip never
    // reached it.
    const prev = select.value;
    const current = data.manual_theme || data.effective;
    // A pending choice the live theme has since caught up with is no longer
    // pending; dropping the flag lets the next live change through.
    if (prev === current) state.themeSelectDirty = false;
    const wanted = state.themeSelectDirty && prev ? prev : current;
    select.innerHTML = "";
    for (const name of data.themes || []) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name + (name === data.effective ? " (active)" : "");
      if (name === wanted) opt.selected = true;
      select.appendChild(opt);
    }
    select.value = wanted;
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

// `?envelope=1` returns `{ overrides, etag }`: the tag rides in the body as
// well as the header because a gzip-ing proxy rewrites the header to a weak
// `W/"…"`. An older server ignores the parameter and returns the bare
// document, so fall back to that shape and the header.
async function fetchOverrides() {
  const { ok, status, data, headers } = await jsonFetch("/api/overrides?envelope=1");
  if (!ok) return { ok, status, data };
  const enveloped = data && typeof data.etag === "string"
    && data.overrides && typeof data.overrides === "object";
  return {
    ok,
    status,
    doc: enveloped ? data.overrides : data,
    etag: enveloped ? data.etag : (headers?.get?.("ETag") || null),
  };
}

function overridesDirty() {
  const el = $("overrides-text");
  return Boolean(el) && state.overridesLoadedText != null && el.value !== state.overridesLoadedText;
}

function showOverridesConflict(text) {
  const el = $("overrides-conflict");
  if (!el) return;
  el.textContent = text || "";
  el.hidden = !text;
}

async function loadOverrides() {
  const res = await fetchOverrides();
  if (res.ok) {
    const text = JSON.stringify(res.doc, null, 2);
    $("overrides-text").value = text;
    state.overridesLoadedText = text;
    // Remember exactly which version the textarea holds, so a save can refuse
    // to overwrite a change made since (If-Match, #289).
    state.overridesEtag = res.etag;
    showOverridesConflict("");
    setStatus("overrides-status", "loaded from disk", "ok");
  } else {
    setStatus("overrides-status", `load failed: ${res.data?.error || "?"}`, "err");
  }
  return res.ok;
}

async function saveOverrides() {
  let payload;
  try {
    payload = JSON.parse($("overrides-text").value);
  } catch (err) {
    setStatus("overrides-status", `invalid JSON: ${err.message}`, "err");
    return;
  }
  const headers = { "Content-Type": "application/json" };
  if (state.overridesEtag) headers["If-Match"] = state.overridesEtag;
  const { ok, status, data } = await jsonFetch("/api/overrides", {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (status === 412) {
    // Someone (another tab's ban, a CLI edit) wrote the file since this
    // editor loaded it. Saving anyway would silently undo their change —
    // and so would replacing the textarea with the disk copy, which would
    // throw away the operator's edit instead. Keep the draft, show what is
    // on disk now beside it, and leave the ETag alone: only an explicit
    // "Reload from disk" adopts the new version, so a blind re-save keeps
    // being refused rather than overwriting the change it never saw.
    const fresh = await fetchOverrides();
    showOverridesConflict(fresh.ok
      ? `Current file on disk:\n${JSON.stringify(fresh.doc, null, 2)}`
      : "");
    setStatus(
      "overrides-status",
      "not saved: the file changed on disk since you loaded it. Your edit is kept above; " +
      "merge in the current version shown below, then click \"Reload from disk\" " +
      "(which replaces your edit) and re-apply, or copy your edit first",
      "warn",
    );
    return;
  }
  if (ok) {
    if (data?.etag) state.overridesEtag = data.etag;
    state.overridesLoadedText = $("overrides-text").value;
    showOverridesConflict("");
    setStatus("overrides-status", `saved to ${data.path}`, "ok");
    refreshCoverageViews();
  } else {
    setStatus("overrides-status", `save failed (${status}): ${data?.error || "?"}`, "err");
  }
}

// ------- Content overrides editor -------------------------------------------

async function loadContentOverrides() {
  const { ok, data } = await jsonFetch("/api/content-overrides");
  if (ok && data) {
    $("content-overrides-text").value = JSON.stringify(data, null, 2);
    setStatus("content-overrides-status", `loaded ${Object.keys(data).length} entries`, "ok");
    return true;
  }
  setStatus("content-overrides-status", `load failed: ${data?.error || "?"}`, "err");
  return false;
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
    `baked ${data.kept} rows from ${data.input} input (overrides applied: ${data.applied_overrides}` +
    (data.reverted_overrides ? `, reverted: ${data.reverted_overrides}` : "") + ", " +
    `dropped ${drops.no_bucket} no-bucket / ${drops.no_display_quote} no-quote / ${drops.low_quality} low-quality). ` +
    `Next tick will pick up the new database.`,
    "ok",
  );
  // Refresh the now-showing block so the operator sees the updated pick, and
  // the coverage views, which a bake changes (#290).
  setTimeout(refreshCurrent, 1500);
  refreshCoverageViews();
}

// ------- Per-row ban --------------------------------------------------------

async function banQuoteKey(key) {
  if (!key) return;
  if (!confirm(`Add ${key} to ban_quote_keys? The picker will skip this exact quote forever.`)) return;
  // The server does the read-modify-write under a lock (#289). Doing it here —
  // GET the sidecar, add the key, POST the whole document back — lost any
  // write that landed between the two requests (a ban from another tab, an
  // editor save), and could clobber a corrupt file with defaults.
  const { ok, status, data } = await jsonFetch("/api/overrides/ban", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!ok) {
    alert(`Ban failed (${status}): ${data?.error || "?"}`);
    return;
  }
  log(data?.already_banned ? `${key} was already banned` : `banned ${key}`, "ok");
  // Re-render so the panel jumps to a new pick that doesn't include the banned row.
  await fireAction("rerender");
  // Show the ban in the editor — unless the operator has unsaved edits there.
  // Reloading would discard them, and adopting the new ETag would let their
  // eventual save silently drop this ban; leaving both alone means that save
  // is refused with 412 and they are told why.
  if (overridesDirty()) {
    setStatus(
      "overrides-status",
      `${key} was banned on disk; your unsaved edit is kept — saving it will be refused until you reload`,
      "warn",
    );
  } else {
    await loadOverrides();
  }
  refreshCoverageViews();
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
  const data = await pollFetch("history", "/api/history?limit=30");
  if (!data) return;
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
  releaseWizardTiles();
  grid.innerHTML = "";
  for (const theme of data.themes || []) {
    const { cell, img } = themeThumb(theme, `Use ${theme}`, () => completeWizard(theme));
    state.wizardTiles.push({ theme, img });
    if (theme === (data.manual_theme || data.theme_arg)) cell.classList.add("selected");
    grid.appendChild(cell);
  }
  openWizard(overlay);
}

function releaseWizardTiles() {
  for (const tile of state.wizardTiles) releaseImage(tile.img);
  state.wizardTiles = [];
}

// Minimal modal focus management (#292): remember where focus was, move it
// into the dialog so keyboard and screen-reader users land on it, and put it
// back when the dialog closes.
let wizardReturnFocus = null;
let wizardKeysWired = false;

const WIZARD_FOCUSABLE = "button, [href], input, select, textarea";

function wizardFocusables(overlay) {
  const found = Array.from(overlay.querySelectorAll?.(WIZARD_FOCUSABLE) || [])
    .filter((el) => !el.disabled && !el.hidden);
  if (!found.length) {
    const dismiss = $("wizard-dismiss");
    if (dismiss) found.push(dismiss);
  }
  return found;
}

// aria-modal promises assistive tech that nothing outside the dialog is
// reachable, so keep Tab / Shift+Tab cycling inside it. Escape closes the
// dialog for this page load without marking setup complete — it comes back
// on the next visit, where "I'm ready" is the way to retire it for good.
function wizardKeydown(event) {
  const overlay = $("setup-wizard");
  if (!overlay || overlay.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeWizard();
    return;
  }
  if (event.key !== "Tab") return;
  const items = wizardFocusables(overlay);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  let target = null;
  if (!items.includes(active)) target = event.shiftKey ? last : first;
  else if (event.shiftKey && active === first) target = last;
  else if (!event.shiftKey && active === last) target = first;
  if (target) {
    event.preventDefault();
    target.focus();
  }
}

function openWizard(overlay) {
  wizardReturnFocus = document.activeElement || null;
  overlay.hidden = false;
  if (!wizardKeysWired) {
    document.addEventListener("keydown", wizardKeydown);
    wizardKeysWired = true;
  }
  const first = overlay.querySelector?.(WIZARD_FOCUSABLE) || $("wizard-dismiss");
  if (first && typeof first.focus === "function") first.focus();
}

function closeWizard() {
  const overlay = $("setup-wizard");
  if (overlay) overlay.hidden = true;
  releaseWizardTiles();
  const back = wizardReturnFocus;
  wizardReturnFocus = null;
  if (back && typeof back.focus === "function") back.focus();
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
  closeWizard();
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
