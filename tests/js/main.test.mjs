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

import { loadMainJs, makeTab, makePanel, routeTable, StubElement } from "./harness.mjs";

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

const OVERRIDES = {
  ban_source_ids: ["999"],
  boost_source_ids: ["141"],
  preferred_buckets: { h3_exact: 1342 },
  ban_quote_keys: ["141:100"],
};

/** Load main.js wired for the ban flow, capturing what gets POSTed. */
async function banHarness(overrides = OVERRIDES, extra = {}) {
  const posted = [];
  const routes = {
    "GET /api/overrides": { body: overrides },
    "POST /api/overrides": { body: { ok: true } },
    "POST /api/action/rerender": { body: { ok: true } },
  };
  const table = routeTable(routes);
  const harness = await loadMainJs({
    elementIds: ["action-log", "overrides-text", "overrides-status"],
    fetch: async (url, init) => {
      if ((init.method || "GET").toUpperCase() === "POST" && url === "/api/overrides") {
        posted.push(JSON.parse(init.body));
      }
      return table(url, init);
    },
    ...extra,
  });
  return { ...harness, posted };
}

describe("banQuoteKey — read-modify-write of selection_overrides", () => {
  it("preserves every sibling field it did not intend to change", async () => {
    // The regression this guards: reconstructing the payload from scratch and
    // forgetting a key silently wipes the operator's bans/boosts/preferences
    // on the next single-quote ban. The server accepts the payload either way.
    const { api, posted } = await banHarness();
    await api.banQuoteKey("1342:77");

    assert.equal(posted.length, 1);
    assert.deepEqual(posted[0].ban_source_ids, ["999"]);
    assert.deepEqual(posted[0].boost_source_ids, ["141"]);
    assert.deepEqual(posted[0].preferred_buckets, { h3_exact: 1342 });
  });

  it("appends the new key to the existing ban list", async () => {
    const { api, posted } = await banHarness();
    await api.banQuoteKey("1342:77");
    assert.deepEqual(posted[0].ban_quote_keys, ["141:100", "1342:77"]);
  });

  it("de-duplicates a key that is already banned", async () => {
    const { api, posted } = await banHarness();
    await api.banQuoteKey("141:100");
    assert.deepEqual(posted[0].ban_quote_keys, ["141:100"]);
  });

  it("defaults every missing field on a legacy v1 sidecar", async () => {
    // A sidecar written before ban_quote_keys existed has no such key, and an
    // operator may have hand-edited the file down to a bare object.
    const { api, posted } = await banHarness({});
    await api.banQuoteKey("141:482");
    assert.deepEqual(posted[0], {
      ban_source_ids: [],
      boost_source_ids: [],
      preferred_buckets: {},
      ban_quote_keys: ["141:482"],
    });
  });

  it("does nothing at all when the operator cancels the confirm", async () => {
    const { api, posted, calls } = await banHarness(OVERRIDES, { confirmResult: false });
    await api.banQuoteKey("1342:77");
    assert.equal(posted.length, 0);
    assert.equal(calls.fetches.length, 0, "must not even read the sidecar");
  });

  it("ignores an empty key without prompting", async () => {
    const { api, calls } = await banHarness();
    await api.banQuoteKey("");
    assert.equal(calls.confirms.length, 0);
    assert.equal(calls.fetches.length, 0);
  });

  it("aborts without writing when the sidecar cannot be read", async () => {
    // Writing on a failed read would clobber the file with defaults — the
    // worst possible outcome of a transient 500.
    const { api, posted, calls } = await banHarness(OVERRIDES, {
      fetch: routeTable({ "GET /api/overrides": { status: 500, body: { error: "boom" } } }),
    });
    await api.banQuoteKey("1342:77");
    assert.equal(posted.length, 0);
    assert.equal(calls.alerts.length, 1);
    assert.match(calls.alerts[0], /Could not load overrides/);
  });

  it("surfaces a failed save and does not claim success", async () => {
    const { api, calls } = await banHarness(OVERRIDES, {
      fetch: routeTable({
        "GET /api/overrides": { body: OVERRIDES },
        "POST /api/overrides": { status: 409, body: { error: "busy" } },
      }),
    });
    await api.banQuoteKey("1342:77");
    assert.equal(calls.alerts.length, 1);
    assert.match(calls.alerts[0], /Save failed \(409\)/);
  });

  it("re-renders the panel after a successful ban", async () => {
    // Without this the banned quote stays on the eInk panel until the next
    // bucket change — up to an hour of staring at the quote you just rejected.
    const { api, calls } = await banHarness();
    await api.banQuoteKey("1342:77");
    const actions = calls.fetches.filter((f) => f.url === "/api/action/rerender");
    assert.equal(actions.length, 1);
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

  it("does not re-fetch a lazy tab whose first load failed", async () => {
    // The gate latches on *activation*, not on a successful response, so a
    // 500ing endpoint is asked once rather than on every tab flip — an
    // operator idly switching tabs shouldn't hammer a sick appliance. (The
    // flag is set synchronously beside the call rather than in a .then(); for
    // a non-2xx response the two are equivalent, since the loaders resolve
    // normally after rendering their error state.)
    const { api, calls } = await loadMainJs({
      tabs: TAB_NAMES.map(makeTab),
      panels: TAB_NAMES.map(makePanel),
      elementIds: LAZY_TAB_ELEMENT_IDS,
      fetch: routeTable({
        ...LAZY_TAB_ROUTES,
        "GET /api/gaps": { status: 500, body: { error: "boom" } },
      }),
    });
    const gapCalls = () => calls.fetches.filter((f) => f.url.startsWith("/api/gaps")).length;

    api.activateTab("coverage");
    await flush();
    assert.equal(api.state.gapsLoaded, true, "flag must latch even on failure");
    assert.equal(gapCalls(), 1);

    api.activateTab("now");
    await flush();
    api.activateTab("coverage");
    await flush();
    assert.equal(gapCalls(), 1, "a failed first load must not re-fire on every flip");
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
