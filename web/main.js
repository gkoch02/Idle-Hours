// LitClock curator — vanilla JS, no build step.
// Every fetch is relative so we inherit the page's origin; token auth lives
// entirely on the server side and is only required for LAN binds (see README).

const $ = (id) => document.getElementById(id);
const log = (msg, cls = "") => {
  const el = $("action-log");
  const line = document.createElement("div");
  line.textContent = `${new Date().toLocaleTimeString()}  ${msg}`;
  if (cls) line.className = cls;
  el.prepend(line);
  // Keep the log short — older lines scroll off on their own via flex.
  while (el.children.length > 8) el.removeChild(el.lastChild);
};

async function jsonFetch(url, opts = {}) {
  const resp = await fetch(url, opts);
  const text = await resp.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { error: text }; }
  }
  return { status: resp.status, ok: resp.ok, data };
}

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
  // Cache-bust the preview so the panel-next-to-you stays in sync.
  $("current-png").src = `/current.png?t=${Date.now()}`;
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

const fmtMs = (v) => (v == null ? "—" : `${v} ms`);

// ------- Coverage grid -------------------------------------------------------

async function refreshCoverage() {
  const { ok, data } = await jsonFetch("/api/coverage");
  if (!ok || !data) return;
  const grid = $("coverage-grid");
  grid.innerHTML = "";
  const counts = data.bucket_counts || {};
  const STATES = [
    "exact", "five_past", "ten_past", "quarter_past", "twenty_past",
    "twenty_five_past", "half_past", "twenty_five_to", "twenty_to",
    "quarter_to", "ten_to", "five_to",
  ];
  // 12 rows (hours) × 12 cols (states). Row-major so the sticky header reads
  // left-to-right as "exact → five past → … → five to".
  for (let h = 1; h <= 12; h++) {
    for (const state of STATES) {
      const bucket = `h${h}_${state}`;
      const n = counts[bucket] || 0;
      const cell = document.createElement("div");
      cell.className = `coverage-cell ${bucketClass(n)}`;
      cell.textContent = n;
      cell.title = `${bucket}: ${n} candidate${n === 1 ? "" : "s"}`;
      cell.onclick = () => {
        $("inspector-bucket").value = bucket;
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
  el.innerHTML = `
    <div class="candidate-head">
      <strong>#${idx + 1} ${entry.is_winner ? "★ winner" : ""}</strong>
      <span>source ${row.source_id ?? "?"} · line ${row.line_number ?? "?"} · q=${row.quality_score ?? "?"}</span>
    </div>
    <div class="candidate-quote">${escapeHtml(row.display_quote || "—")}</div>
    <div class="candidate-meta">${escapeHtml(title)}</div>
    <div class="candidate-score"></div>
  `;
  const scoreEl = el.querySelector(".candidate-score");
  for (const [k, v] of Object.entries(score)) {
    const span = document.createElement("span");
    span.textContent = `${k}: ${v}`;
    if (v && v !== 0) span.classList.add("nonzero");
    scoreEl.appendChild(span);
  }
  return el;
}

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------- Controls (mirror buttons) ------------------------------------------

async function fireAction(action) {
  log(`→ ${action}`);
  const { status, ok, data } = await jsonFetch(`/api/action/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (status === 409) {
    log(`${action}: busy (render in flight)`, "warn");
    return;
  }
  if (!ok) {
    log(`${action}: error ${status} ${data?.error || ""}`, "err");
    return;
  }
  log(`${action}: ok`, "ok");
  await refreshCurrent();
}

function wireControls() {
  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => fireAction(btn.dataset.action));
  });
}

// ------- Overrides editor ---------------------------------------------------

async function loadOverrides() {
  const { ok, data } = await jsonFetch("/api/overrides");
  if (ok) {
    $("overrides-text").value = JSON.stringify(data, null, 2);
    setOverrideStatus("loaded from disk", "ok");
  } else {
    setOverrideStatus(`load failed: ${data?.error || "?"}`, "err");
  }
}

async function saveOverrides() {
  let payload;
  try {
    payload = JSON.parse($("overrides-text").value);
  } catch (err) {
    setOverrideStatus(`invalid JSON: ${err.message}`, "err");
    return;
  }
  const { ok, status, data } = await jsonFetch("/api/overrides", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (ok) setOverrideStatus(`saved to ${data.path}`, "ok");
  else setOverrideStatus(`save failed (${status}): ${data?.error || "?"}`, "err");
}

function setOverrideStatus(msg, cls) {
  const el = $("overrides-status");
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
    li.textContent = `${entry.ts} — source ${entry.source_id} line ${entry.line_number}`;
    list.appendChild(li);
  }
}

// ------- Wiring -------------------------------------------------------------

function init() {
  wireControls();
  $("inspector-form").addEventListener("submit", inspectBucket);
  $("overrides-save").addEventListener("click", (e) => { e.preventDefault(); saveOverrides(); });
  $("overrides-reload").addEventListener("click", loadOverrides);

  refreshAll();
  // Poll every 30s. Cheap — all GETs are stdlib-served and cached-none.
  setInterval(refreshCurrent, 30000);
  setInterval(refreshTelemetry, 30000);
  setInterval(refreshHistory, 60000);
}

async function refreshAll() {
  await Promise.all([refreshCurrent(), refreshTelemetry(), refreshCoverage(), refreshHistory()]);
  await loadOverrides();
}

document.addEventListener("DOMContentLoaded", init);
