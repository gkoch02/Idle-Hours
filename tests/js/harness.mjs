// Test harness for idle_hours/web/main.js.
//
// main.js is a plain no-build script: no modules, no exports, and it runs
// against globals (document, window, localStorage, fetch). To test the *real*
// file rather than a transcribed copy, it is evaluated inside a `node:vm`
// context wired to a minimal DOM stub.
//
// One wrinkle drives the shape below: top-level `function` declarations become
// properties of the vm's global object, but `const`/`let` bindings live in the
// context's global *lexical* scope and are invisible from outside. A second
// script run in the same context can see both, so it copies the names we need
// onto the global object where the test can reach them.
//
// main.js only calls init() from a DOMContentLoaded listener, so loading it
// has no side effects beyond declarations — the stub records the listener and
// never fires it.

import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
export const MAIN_JS = join(HERE, "..", "..", "idle_hours", "web", "main.js");

// Names lifted out of the lexical scope so tests can drive them. Anything
// added here must exist in main.js — `buildExportBridge` throws on a typo
// rather than silently exporting undefined, so a rename in main.js fails the
// suite instead of turning tests into vacuous no-ops.
const EXPORTED = [
  "state",
  "getToken",
  "setToken",
  "escapeHtml",
  "fmtMs",
  "jsonFetch",
  "promptForToken",
  "activateTab",
  "wireTabs",
  "banQuoteKey",
  "refreshThemes",
  "bucketClass",
  "fireAction",
];

class StubClassList {
  constructor() { this.tokens = new Set(); }
  toggle(name, force) {
    const on = force === undefined ? !this.tokens.has(name) : Boolean(force);
    if (on) this.tokens.add(name); else this.tokens.delete(name);
    return on;
  }
  add(name) { this.tokens.add(name); }
  remove(name) { this.tokens.delete(name); }
  contains(name) { return this.tokens.has(name); }
}

export class StubElement {
  constructor(id = "", tag = "div") {
    this.id = id;
    this.tagName = tag.toUpperCase();
    this.textContent = "";
    this.innerHTML = "";
    this.className = "";
    this.value = "";
    this.hidden = false;
    this.selected = false;
    this.src = "";
    this.dataset = {};
    this.attributes = {};
    this.classList = new StubClassList();
    this.children = [];
    this.listeners = {};
  }
  get lastChild() { return this.children[this.children.length - 1] ?? null; }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k]; }
  appendChild(child) { this.children.push(child); return child; }
  prepend(child) { this.children.unshift(child); return child; }
  removeChild(child) {
    const i = this.children.indexOf(child);
    if (i >= 0) this.children.splice(i, 1);
    return child;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  querySelectorAll() { return []; }
  // Convenience for assertions: every option appended to a <select>.
  get optionValues() { return this.children.map((c) => c.value); }
}

/**
 * Build a sandbox and evaluate main.js inside it.
 *
 * @param {object} opts
 * @param {(url: string, init: object) => Promise<object>} opts.fetch
 *        Stub fetch. Must resolve to `{ status, ok, text() }`.
 * @param {string[]} opts.elementIds  ids getElementById should resolve.
 * @param {object[]} opts.tabs        `.tab` elements for querySelectorAll.
 * @param {object[]} opts.panels      `.tab-panel` elements.
 * @param {boolean} opts.confirmResult what window.confirm returns.
 * @param {string|null} opts.promptResult what window.prompt returns.
 */
export async function loadMainJs(opts = {}) {
  const source = await readFile(MAIN_JS, "utf8");

  const elements = new Map();
  for (const id of opts.elementIds || []) elements.set(id, new StubElement(id));

  const tabs = opts.tabs || [];
  const panels = opts.panels || [];

  const calls = {
    fetches: [],
    alerts: [],
    confirms: [],
    prompts: [],
    replaceState: [],
    intervals: [],
  };

  const storage = new Map();
  const localStorage = {
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: (k) => storage.delete(k),
  };

  const document = {
    _activeElement: null,
    get activeElement() { return this._activeElement; },
    getElementById: (id) => elements.get(id) ?? null,
    createElement: (tag) => new StubElement("", tag),
    querySelectorAll: (sel) => {
      if (sel === ".tab") return tabs;
      if (sel === ".tab-panel") return panels;
      return [];
    },
    addEventListener: (type, fn) => { (document.listeners[type] ||= []).push(fn); },
    listeners: {},
  };

  const location = { hash: opts.hash ?? "" };

  const sandbox = {
    console,
    Date,
    JSON,
    Set,
    Map,
    Array,
    Object,
    Promise,
    String,
    Number,
    Boolean,
    Math,
    URLSearchParams,
    document,
    location,
    localStorage,
    history: {
      replaceState: (...args) => { calls.replaceState.push(args); location.hash = args[2]; },
    },
    setInterval: (fn, ms) => { calls.intervals.push(ms); return 0; },
    clearInterval: () => {},
    setTimeout: (fn, ms) => { return 0; },
    fetch: async (url, init = {}) => {
      calls.fetches.push({ url, init });
      return opts.fetch ? opts.fetch(url, init) : { status: 200, ok: true, text: async () => "{}" };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.confirm = (msg) => {
    calls.confirms.push(msg);
    return opts.confirmResult !== undefined ? opts.confirmResult : true;
  };
  sandbox.alert = (msg) => { calls.alerts.push(msg); };
  sandbox.prompt = (msg) => {
    calls.prompts.push(msg);
    return opts.promptResult !== undefined ? opts.promptResult : null;
  };

  const context = vm.createContext(sandbox);
  new vm.Script(source, { filename: "main.js" }).runInContext(context);

  // Second script: copy lexical `const` bindings onto the global object.
  const bridge = EXPORTED.map(
    (n) => `if (typeof ${n} === "undefined") throw new Error("main.js no longer defines '${n}'");` +
           `globalThis.__t_${n} = ${n};`,
  ).join("\n");
  new vm.Script(bridge, { filename: "bridge.js" }).runInContext(context);

  const api = {};
  for (const n of EXPORTED) api[n] = sandbox[`__t_${n}`];

  return { api, calls, elements, document, location, tabs, panels, storage, sandbox };
}

/** Build a fetch stub from a `{ "METHOD /path": {status, body} }` route table. */
export function routeTable(routes) {
  return async (url, init = {}) => {
    const method = (init.method || "GET").toUpperCase();
    const key = `${method} ${url}`;
    const hit = routes[key] ?? routes[`${method} ${url.split("?")[0]}`];
    if (!hit) return { status: 404, ok: false, text: async () => JSON.stringify({ error: `no route ${key}` }) };
    const status = hit.status ?? 200;
    return {
      status,
      ok: status >= 200 && status < 300,
      text: async () => (typeof hit.body === "string" ? hit.body : JSON.stringify(hit.body ?? {})),
    };
  };
}

/** A `.tab` stub carrying the dataset the nav code reads. */
export function makeTab(name) {
  const el = new StubElement(`tab-btn-${name}`, "button");
  el.dataset.tab = name;
  return el;
}

/** A `.tab-panel` stub. */
export function makePanel(name) {
  return new StubElement(`tab-${name}`, "section");
}
