// Behavioural tests for idle_hours/web/main.js.
//
// The curator UI's 726 lines of front-end had no tests and the repo had no JS
// test infrastructure at all, so a whole class of operator-facing behaviour
// was unverifiable from Python: hash routing, the lazy per-tab fetch gating,
// the focus guard that stops a 30s poll from clobbering an open dropdown, the
// 401 token-recovery retry, and — most consequentially — the read-modify-write
// in banQuoteKey, which rewrites the shared selection_overrides sidecar from
// the browser. A bug there silently drops an operator's bans and boosts.
//
// Run with:  node --test tests/js/*.test.mjs
// (tests/test_web_ui_js.py shells out to the same command so it runs in CI.)

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { loadMainJs, makeTab, makePanel, routeTable } from "./harness.mjs";

// Every id the lazy tab loaders touch. Tab tests must supply all of them:
// activateTab fires those loaders, and a missing element surfaces as an
// unhandled rejection *after* the test ends rather than as a clean failure.
const LAZY_TAB_ELEMENT_IDS = [
  "action-log",
  "content-overrides-text", "content-overrides-status",
  "gap-threshold", "gap-results",
  "theme-preview-grid",
];

const LAZY_TAB_ROUTES = {
  "GET /api/content-overrides": { body: {} },
  "GET /api/gaps": { body: { buckets: [] } },
  "GET /api/themes": { body: { themes: ["default"], effective: "default", theme_arg: "auto" } },
};

/** Let the lazy loaders activateTab kicked off settle before asserting. */
const flush = () => new Promise((resolve) => setImmediate(resolve));

/** Load main.js wired for the ban flow, capturing what gets POSTed. */
async function banHarness(extra = {}, banRoute = { body: { ok: true, key: "1342:77", already_banned: false } }) {
  const posted = [];
  const table = routeTable({
    "GET /api/overrides": { body: {} },
    "POST /api/overrides/ban": banRoute,
    "POST /api/action/rerender": { body: { ok: true } },
  });
  const harness = await loadMainJs({
    elementIds: ["action-log", "overrides-text", "overrides-status"],
    fetch: async (url, init) => {
      if ((init.method || "GET").toUpperCase() === "POST") {
        posted.push({ url, body: init.body ? JSON.parse(init.body) : null, headers: init.headers });
      }
      return table(url, init);
    },
    ...extra,
  });
  return { ...harness, posted };
}

describe("banQuoteKey — server-side ban, no browser read-modify-write (#289)", () => {
  it("POSTs only the key to the ban endpoint", async () => {
    // The old flow GET-mutated-POSTed the whole sidecar and lost any write
    // that landed in between. The browser must now send just the key.
    const { api, posted } = await banHarness();
    await api.banQuoteKey("1342:77");
    const bans = posted.filter((p) => p.url === "/api/overrides/ban");
    assert.equal(bans.length, 1);
    assert.deepEqual(bans[0].body, { key: "1342:77" });
    assert.equal(bans[0].headers["Content-Type"], "application/json");
  });

  it("never writes the whole sidecar document", async () => {
    const { api, posted } = await banHarness();
    await api.banQuoteKey("1342:77");
    assert.equal(posted.filter((p) => p.url === "/api/overrides").length, 0);
  });

  it("does not read the sidecar before banning", async () => {
    const { api, calls } = await banHarness();
    await api.banQuoteKey("1342:77");
    const firstBan = calls.fetches.findIndex((f) => f.url === "/api/overrides/ban");
    const readBefore = calls.fetches.slice(0, firstBan).some((f) => f.url === "/api/overrides");
    assert.equal(readBefore, false);
  });

  it("does nothing at all when the operator cancels the confirm", async () => {
    const { api, posted, calls } = await banHarness({ confirmResult: false });
    await api.banQuoteKey("1342:77");
    assert.equal(posted.length, 0);
    assert.equal(calls.fetches.length, 0);
  });

  it("ignores an empty key without prompting", async () => {
    const { api, calls } = await banHarness();
    await api.banQuoteKey("");
    assert.equal(calls.confirms.length, 0);
    assert.equal(calls.fetches.length, 0);
  });

  it("surfaces a refused ban (corrupt sidecar) and does not re-render", async () => {
    const { api, calls } = await banHarness({}, { status: 409, body: { error: "corrupt" } });
    await api.banQuoteKey("1342:77");
    assert.equal(calls.alerts.length, 1);
    assert.match(calls.alerts[0], /Ban failed \(409\)/);
    assert.equal(calls.fetches.filter((f) => f.url === "/api/action/rerender").length, 0);
  });

  it("re-renders the panel after a successful ban", async () => {
    // Without this the banned quote stays on the eInk panel until the next
    // bucket change — up to an hour of staring at the quote you just rejected.
    const { api, calls } = await banHarness();
    await api.banQuoteKey("1342:77");
    const actions = calls.fetches.filter((f) => f.url === "/api/action/rerender");
    assert.equal(actions.length, 1);
  });

  it("refreshes the coverage grid after a successful ban", async () => {
    const { api, calls } = await banHarness({
      elementIds: ["action-log", "overrides-text", "overrides-status", "coverage-grid"],
    });
    await api.banQuoteKey("1342:77");
    await flush();
    assert.ok(calls.fetches.some((f) => f.url === "/api/coverage"), "coverage not refreshed");
  });
});

describe("overrides editor — If-Match on save (#289)", () => {
  // `envelope` switches the GET between the body-carries-the-ETag shape and
  // the bare document an older server returns (tag in the header only).
  function editorHarness(saveRoute, { envelope = true, headerEtag = (v) => `"v${v}"` } = {}) {
    const table = routeTable({
      "POST /api/overrides": saveRoute,
      "POST /api/overrides/ban": { body: { ok: true, key: "1:1", already_banned: false } },
      "POST /api/action/rerender": { body: { ok: true } },
    });
    let gets = 0;
    return loadMainJs({
      elementIds: ["action-log", "overrides-text", "overrides-status", "overrides-conflict"],
      fetch: async (url, init) => {
        if ((init.method || "GET") === "GET" && url.split("?")[0] === "/api/overrides") {
          gets += 1;
          const doc = { ban_quote_keys: [], version: gets };
          const body = envelope ? { overrides: doc, etag: `"v${gets}"` } : doc;
          return {
            status: 200, ok: true,
            text: async () => JSON.stringify(body),
            headers: { get: (h) => (h.toLowerCase() === "etag" ? headerEtag(gets) : null) },
          };
        }
        return table(url, init);
      },
    });
  }

  it("sends the ETag it loaded as If-Match", async () => {
    const h = await editorHarness({ body: { ok: true, path: "x", etag: '"v9"' } });
    await h.sandbox.loadOverrides();
    await h.sandbox.saveOverrides();
    const save = h.calls.fetches.find((f) => f.init.method === "POST");
    assert.equal(save.init.headers["If-Match"], '"v1"');
    assert.equal(h.api.state.overridesEtag, '"v9"', "a successful save adopts the new ETag");
  });

  it("asks for the envelope and prefers the body ETag over a proxy-weakened header", async () => {
    const h = await editorHarness({ body: { ok: true } }, { headerEtag: (v) => `W/"v${v}"` });
    await h.sandbox.loadOverrides();
    assert.ok(h.calls.fetches[0].url.includes("envelope=1"));
    assert.equal(h.api.state.overridesEtag, '"v1"');
    assert.match(h.elements.get("overrides-text").value, /"version": 1/);
    assert.doesNotMatch(h.elements.get("overrides-text").value, /etag/, "the envelope must not leak into the editor");
  });

  it("falls back to the header ETag against a server without the envelope", async () => {
    const h = await editorHarness({ body: { ok: true } }, { envelope: false });
    await h.sandbox.loadOverrides();
    assert.equal(h.api.state.overridesEtag, '"v1"');
    assert.match(h.elements.get("overrides-text").value, /"version": 1/);
  });

  it("on 412 keeps the operator's draft and the old ETag, and shows the disk copy", async () => {
    const h = await editorHarness({ status: 412, body: { error: "changed" } });
    await h.sandbox.loadOverrides();
    const draft = '{"ban_quote_keys": ["my-edit"]}';
    h.elements.get("overrides-text").value = draft;
    await h.sandbox.saveOverrides();
    assert.equal(h.elements.get("overrides-text").value, draft, "the draft was destroyed");
    assert.equal(h.api.state.overridesEtag, '"v1"', "a 412 must not adopt the new version implicitly");
    assert.match(h.elements.get("overrides-status").textContent, /changed on disk/);
    assert.match(h.elements.get("overrides-status").textContent, /edit is kept/);
    const conflict = h.elements.get("overrides-conflict");
    assert.equal(conflict.hidden, false);
    assert.match(conflict.textContent, /"version": 2/);
    // An explicit reload is what adopts the current version.
    await h.sandbox.loadOverrides();
    assert.equal(h.api.state.overridesEtag, '"v3"');
    assert.match(h.elements.get("overrides-text").value, /"version": 3/);
    assert.equal(conflict.hidden, true);
  });

  it("omits If-Match when nothing was loaded", async () => {
    const h = await editorHarness({ body: { ok: true, path: "x" } });
    h.elements.get("overrides-text").value = '{"ban_quote_keys": []}';
    await h.sandbox.saveOverrides();
    const save = h.calls.fetches.find((f) => f.init.method === "POST");
    assert.equal(save.init.headers["If-Match"], undefined);
  });

  it("a ban leaves an unsaved edit and its ETag alone", async () => {
    const h = await editorHarness({ body: { ok: true } });
    await h.sandbox.loadOverrides();
    const draft = '{"ban_quote_keys": [], "boost_source_ids": ["42"]}';
    h.elements.get("overrides-text").value = draft;
    await h.api.banQuoteKey("1:1");
    assert.equal(h.elements.get("overrides-text").value, draft, "the ban wiped the operator's edit");
    assert.equal(h.api.state.overridesEtag, '"v1"', "adopting the post-ban ETag would let the save drop the ban");
    assert.match(h.elements.get("overrides-status").textContent, /unsaved edit is kept/);
  });

  it("a ban reloads a clean editor so the new key shows", async () => {
    const h = await editorHarness({ body: { ok: true } });
    await h.sandbox.loadOverrides();
    await h.api.banQuoteKey("1:1");
    assert.equal(h.api.state.overridesEtag, '"v2"');
    assert.match(h.elements.get("overrides-text").value, /"version": 2/);
  });
});

describe("jsonFetch — token handling and 401 recovery", () => {
  const okRoute = routeTable({ "GET /api/current": { body: { time: "14:30" } } });

  it("omits the token header when no token is stored", async () => {
    const { api, calls } = await loadMainJs({ fetch: okRoute });
    await api.jsonFetch("/api/current");
    assert.equal(calls.fetches[0].init.headers["X-Idle-Hours-Token"], undefined);
  });

  it("sends the stored token on every request", async () => {
    const { api, calls } = await loadMainJs({ fetch: okRoute });
    api.setToken("s3cret");
    await api.jsonFetch("/api/current");
    assert.equal(calls.fetches[0].init.headers["X-Idle-Hours-Token"], "s3cret");
  });

  it("prompts once and retries after a 401", async () => {
    let seen = 0;
    const { api, calls } = await loadMainJs({
      promptResult: "  pasted-token  ",
      fetch: async () => {
        seen += 1;
        return seen === 1
          ? { status: 401, ok: false, text: async () => "" }
          : { status: 200, ok: true, text: async () => JSON.stringify({ ok: true }) };
      },
    });
    const res = await api.jsonFetch("/api/current");
    assert.equal(calls.prompts.length, 1);
    assert.equal(calls.fetches.length, 2);
    assert.equal(res.status, 200);
    // The pasted value is trimmed before storage and used on the retry.
    assert.equal(calls.fetches[1].init.headers["X-Idle-Hours-Token"], "pasted-token");
    assert.equal(api.getToken(), "pasted-token");
  });

  it("does not retry when the operator cancels the token prompt", async () => {
    const { api, calls } = await loadMainJs({
      promptResult: null,
      fetch: async () => ({ status: 401, ok: false, text: async () => "" }),
    });
    const res = await api.jsonFetch("/api/current");
    assert.equal(calls.fetches.length, 1);
    assert.equal(res.status, 401);
  });

  it("raises ONE prompt when several concurrent requests 401", async () => {
    // Gating JSON GETs (#233) made this reachable on a LAN bind's very first
    // load: refreshAll() fires five GETs through Promise.all and the wizard
    // adds /api/setup, so six independent 401 handlers each raised their own
    // window.prompt. The operator saw six stacked dialogs.
    const { api, calls } = await loadMainJs({
      promptResult: "the-token",
      fetch: async (url, init = {}) => {
        const token = (init.headers || {})["X-Idle-Hours-Token"];
        return token === "the-token"
          ? { status: 200, ok: true, text: async () => "{}" }
          : { status: 401, ok: false, text: async () => "" };
      },
    });
    const results = await Promise.all([
      api.jsonFetch("/api/current"), api.jsonFetch("/api/telemetry"),
      api.jsonFetch("/api/coverage"), api.jsonFetch("/api/history"),
      api.jsonFetch("/api/themes"), api.jsonFetch("/api/setup"),
    ]);
    assert.equal(calls.prompts.length, 1, "one dialog per page load, not one per request");
    // The five that skipped the prompt must still have recovered.
    assert.ok(results.every((r) => r.ok), "a request that skipped the prompt must still retry");
  });

  it("raises ONE prompt even when the operator cancels it", async () => {
    // Storage being unchanged is not proof that nobody asked. Cancelling (or
    // submitting empty) stores nothing, so keying the dedup only on "a new
    // non-empty token appeared" put all six dialogs back — precisely when the
    // operator does not have the token to hand.
    const { api, calls } = await loadMainJs({
      promptResult: null,               // Cancel
      fetch: async () => ({ status: 401, ok: false, text: async () => "" }),
    });
    await Promise.all([
      api.jsonFetch("/api/current"), api.jsonFetch("/api/telemetry"),
      api.jsonFetch("/api/coverage"), api.jsonFetch("/api/history"),
      api.jsonFetch("/api/themes"), api.jsonFetch("/api/setup"),
    ]);
    assert.equal(calls.prompts.length, 1, "one dialog per burst even on cancel");
  });

  it("prompts again on a later request after a cancelled burst", async () => {
    // The memo must not silence the operator for the life of the page: a
    // request that starts when nothing else is in flight begins a new burst.
    const { api, calls } = await loadMainJs({
      promptResult: null,
      fetch: async () => ({ status: 401, ok: false, text: async () => "" }),
    });
    await Promise.all([api.jsonFetch("/api/current"), api.jsonFetch("/api/themes")]);
    assert.equal(calls.prompts.length, 1);
    await api.jsonFetch("/api/current");   // the operator clicks something later
    assert.equal(calls.prompts.length, 2, "a later attempt must be able to prompt");
  });

  it("prompts again when the stored token is itself the one that failed", async () => {
    // The dedup must key on "storage changed", not "storage is non-empty" —
    // otherwise a stale saved token would suppress the prompt forever and the
    // operator could never correct it.
    const { api, calls, storage } = await loadMainJs({
      promptResult: "fresh",
      fetch: async () => ({ status: 401, ok: false, text: async () => "" }),
    });
    storage.set("idle-hours.web.token", "stale");  // raw Map behind the localStorage shim
    await api.jsonFetch("/api/current");
    assert.equal(calls.prompts.length, 1);
  });

  it("retries at most once so a persistent 401 cannot loop", async () => {
    // jsonFetch recurses; a missing retryAfterAuth=false on the inner call
    // would prompt-and-retry forever against a wrong token.
    const { api, calls } = await loadMainJs({
      promptResult: "always-wrong",
      fetch: async () => ({ status: 401, ok: false, text: async () => "" }),
    });
    await api.jsonFetch("/api/current");
    assert.equal(calls.fetches.length, 2);
    assert.equal(calls.prompts.length, 1);
  });

  it("wraps a non-JSON error body instead of throwing", async () => {
    const { api } = await loadMainJs({
      fetch: async () => ({ status: 500, ok: false, text: async () => "<html>oops</html>" }),
    });
    const res = await api.jsonFetch("/api/current");
    assert.equal(res.ok, false);
    assert.equal(res.data.error, "<html>oops</html>");
  });
});

describe("tab navigation", () => {
  const TAB_NAMES = ["now", "curate", "coverage", "activity"];

  async function tabHarness(hash = "") {
    return loadMainJs({
      hash,
      tabs: TAB_NAMES.map(makeTab),
      panels: TAB_NAMES.map(makePanel),
      elementIds: LAZY_TAB_ELEMENT_IDS,
      fetch: routeTable(LAZY_TAB_ROUTES),
    });
  }

  it("shows only the activated panel", async () => {
    const { api, panels } = await tabHarness();
    api.activateTab("curate");
    await flush();
    assert.deepEqual(panels.map((p) => p.hidden), [true, false, true, true]);
  });

  it("marks the active tab for assistive tech", async () => {
    const { api, tabs } = await tabHarness();
    api.activateTab("coverage");
    await flush();
    assert.deepEqual(tabs.map((t) => t.getAttribute("aria-selected")),
                     ["false", "false", "true", "false"]);
    assert.equal(tabs[2].classList.contains("active"), true);
  });

  it("writes the tab into the URL hash so it is bookmarkable", async () => {
    const { api, location } = await tabHarness();
    api.activateTab("activity");
    await flush();
    assert.equal(location.hash, "#activity");
  });

  it("does not rewrite history when the hash already matches", async () => {
    const { api, calls } = await tabHarness("#curate");
    calls.replaceState.length = 0;
    api.activateTab("curate");
    await flush();
    assert.equal(calls.replaceState.length, 0);
  });

  it("opens the tab named in the URL hash", async () => {
    const { api, panels } = await tabHarness("#coverage");
    api.wireTabs();
    await flush();
    assert.equal(panels[2].hidden, false);
  });

  it("falls back to 'now' for an unknown hash", async () => {
    // A stale bookmark or a hand-typed #settings must not leave every panel
    // hidden with no visible content.
    const { api, panels } = await tabHarness("#settings");
    api.wireTabs();
    await flush();
    assert.equal(panels[0].hidden, false);
  });
});

describe("lazy per-tab loading", () => {
  const TAB_NAMES = ["now", "curate", "coverage", "activity"];

  async function lazyHarness() {
    return loadMainJs({
      tabs: TAB_NAMES.map(makeTab),
      panels: TAB_NAMES.map(makePanel),
      elementIds: LAZY_TAB_ELEMENT_IDS,
      fetch: routeTable(LAZY_TAB_ROUTES),
    });
  }

  it("fetches a tab's data on first activation only", async () => {
    const { api, calls } = await lazyHarness();
    api.activateTab("curate");
    await flush();
    const first = calls.fetches.filter((f) => f.url.startsWith("/api/content-overrides")).length;
    api.activateTab("now");
    await flush();
    api.activateTab("curate");
    await flush();
    const second = calls.fetches.filter((f) => f.url.startsWith("/api/content-overrides")).length;
    assert.equal(first, 1);
    assert.equal(second, 1, "re-activating a tab must not re-fetch");
  });

  it("retries a lazy tab whose first load failed (#290)", async () => {
    // The flag used to latch on activation, so a tab whose first fetch
    // failed stayed empty until a full page reload. It now latches on
    // success only.
    let gapsFail = true;
    const table = routeTable(LAZY_TAB_ROUTES);
    const { api, calls } = await loadMainJs({
      tabs: TAB_NAMES.map(makeTab),
      panels: TAB_NAMES.map(makePanel),
      elementIds: LAZY_TAB_ELEMENT_IDS,
      fetch: async (url, init) => {
        if (url.startsWith("/api/gaps") && gapsFail) {
          return { status: 500, ok: false, text: async () => JSON.stringify({ error: "boom" }) };
        }
        return table(url, init);
      },
    });
    const gapCalls = () => calls.fetches.filter((f) => f.url.startsWith("/api/gaps")).length;

    api.activateTab("coverage");
    await flush();
    assert.equal(api.state.gapsLoaded, false, "a failed load must not latch");
    assert.equal(gapCalls(), 1);

    gapsFail = false;
    api.activateTab("now");
    await flush();
    api.activateTab("coverage");
    await flush();
    assert.equal(gapCalls(), 2, "the next activation must retry");
    assert.equal(api.state.gapsLoaded, true);

    api.activateTab("now");
    await flush();
    api.activateTab("coverage");
    await flush();
    assert.equal(gapCalls(), 2, "a successful load is not repeated");
  });

  it("does not start a second load while the first is in flight", async () => {
    const { api, calls } = await lazyHarness();
    api.activateTab("curate");
    api.activateTab("now");
    api.activateTab("curate");
    await flush();
    const n = calls.fetches.filter((f) => f.url.startsWith("/api/content-overrides")).length;
    assert.equal(n, 1);
  });

  it("keeps the three lazy tabs independent", async () => {
    const { api } = await lazyHarness();
    api.activateTab("curate");
    await flush();
    assert.equal(api.state.contentOverridesLoaded, true);
    assert.equal(api.state.gapsLoaded, false);
    assert.equal(api.state.themePreviewLoaded, false);
  });
});

describe("refreshThemes — dropdown focus guard and state pill", () => {
  async function themeHarness(payload, { focused = false } = {}) {
    const harness = await loadMainJs({
      elementIds: ["theme-select", "theme-current", "action-log"],
      fetch: routeTable({ "GET /api/themes": { body: payload } }),
    });
    const select = harness.elements.get("theme-select");
    if (focused) harness.document._activeElement = select;
    return { ...harness, select, pill: harness.elements.get("theme-current") };
  }

  const PAYLOAD = {
    themes: ["default", "dark", "scholar"],
    theme_arg: "auto",
    manual_theme: null,
    effective: "dark",
  };

  it("populates the dropdown from /api/themes", async () => {
    const { api, select } = await themeHarness(PAYLOAD);
    await api.refreshThemes();
    assert.deepEqual(select.optionValues, ["default", "dark", "scholar"]);
  });

  it("marks the effective theme in the option label", async () => {
    const { api, select } = await themeHarness(PAYLOAD);
    await api.refreshThemes();
    assert.equal(select.children[1].textContent, "dark (active)");
  });

  it("leaves the dropdown untouched while it has focus", async () => {
    // The 30s poll must not collapse an open <select> mid-selection.
    const { api, select } = await themeHarness(PAYLOAD, { focused: true });
    await api.refreshThemes();
    assert.equal(select.children.length, 0, "rebuilt the list while focused");
  });

  it("still updates the state pill while the dropdown has focus", async () => {
    const { api, pill } = await themeHarness(PAYLOAD, { focused: true });
    await api.refreshThemes();
    assert.equal(pill.textContent, "auto: dark");
  });

  it("distinguishes manual, auto and fixed in the pill", async () => {
    for (const [payload, expected] of [
      [{ ...PAYLOAD, manual_theme: "gothic" }, "manual: gothic"],
      [{ ...PAYLOAD, manual_theme: null, theme_arg: "auto" }, "auto: dark"],
      [{ ...PAYLOAD, manual_theme: null, theme_arg: "scholar", effective: "scholar" }, "fixed: scholar"],
    ]) {
      const { api, pill } = await themeHarness(payload);
      await api.refreshThemes();
      assert.equal(pill.textContent, expected);
    }
  });

  it("caches the theme list on state for the preview grid", async () => {
    const { api } = await themeHarness(PAYLOAD);
    await api.refreshThemes();
    assert.deepEqual(api.state.themes, ["default", "dark", "scholar"]);
  });
});

describe("escapeHtml — corpus text is interpolated into innerHTML", () => {
  it("neutralises every character that could break out of markup", async () => {
    const { api } = await loadMainJs({});
    assert.equal(
      api.escapeHtml(`<img src=x onerror="alert('x')">`),
      "&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;",
    );
  });

  it("escapes ampersands so entities cannot be smuggled in", async () => {
    const { api } = await loadMainJs({});
    assert.equal(api.escapeHtml("&lt;script&gt;"), "&amp;lt;script&amp;gt;");
  });

  it("coerces non-strings instead of throwing", async () => {
    // Corpus rows carry nulls and numbers (line_number, quality_score).
    const { api } = await loadMainJs({});
    assert.equal(api.escapeHtml(null), "null");
    assert.equal(api.escapeHtml(482), "482");
  });
});

describe("rowIdLine — the corpus identity span", () => {
  // This line is built into innerHTML by both the bucket inspector and the
  // search results, and for a long time it was the one place corpus fields
  // reached the DOM unescaped. The fields are numeric in any corpus the
  // pipeline produces, so these cases stand in for a hand-edited or
  // externally-merged JSONL — the input that made the gap worth closing.
  it("renders the ordinary numeric case", async () => {
    const { api } = await loadMainJs({});
    assert.equal(
      api.rowIdLine({ source_id: "141", line_number: 482, quality_score: 95 }),
      "source 141 · line 482 · q=95",
    );
  });

  it("escapes markup in every field it interpolates", async () => {
    const { api } = await loadMainJs({});
    const line = api.rowIdLine({
      source_id: `<img src=x onerror="alert(1)">`,
      line_number: "<script>",
      quality_score: "'>",
    });
    assert.ok(!line.includes("<"), `raw '<' survived: ${line}`);
    assert.ok(!line.includes(`"`), `raw '"' survived: ${line}`);
    assert.ok(line.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
    assert.ok(line.includes("&lt;script&gt;"));
    assert.ok(line.includes("&#39;&gt;"));
  });

  it("falls back to a question mark for absent fields", async () => {
    const { api } = await loadMainJs({});
    // Rows dropped by a re-bake reach the UI with bare ids, and source_id is
    // null for every locally-mined (non-Gutenberg) row.
    assert.equal(api.rowIdLine({}), "source ? · line ? · q=?");
    assert.equal(
      api.rowIdLine({ source_id: null, line_number: 0, quality_score: 0 }),
      "source ? · line 0 · q=0",
    );
  });
});

describe("small formatters", () => {
  it("renders a missing latency as an em dash, not 'undefined ms'", async () => {
    const { api } = await loadMainJs({});
    assert.equal(api.fmtMs(null), "—");
    assert.equal(api.fmtMs(undefined), "—");
    assert.equal(api.fmtMs(0), "0 ms");
  });

  it("classifies bucket counts into the coverage heat scale", async () => {
    const { api } = await loadMainJs({});
    // Zero must be distinguishable from merely sparse — the empty buckets are
    // what the gap finder sends operators off to harvest.
    assert.notEqual(api.bucketClass(0), api.bucketClass(1));
  });
});

describe("token storage degrades gracefully", () => {
  it("survives localStorage being unavailable", async () => {
    // Safari private mode and some kiosk browsers throw on setItem.
    const { api, sandbox } = await loadMainJs({});
    sandbox.localStorage = {
      getItem() { throw new Error("denied"); },
      setItem() { throw new Error("denied"); },
      removeItem() { throw new Error("denied"); },
    };
    assert.equal(api.getToken(), "");
    assert.doesNotThrow(() => api.setToken("x"));
  });
});

describe("token-gated images — /current.png and /api/preview load through fetch (#286)", () => {
  const CURRENT_IDS = [
    "clock", "bucket", "theme", "mode", "quote", "attribution", "matched", "current-png", "ban-current",
    "action-log",
  ];
  const CURRENT = { time: "10:00", bucket: "h10_exact", theme: "default", source_id: "141", line_number: 1 };

  it("fetches the current frame with the token header and shows it as an object URL", async () => {
    const { api, calls, elements } = await loadMainJs({
      elementIds: CURRENT_IDS,
      fetch: routeTable({ "GET /api/current": { body: CURRENT }, "GET /current.png": { body: "png-bytes" } }),
    });
    api.setToken("secret");
    await api.refreshCurrent();
    await flush();
    const png = calls.fetches.find((f) => f.url.startsWith("/current.png"));
    assert.ok(png, "current.png must be fetched, not assigned to img.src");
    assert.equal(png.init.headers["X-Idle-Hours-Token"], "secret");
    assert.deepEqual(calls.objectUrls, ["png-bytes"]);
    assert.equal(elements.get("current-png").src, "blob:stub-1");
  });

  it("revokes the previous object URL when the frame is refreshed", async () => {
    const { api, calls } = await loadMainJs({
      elementIds: CURRENT_IDS,
      fetch: routeTable({ "GET /api/current": { body: CURRENT }, "GET /current.png": { body: "png" } }),
    });
    await api.refreshCurrent();
    await api.refreshCurrent();
    await flush();
    assert.deepEqual(calls.revokedUrls, ["blob:stub-1"]);
  });

  it("loads one preview per theme with the header and never sets a raw src", async () => {
    const { api, calls, elements } = await loadMainJs({
      elementIds: ["action-log", "theme-preview-grid"],
      fetch: routeTable({
        "GET /api/themes": { body: { themes: ["default", "dark"], effective: "default", theme_arg: "auto" } },
        "GET /api/preview": { body: "thumb" },
      }),
    });
    api.setToken("secret");
    await api.refreshThemePreview();
    await flush();
    const previews = calls.fetches.filter((f) => f.url.startsWith("/api/preview?theme="));
    assert.equal(previews.length, 2);
    for (const f of previews) assert.equal(f.init.headers["X-Idle-Hours-Token"], "secret");
    const cells = elements.get("theme-preview-grid").children;
    assert.equal(cells.length, 2);
    for (const cell of cells) {
      const img = cell.children[0];
      assert.equal(img.tagName, "IMG");
      assert.ok(img.src.startsWith("blob:stub-"), `img.src is ${img.src}`);
    }
  });

  it("prompts for the token once and retries when an image 401s", async () => {
    let attempts = 0;
    const { api, calls, elements } = await loadMainJs({
      elementIds: CURRENT_IDS,
      promptResult: "fresh",
      fetch: async (url) => {
        if (url.startsWith("/current.png")) {
          attempts += 1;
          if (attempts === 1) return { status: 401, ok: false, text: async () => "" };
          return { status: 200, ok: true, blob: async () => "png" };
        }
        return { status: 200, ok: true, text: async () => JSON.stringify(CURRENT) };
      },
    });
    await api.refreshCurrent();
    await flush();
    assert.equal(calls.prompts.length, 1);
    assert.equal(attempts, 2);
    assert.equal(elements.get("current-png").src, "blob:stub-1");
  });

  it("leaves the image alone and logs when the fetch fails", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: CURRENT_IDS,
      fetch: routeTable({ "GET /api/current": { body: CURRENT }, "GET /current.png": { status: 404, body: {} } }),
    });
    elements.get("current-png").src = "before";
    await api.refreshCurrent();
    await flush();
    assert.equal(elements.get("current-png").src, "before");
  });
});

describe("the sleep frame — skip / un-skip are refused while asleep", () => {
  const IDS = [
    "clock", "bucket", "theme", "mode", "quote", "attribution", "matched", "current-png", "ban-current",
    "action-log", "action-skip", "action-unskip", "action-quiet",
  ];
  const current = (asleep) => ({
    time: "23:00", bucket: "h11_exact", theme: "default", source_id: "141", line_number: 1, asleep,
  });

  it("disables skip and un-skip and offers a wake while the panel is asleep", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: IDS,
      fetch: routeTable({ "GET /api/current": { body: current(true) }, "GET /current.png": { body: "png" } }),
    });
    await api.refreshCurrent();
    assert.equal(elements.get("action-skip").disabled, true);
    assert.equal(elements.get("action-unskip").disabled, true);
    assert.match(elements.get("action-skip").title, /asleep/);
    assert.equal(elements.get("action-quiet").textContent, "D · Wake");
  });

  it("re-enables them once the panel is awake", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: IDS,
      fetch: routeTable({ "GET /api/current": { body: current(false) }, "GET /current.png": { body: "png" } }),
    });
    await api.refreshCurrent();
    assert.equal(elements.get("action-skip").disabled, false);
    assert.equal(elements.get("action-skip").title, "");
    assert.equal(elements.get("action-quiet").textContent, "D · Sleep");
  });

  it("reports an asleep refusal as asleep, not as a busy render", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: IDS,
      fetch: routeTable({
        "POST /api/action/skip": { status: 409, body: { ok: false, error: "asleep" } },
        "GET /api/current": { body: current(true) },
        "GET /current.png": { body: "png" },
      }),
    });
    await api.fireAction("skip");
    const lines = elements.get("action-log").children.map((c) => c.textContent);
    assert.ok(lines.some((l) => /skip: the panel is asleep/.test(l)), lines.join("\n"));
    assert.ok(!lines.some((l) => /busy/.test(l)), lines.join("\n"));
    // The refusal refreshes the controls, so the stale buttons disable.
    assert.equal(elements.get("action-skip").disabled, true);
  });

  it("still reports a render in flight as busy", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: IDS,
      fetch: routeTable({ "POST /api/action/skip": { status: 409, body: { ok: false, error: "busy" } } }),
    });
    await api.fireAction("skip");
    const lines = elements.get("action-log").children.map((c) => c.textContent);
    assert.ok(lines.some((l) => /skip: busy/.test(l)), lines.join("\n"));
  });
});

describe("theme dropdown follows the live theme (#290)", () => {
  const PAYLOAD = { themes: ["default", "dark", "scholar"], theme_arg: "auto", manual_theme: null, effective: "dark" };

  async function harness(payloads) {
    let i = 0;
    const h = await loadMainJs({
      elementIds: ["theme-select", "theme-current", "action-log", "theme-apply"],
      fetch: async (url, init) => {
        if (url === "/api/themes") {
          const body = payloads[Math.min(i, payloads.length - 1)];
          i += 1;
          return { status: 200, ok: true, text: async () => JSON.stringify(body) };
        }
        return routeTable({ "POST /api/action/theme": { body: { ok: true, theme: "scholar" } } })(url, init);
      },
    });
    h.api.wireControls();
    return { ...h, select: h.elements.get("theme-select") };
  }

  const selected = (select) => select.children.find((c) => c.selected)?.value;

  it("moves the selection when the live theme changes", async () => {
    const { api, select } = await harness([PAYLOAD, { ...PAYLOAD, effective: "scholar" }]);
    await api.refreshThemes();
    assert.equal(selected(select), "dark");
    await api.refreshThemes();
    assert.equal(selected(select), "scholar", "stuck on the first theme it showed");
  });

  it("keeps an unapplied operator choice across polls", async () => {
    const { api, select } = await harness([PAYLOAD, PAYLOAD]);
    await api.refreshThemes();
    select.value = "default";
    for (const fn of select.listeners.change || []) fn();
    await api.refreshThemes();
    assert.equal(selected(select), "default");
  });

  it("follows the live theme after the operator picks the live theme back (not latched)", async () => {
    const { api, select } = await harness([
      { ...PAYLOAD, effective: "default" }, { ...PAYLOAD, effective: "default" }, { ...PAYLOAD, effective: "scholar" },
    ]);
    await api.refreshThemes();
    const pick = (v) => { select.value = v; for (const fn of select.listeners.change || []) fn(); };
    pick("dark");
    await api.refreshThemes();
    assert.equal(selected(select), "dark", "a real pending choice is kept");
    pick("default");
    await api.refreshThemes();
    assert.equal(selected(select), "scholar", "stuck on a choice the operator already undid");
  });

  it("drops a pending choice once the live theme catches up with it", async () => {
    const { api, select } = await harness([
      { ...PAYLOAD, effective: "default" }, { ...PAYLOAD, effective: "dark" }, { ...PAYLOAD, effective: "scholar" },
    ]);
    await api.refreshThemes();
    select.value = "dark";
    for (const fn of select.listeners.change || []) fn();
    await api.refreshThemes();
    await api.refreshThemes();
    assert.equal(selected(select), "scholar");
  });

  it("follows the live theme again once the choice is applied", async () => {
    const { api, select, elements } = await harness([PAYLOAD, PAYLOAD, { ...PAYLOAD, effective: "scholar" }]);
    await api.refreshThemes();
    select.value = "default";
    for (const fn of select.listeners.change || []) fn();
    for (const fn of elements.get("theme-apply").listeners.click || []) fn();
    await flush();
    await flush();
    assert.equal(api.state.themeSelectDirty, false);
    await api.refreshThemes();
    assert.equal(selected(select), "scholar");
  });
});

describe("polled GET failures are reported once per burst (#290)", () => {
  it("logs the first failure, stays quiet on repeats, and logs recovery", async () => {
    let fail = true;
    const { api, elements } = await loadMainJs({
      elementIds: ["action-log", "telemetry-hours", "t-renders", "t-errors", "t-render-p50",
        "t-render-p95", "t-display-p50", "t-display-p95", "t-last-error"],
      fetch: async () => (fail
        ? { status: 503, ok: false, text: async () => JSON.stringify({ error: "down" }) }
        : { status: 200, ok: true, text: async () => JSON.stringify({ render_count: 3 }) }),
    });
    const logLines = () => elements.get("action-log").children.map((c) => c.textContent);
    await api.refreshTelemetry();
    await api.refreshTelemetry();
    await api.refreshTelemetry();
    const failures = logLines().filter((l) => /telemetry refresh failed \(HTTP 503\)/.test(l));
    assert.equal(failures.length, 1, logLines().join("\n"));
    fail = false;
    await api.refreshTelemetry();
    assert.ok(logLines().some((l) => /telemetry refresh recovered/.test(l)));
    assert.equal(elements.get("t-renders").textContent, 3);
  });

  it("reports a network error instead of rejecting", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: ["action-log", "coverage-grid"],
      fetch: async () => { throw new Error("offline"); },
    });
    assert.equal(await api.refreshCoverage(), false);
    assert.match(elements.get("action-log").children[0].textContent, /coverage refresh failed \(network error\)/);
  });
});

describe("staleness after a quote change or a bake (#290)", () => {
  const CURRENT_IDS = ["clock", "bucket", "theme", "mode", "quote", "attribution", "matched",
    "current-png", "ban-current", "action-log", "theme-preview-grid"];

  it("re-renders the theme thumbnails when the displayed quote changes", async () => {
    let current = { source_id: "141", line_number: 1 };
    const { api, calls } = await loadMainJs({
      elementIds: CURRENT_IDS,
      fetch: async (url, init) => {
        if (url === "/api/current") return { status: 200, ok: true, text: async () => JSON.stringify(current) };
        return routeTable({
          "GET /api/themes": { body: { themes: ["default"], effective: "default" } },
          "GET /api/preview": { body: "thumb" },
          "GET /current.png": { body: "png" },
        })(url, init);
      },
    });
    await api.refreshCurrent();
    api.state.themePreviewLoaded = true;
    const previews = () => calls.fetches.filter((f) => f.url.startsWith("/api/preview")).length;
    await api.refreshCurrent();
    await flush();
    assert.equal(previews(), 0, "same quote must not re-render the grid");
    current = { source_id: "141", line_number: 2 };
    await api.refreshCurrent();
    await flush();
    await flush();
    assert.equal(previews(), 1);
  });

  it("refreshes coverage after a successful bake", async () => {
    const { api, calls } = await loadMainJs({
      elementIds: ["action-log", "bake-now", "bake-status", "coverage-grid"],
      fetch: routeTable({
        "POST /api/bake": { body: { ok: true, kept: 1, input: 1, drops: {} } },
        "GET /api/coverage": { body: { bucket_counts: {} } },
      }),
    });
    await api.bakeNow();
    await flush();
    assert.ok(calls.fetches.some((f) => f.url === "/api/coverage"));
  });
});

describe("pick-a-theme surfaces leave out diags (#292)", () => {
  it("the Now-tab grid uses preview_themes, not the full list", async () => {
    const { api, elements } = await loadMainJs({
      elementIds: ["action-log", "theme-preview-grid"],
      fetch: routeTable({
        "GET /api/themes": { body: { themes: ["default", "diags"], preview_themes: ["default"], effective: "default" } },
        "GET /api/preview": { body: "thumb" },
      }),
    });
    await api.refreshThemePreview();
    const labels = elements.get("theme-preview-grid").children.map((c) => c.children[1].textContent);
    assert.deepEqual(labels, ["default"]);
  });

  it("falls back to filtering diags when the server predates preview_themes", async () => {
    const { api } = await loadMainJs({
      elementIds: ["action-log", "theme-preview-grid"],
      fetch: routeTable({
        "GET /api/themes": { body: { themes: ["default", "diags"], effective: "default" } },
        "GET /api/preview": { body: "thumb" },
      }),
    });
    await api.refreshThemePreview();
    assert.deepEqual(api.state.previewThemes, ["default"]);
    assert.deepEqual(api.state.themes, ["default", "diags"], "the dropdown keeps diags");
  });
});

describe("setup wizard focus management (#292)", () => {
  it("moves focus into the dialog and restores it on close", async () => {
    const h = await loadMainJs({
      elementIds: ["action-log", "setup-wizard", "wizard-quiet", "wizard-theme-grid", "wizard-dismiss",
        "wizard-status", "opener"],
      fetch: routeTable({
        "GET /api/setup": { body: { setup_complete: false, themes: [] } },
        "POST /api/setup": { body: { ok: true, setup_complete: true } },
      }),
    });
    const opener = h.elements.get("opener");
    opener.focus();
    await h.api.maybeShowWizard();
    assert.equal(h.elements.get("setup-wizard").hidden, false);
    assert.equal(h.document.activeElement, h.elements.get("wizard-dismiss"));
    await h.api.completeWizard(null);
    assert.equal(h.elements.get("setup-wizard").hidden, true);
    assert.equal(h.document.activeElement, opener);
  });
});

describe("thumbnail grid reuses its tiles across quote changes (no blob leak)", () => {
  const CURRENT_IDS = ["clock", "bucket", "theme", "mode", "quote", "attribution", "matched",
    "current-png", "ban-current", "action-log", "theme-preview-grid"];

  async function gridHarness(themesByCall = [["a", "b", "c"]]) {
    let current = { source_id: "141", line_number: 0 };
    let themeCalls = 0;
    const h = await loadMainJs({
      elementIds: CURRENT_IDS,
      fetch: async (url, init) => {
        if (url === "/api/current") return { status: 200, ok: true, text: async () => JSON.stringify(current) };
        if (url === "/api/themes") {
          const themes = themesByCall[Math.min(themeCalls, themesByCall.length - 1)];
          themeCalls += 1;
          return { status: 200, ok: true, text: async () => JSON.stringify({ themes, preview_themes: themes, effective: themes[0] }) };
        }
        return routeTable({ "GET /api/preview": { body: "thumb" }, "GET /current.png": { body: "png" } })(url, init);
      },
    });
    const setQuote = (n) => { current = { source_id: "141", line_number: n }; };
    return { ...h, setQuote };
  }

  const settle = async () => { for (let i = 0; i < 6; i += 1) await flush(); };
  const created = (calls) => calls.objectUrls.map((_, i) => `blob:stub-${i + 1}`);

  it("N quote changes: same <img> elements, every superseded URL revoked", async () => {
    const h = await gridHarness();
    await h.api.refreshCurrent();
    await h.api.refreshThemePreview();
    h.api.state.themePreviewLoaded = true;
    await settle();
    const grid = h.elements.get("theme-preview-grid");
    const imgs = grid.children.map((c) => c.children[0]);
    for (let n = 1; n <= 5; n += 1) {
      h.setQuote(n);
      await h.api.refreshCurrent();
      await settle();
    }
    assert.deepEqual(grid.children.map((c) => c.children[0]), imgs, "the grid was rebuilt");
    assert.equal(grid.children.length, 3);
    const live = new Set([...imgs.map((i) => i.src), h.elements.get("current-png").src]);
    assert.equal(live.size, 4);
    const revoked = new Set(h.calls.revokedUrls);
    for (const url of created(h.calls)) {
      if (live.has(url)) assert.ok(!revoked.has(url), `live ${url} revoked`);
      else assert.ok(revoked.has(url), `${url} leaked`);
    }
  });

  it("a changed theme list rebuilds the grid and revokes the discarded tiles", async () => {
    const h = await gridHarness([["a", "b"], ["a", "b", "c"]]);
    await h.api.refreshThemePreview();
    await settle();
    const oldSrcs = h.elements.get("theme-preview-grid").children.map((c) => c.children[0].src);
    h.api.state.previewThemes = [];
    await h.api.refreshThemePreview();
    await settle();
    for (const url of oldSrcs) assert.ok(h.calls.revokedUrls.includes(url), `${url} leaked on rebuild`);
    assert.equal(h.elements.get("theme-preview-grid").children.length, 3);
  });

  it("reloads only on-screen tiles; an off-screen tile waits for one fetch, not one per quote", async () => {
    const h = await gridHarness();
    const visible = new Set();
    const observers = [];
    h.sandbox.IntersectionObserver = class {
      constructor(cb) { this.cb = cb; this.targets = []; this.live = true; observers.push(this); }
      observe(el) {
        this.targets.push(el);
        if (visible.has(el)) this.cb([{ isIntersecting: true, target: el }]);
      }
      disconnect() { this.live = false; }
    };
    await h.api.refreshThemePreview();
    const grid = h.elements.get("theme-preview-grid");
    const imgs = grid.children.map((c) => c.children[0]);
    h.api.state.themePreviewLoaded = true;
    await h.api.refreshCurrent();
    await settle();
    visible.add(imgs[0]);
    const previews = () => h.calls.fetches.filter((f) => f.url.startsWith("/api/preview")).length;
    const before = previews();
    for (let n = 1; n <= 4; n += 1) {
      h.setQuote(n);
      await h.api.refreshCurrent();
      await settle();
    }
    assert.equal(previews() - before, 4, "only the visible tile should reload per quote change");
    // Each hidden tile has exactly one live observer waiting.
    for (const img of imgs.slice(1)) {
      const waiting = observers.filter((o) => o.live && o.targets.includes(img));
      assert.equal(waiting.length, 1);
    }
    // Scrolling a hidden tile into view fetches it exactly once.
    const waiter = observers.find((o) => o.live && o.targets.includes(imgs[1]));
    waiter.cb([{ isIntersecting: true, target: imgs[1] }]);
    await settle();
    assert.equal(previews() - before, 5);
  });
});

describe("setup wizard keyboard handling (#292)", () => {
  async function wizardHarness() {
    const h = await loadMainJs({
      elementIds: ["action-log", "setup-wizard", "wizard-quiet", "wizard-theme-grid", "wizard-dismiss",
        "wizard-status", "opener", "wiz-a", "wiz-b"],
      fetch: routeTable({
        "GET /api/setup": { body: { setup_complete: false, themes: [] } },
        "POST /api/setup": { body: { ok: true, setup_complete: true } },
      }),
    });
    const overlay = h.elements.get("setup-wizard");
    const items = [h.elements.get("wiz-a"), h.elements.get("wiz-b"), h.elements.get("wizard-dismiss")];
    overlay.querySelectorAll = () => items;
    overlay.querySelector = () => items[0];
    const key = (k, shiftKey = false) => {
      const ev = { key: k, shiftKey, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
      for (const fn of h.document.listeners.keydown || []) fn(ev);
      return ev;
    };
    return { ...h, overlay, items, key };
  }

  it("Tab from the last control wraps to the first, Shift+Tab from the first to the last", async () => {
    const h = await wizardHarness();
    await h.api.maybeShowWizard();
    assert.equal(h.document.activeElement, h.items[0]);
    const back = h.key("Tab", true);
    assert.ok(back.defaultPrevented);
    assert.equal(h.document.activeElement, h.items[2]);
    const fwd = h.key("Tab");
    assert.ok(fwd.defaultPrevented);
    assert.equal(h.document.activeElement, h.items[0]);
    const mid = h.key("Tab");
    assert.equal(mid.defaultPrevented, false, "ordinary Tab inside the dialog is left to the browser");
  });

  it("pulls focus back in if it has escaped the dialog", async () => {
    const h = await wizardHarness();
    await h.api.maybeShowWizard();
    h.elements.get("opener").focus();
    h.key("Tab");
    assert.equal(h.document.activeElement, h.items[0]);
  });

  it("Escape closes without completing setup and restores focus", async () => {
    const h = await wizardHarness();
    const opener = h.elements.get("opener");
    opener.focus();
    await h.api.maybeShowWizard();
    const ev = h.key("Escape");
    assert.ok(ev.defaultPrevented);
    assert.equal(h.overlay.hidden, true);
    assert.equal(h.document.activeElement, opener);
    assert.equal(h.calls.fetches.filter((f) => f.init.method === "POST").length, 0);
  });

  it("does nothing once the dialog is closed", async () => {
    const h = await wizardHarness();
    await h.api.maybeShowWizard();
    await h.api.completeWizard(null);
    h.elements.get("opener").focus();
    const ev = h.key("Tab");
    assert.equal(ev.defaultPrevented, false);
    assert.equal(h.document.activeElement, h.elements.get("opener"));
  });
});
