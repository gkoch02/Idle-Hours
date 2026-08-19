#!/usr/bin/env python3
"""Curator web UI for Idle Hours — local HTTP surface for browsing and tweaking the clock.

This runs in-process inside ``run_clock.py`` on a background daemon thread, sharing
``RuntimeState.render_lock`` / ``state.lock`` / ``state.ledger_lock`` with the GPIO
button listener so web-driven actions and physical presses can never render-race.
Every mutating POST routes through the same ``_button_render_gate`` (non-blocking
``render_lock.acquire``) that button handlers use, returning 409 when a render is
already in flight rather than queueing.

Design notes:

* Stdlib only — ``http.server.ThreadingHTTPServer`` + ``BaseHTTPRequestHandler``.
  Runtime deps stay at Pillow; no Flask, no ``[web]`` extras group.
* Default bind is ``127.0.0.1:<port>``. Exposing on LAN (``0.0.0.0:<port>``)
  additionally requires a token (``--web-token`` or ``--web-token-file``);
  otherwise ``start_web_server`` refuses to start so an operator can't
  accidentally open a tokenless POST surface on the network.
* Token is checked via the ``X-Idle-Hours-Token`` header only, never a query string,
  since ``BaseHTTPRequestHandler`` logs request paths — a token in the URL would
  leak into journald.
* GETs are never token-gated (telemetry/coverage/current.png aren't sensitive);
  POSTs are gated whenever a token is configured.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hmac
import json
import re
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from idle_hours import apply_content_overrides, atomic_io
from idle_hours import pick_quote as pick_quote_module
from idle_hours.buckets import bucket_for_time
from idle_hours.runtime_log import _log

BASE_DIR = Path(__file__).resolve().parent
WEB_ROOT = BASE_DIR / "web"
DEFAULT_COVERAGE_PATH = BASE_DIR / "assets" / "bucket-coverage.json"
DEFAULT_OVERRIDES_PATH = BASE_DIR / "assets" / "selection_overrides.json"
DEFAULT_CONTENT_OVERRIDES_PATH = BASE_DIR / "assets" / "content_overrides.json"
DEFAULT_RAW_CORPUS_PATH = BASE_DIR / "assets" / "candidates-attributed.jsonl"
DEFAULT_BAKED_DB_PATH = BASE_DIR / "assets" / "quote_database.jsonl"
DEFAULT_OUTPUT_PATH = BASE_DIR / "output" / "current.png"

TOKEN_HEADER = "X-Idle-Hours-Token"
MAX_BODY_BYTES = 64 * 1024  # Overrides payloads are tiny; cap to stop runaway requests.
PREVIEW_MIN_WIDTH = 80
PREVIEW_MIN_HEIGHT = 60
PREVIEW_MAX_WIDTH = 800
PREVIEW_MAX_HEIGHT = 480
BUCKET_PATH_RE = re.compile(r"^/api/bucket/(?P<bucket>h(?:[1-9]|1[0-2])_[a-z_]+)$")
# Per-row content-override key: "<source_id>:<line_number>". Source IDs are
# numeric strings in the corpus (Gutenberg IDs like "141"); line_number is a
# positive int. Matches what ``apply_content_overrides.row_key`` produces.
CONTENT_OVERRIDE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+:\d+$")
LOCALHOST_HOSTS = {"", "127.0.0.1", "localhost", "::1"}


def _parse_bind(bind_str: str) -> tuple[str, int]:
    """Parse ``HOST:PORT`` (or ``:PORT``) into ``(host, port)``.

    An empty host is normalised to ``127.0.0.1`` — callers that want LAN
    exposure must spell it out (``0.0.0.0:8080``).
    """
    if ":" not in bind_str:
        raise ValueError(f"invalid --web-bind {bind_str!r} (expected HOST:PORT)")
    host, port_str = bind_str.rsplit(":", 1)
    if not host:
        host = "127.0.0.1"
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"invalid port {port_str!r} in --web-bind") from exc
    return host, port


def _is_non_localhost_host(host: str) -> bool:
    return host not in LOCALHOST_HOSTS


class WebContext:
    """Bundle of shared state the HTTP handler reaches through ``server.context``.

    Token handling: if ``token_file`` is set, :meth:`current_token` restats the
    file on every request and re-reads it when the mtime changes, so an
    operator rotating the secret can swap the file contents without bouncing
    the server. The inline ``token`` kwarg is the seed value — used when no
    file is configured, or as a fallback when the file is transiently
    unreadable. Without this, a systemctl-managed appliance would have to be
    reloaded just to swap a shared secret.
    """

    def __init__(
        self,
        args: argparse.Namespace,
        state: object,
        token: str = "",
        token_file: str | Path | None = None,
    ):
        self.args = args
        self.state = state
        self._inline_token = (token or "").strip()
        self._token_file: Path | None = Path(token_file).expanduser() if token_file else None
        self._cached_token: str = self._inline_token
        self._cached_token_mtime: float | None = None
        self._token_lock = threading.Lock()
        self.history_path: str | None = args.history_path or None
        self.telemetry_path: str | None = args.telemetry_path or None
        self.overrides_path = _resolve_path(args.overrides) if getattr(args, "overrides", None) else DEFAULT_OVERRIDES_PATH
        self.content_overrides_path = (
            _resolve_path(args.content_overrides)
            if getattr(args, "content_overrides", None)
            else DEFAULT_CONTENT_OVERRIDES_PATH
        )
        self.raw_corpus_path = (
            _resolve_path(args.raw_corpus) if getattr(args, "raw_corpus", None) else DEFAULT_RAW_CORPUS_PATH
        )
        self.baked_db_path = (
            _resolve_path(args.baked_db) if getattr(args, "baked_db", None) else DEFAULT_BAKED_DB_PATH
        )
        self.coverage_path = DEFAULT_COVERAGE_PATH
        self.output_path = _resolve_path(args.output) if getattr(args, "output", None) else DEFAULT_OUTPUT_PATH
        if self._token_file is not None:
            self._refresh_token_from_file(initial=True)

    def _refresh_token_from_file(self, *, initial: bool = False) -> None:
        """Re-read the token file if its mtime changed since the last read.

        ``initial=True`` is used by the constructor so a missing file at
        startup doesn't panic — the inline fallback (or empty) carries. During
        normal operation a file that used to exist and now doesn't is treated
        the same way (we fall back to the inline value and log once); a file
        that's back after a missing window re-caches cleanly.

        Security guard: once a non-empty token has been cached, we refuse to
        downgrade to an empty one via hot-reload. An operator who typos
        ``echo -n "" > tokenfile`` (or runs a tool that truncates before
        writing the new value) would otherwise silently open the POST surface
        on any LAN bind — the startup guard wouldn't re-check. Rotation to a
        different non-empty value is still honoured; rotation back to literally
        empty requires a restart so the startup guard can weigh in.
        """
        assert self._token_file is not None
        try:
            stat = self._token_file.stat()
        except OSError as exc:
            if not initial:
                _log(f"--web-token-file {self._token_file!s} unreadable: {exc!r}; using previous token", err=True)
            return
        if self._cached_token_mtime == stat.st_mtime:
            return
        try:
            contents = self._token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            _log(f"--web-token-file {self._token_file!s} read failed: {exc!r}; using previous token", err=True)
            return
        if not contents and self._cached_token:
            _log(
                f"--web-token-file {self._token_file!s} is now empty; refusing to downgrade to "
                "no-auth at runtime (keeping previous token; restart to explicitly disable).",
                err=True,
            )
            # Update mtime anyway so we don't re-warn on every request until
            # the operator writes a valid replacement.
            self._cached_token_mtime = stat.st_mtime
            return
        self._cached_token = contents
        self._cached_token_mtime = stat.st_mtime
        if not initial:
            _log(f"--web-token-file {self._token_file!s} reloaded (mtime changed)")

    def current_token(self) -> str:
        """Return the live token, reloading from ``--web-token-file`` if it changed.

        Thread-safety: the HTTP handler runs per-request threads, so an mtime
        check + re-read must be serialised or two racing refreshes could
        interleave a partial string into ``_cached_token``. ``threading.Lock``
        held for the stat+read is sufficient — neither call blocks long.
        """
        if self._token_file is None:
            return self._inline_token
        with self._token_lock:
            self._refresh_token_from_file()
            return self._cached_token


def _resolve_path(path_str: str) -> Path:
    """Resolve an operator-supplied path string.

    Relative paths anchor on CWD (the same contract ``run_clock.main()``
    uses for ``--output`` and what every other operator-controlled path
    on the CLI expects). Previously this joined against ``BASE_DIR`` —
    fine when ``BASE_DIR`` was the repo root, but after the v2.x package
    move ``BASE_DIR`` points inside the installed package, so a
    BASE_DIR-relative resolve would bury the operator's render artifact
    inside site-packages and read the wrong (stale or absent) file from
    the curator UI. Bundled defaults still anchor on ``BASE_DIR`` via
    the ``DEFAULT_*_PATH`` module constants — this helper is only
    consulted when the operator supplied an explicit value on the CLI.
    """
    return Path(path_str).expanduser().resolve()


class _IdleHoursHTTPServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` with a ``context`` attribute attached.

    The handler reaches ``args``, ``state``, and the token via ``self.server.context``.
    """

    # Hand a freshly-freed port back to the OS quickly so test suites that bind
    # ephemeral ports in a tight loop don't trip over TIME_WAIT on re-bind.
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler_cls, context: WebContext):
        super().__init__(address, handler_cls)
        self.context = context


# ----------------------------------------------------------------------------
# Validation helpers
# ----------------------------------------------------------------------------

OVERRIDES_KEYS = ("ban_source_ids", "boost_source_ids", "preferred_buckets", "ban_quote_keys")


def _is_id(value: object) -> bool:
    """Accept string/int source IDs, but reject booleans.

    ``bool`` is a subclass of ``int`` in Python, so a bare ``isinstance(..., int)``
    would accept ``True`` and coerce it to ``"True"`` downstream. Explicitly
    exclude it so the on-disk file only ever contains strings and ints.
    """
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int))


def validate_overrides_payload(payload: object) -> dict:
    """Return a cleaned overrides dict, or raise ``ValueError`` with a caller-safe message.

    Accepts the same schema as ``assets/selection_overrides.json`` and nothing
    else — any extra top-level keys are silently dropped so a malformed client
    can't sneak data into the on-disk file.

    Rejects an empty object outright: a ``POST`` whose body is ``{}`` (or absent
    entirely, which ``_read_json_body`` coerces to ``{}``) must not be treated
    as "wipe everything". Callers who really want to clear state must spell it
    out with explicit empty collections — ``{"ban_source_ids": [], ...}``.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object, got {type(payload).__name__}")
    if not any(k in payload for k in OVERRIDES_KEYS):
        raise ValueError(
            "payload must contain at least one of "
            f"{OVERRIDES_KEYS} — refusing to treat empty body as a wipe"
        )
    ban = payload.get("ban_source_ids", [])
    boost = payload.get("boost_source_ids", [])
    preferred = payload.get("preferred_buckets", {})
    ban_quote_keys = payload.get("ban_quote_keys", [])
    if not isinstance(ban, list) or not all(_is_id(x) for x in ban):
        raise ValueError("ban_source_ids must be a list of string/int ids")
    if not isinstance(boost, list) or not all(_is_id(x) for x in boost):
        raise ValueError("boost_source_ids must be a list of string/int ids")
    if not isinstance(preferred, dict):
        raise ValueError("preferred_buckets must be an object")
    if not isinstance(ban_quote_keys, list):
        raise ValueError("ban_quote_keys must be a list of '<source_id>:<line_number>' strings")
    for entry in ban_quote_keys:
        if not isinstance(entry, str) or not CONTENT_OVERRIDE_KEY_RE.match(entry):
            raise ValueError(
                f"ban_quote_keys entry {entry!r} must be of the form '<source_id>:<line_number>'"
            )
    valid_buckets = pick_quote_module.valid_bucket_names()
    for key, value in preferred.items():
        if key not in valid_buckets:
            raise ValueError(f"preferred_buckets key {key!r} is not a valid bucket")
        if not _is_id(value):
            raise ValueError(f"preferred_buckets[{key!r}] must be a string/int source id")
    return {
        "ban_source_ids": [str(x) for x in ban],
        "boost_source_ids": [str(x) for x in boost],
        "preferred_buckets": {k: str(v) for k, v in preferred.items()},
        "ban_quote_keys": list(ban_quote_keys),
    }


def write_overrides_atomic(path: Path, payload: dict) -> None:
    """Atomically write ``payload`` to ``path``.

    Routes through :mod:`atomic_io` so the on-disk overrides file inherits the
    same tmp → fsync → replace → dir-fsync durability contract as persisted
    runtime state and the attributed corpus.
    """
    atomic_io.atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def validate_content_overrides_payload(payload: object) -> dict:
    """Return a cleaned content-overrides dict, or raise ``ValueError``.

    The sidecar is keyed by ``"<source_id>:<line_number>"``; values are partial
    row dicts whose fields are restricted to
    :data:`apply_content_overrides.ALLOWED_FIELDS`. Strict validation here
    keeps malformed UI input from poisoning the next pipeline re-bake — the
    baker's loader is fail-open by design and would silently drop a bad file
    rather than refuse to bake.

    Empty payload (``{}``) is permitted: it represents "wipe every per-row
    override," which is a legitimate operator action (unlike the selection-
    overrides validator, where the keys themselves must be present so a bare
    ``{}`` POST can't accidentally clear the bans/boosts shape).
    """
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object, got {type(payload).__name__}")
    cleaned: dict[str, dict] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not CONTENT_OVERRIDE_KEY_RE.match(key):
            raise ValueError(f"override key {key!r} must be of the form '<source_id>:<line_number>'")
        if not isinstance(value, dict):
            raise ValueError(f"override for {key!r} must be a JSON object")
        unknown = sorted(f for f in value if f not in apply_content_overrides.ALLOWED_FIELDS)
        if unknown:
            raise ValueError(
                f"override for {key!r} has unsupported field(s): {', '.join(unknown)}. "
                f"Allowed: {sorted(apply_content_overrides.ALLOWED_FIELDS)}"
            )
        for field, fval in value.items():
            if field in {"display_quote", "matched_text", "author", "title", "normalized_time"}:
                if not isinstance(fval, str):
                    raise ValueError(f"override {key!r}.{field} must be a string")
            elif field in {"hour", "minute", "quality_score"}:
                if isinstance(fval, bool) or not isinstance(fval, int):
                    raise ValueError(f"override {key!r}.{field} must be an int")
                # Range-check so an out-of-bounds value can't silently re-derive
                # a bogus bucket at bake time (e.g. minute=99 → bucket_for_time
                # "HH:99" KeyErrors and the row gets dropped with no feedback).
                bounds = {"hour": (0, 23), "minute": (0, 59), "quality_score": (0, 100)}[field]
                if not bounds[0] <= fval <= bounds[1]:
                    raise ValueError(
                        f"override {key!r}.{field} must be in [{bounds[0]}, {bounds[1]}]"
                    )
        cleaned[key] = dict(value)
    return cleaned


def write_content_overrides_atomic(path: Path, payload: dict) -> None:
    """Atomically write the per-row content-overrides sidecar."""
    atomic_io.atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------

class CuratorHandler(BaseHTTPRequestHandler):
    """Routes GET/POST against the curator surface.

    Logging is redirected to ``_log`` so the server's request line ends up in
    the same journald stream as the main loop instead of the default stderr
    format. Token enforcement is header-only — a query-string token would end
    up in ``self.path`` and thus the log line.
    """

    server_version = "IdleHoursCurator/1.0"

    def log_message(self, format, *args):
        # Silence the default stderr access log; we already log meaningful events
        # via ``_log`` inside the action functions. The default format dumps the
        # raw request line which, if anyone added a token-in-query-string by
        # mistake, would leak it straight into journald.
        return

    def log_error(self, format, *args):
        # Keep errors visible (but still via our logger, not the default one).
        _log(f"web: {format % args}", err=True)

    # -- convenience helpers --------------------------------------------------

    def _ctx(self) -> WebContext:
        return self.server.context  # type: ignore[attr-defined]

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _not_found(self) -> None:
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _serve_static(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            return self._json(HTTPStatus.NOT_FOUND, {"error": f"missing {path.name}"})
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _check_token(self) -> bool:
        ctx = self._ctx()
        token = ctx.current_token()
        if not token:
            return True
        supplied = self.headers.get(TOKEN_HEADER, "")
        if not supplied or not hmac.compare_digest(supplied, token):
            # Structured auth-failure marker so an operator can grep for
            # "was the web UI hammered with bad tokens?" without scraping
            # journald; remote+path are sufficient to distinguish a fat-
            # finger from a scanner sweep. Strip the query string for the
            # same reason ``log_message`` is silenced — a fat-finger client
            # putting the token in the URL would otherwise plant the secret
            # in the telemetry sidecar.
            self._emit_web_telemetry({
                "mode": "web_auth_fail",
                "remote": self.client_address[0] if self.client_address else "",
                "path": urllib.parse.urlparse(self.path).path,
            })
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "token required"})
            return False
        return True

    def _emit_web_telemetry(self, payload: dict) -> None:
        """Emit one structured web-activity entry via the run_clock telemetry sink.

        Lazy import keeps the module-import graph acyclic (``run_clock``
        imports from ``web_server``-adjacent runtime modules, not vice
        versa at load time) and routes through ``run_clock.append_telemetry``
        so tests can patch the sink in one place.
        """
        ctx = self._ctx()
        if not ctx.telemetry_path:
            return
        from idle_hours import run_clock
        run_clock.append_telemetry(ctx.telemetry_path, payload)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError(f"body too large ({length} > {MAX_BODY_BYTES})")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    # -- dispatch -------------------------------------------------------------

    def do_GET(self):  # noqa: N802 (required by BaseHTTPRequestHandler)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/":
                return self._serve_static(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            if path == "/main.js":
                return self._serve_static(WEB_ROOT / "main.js", "application/javascript; charset=utf-8")
            if path == "/style.css":
                return self._serve_static(WEB_ROOT / "style.css", "text/css; charset=utf-8")
            if path == "/current.png":
                return self._serve_static(self._ctx().output_path, "image/png")
            if path == "/metrics":
                return self._api_metrics()
            if path == "/api/current":
                return self._api_current()
            if path == "/api/telemetry":
                return self._api_telemetry(query)
            if path == "/api/coverage":
                return self._api_coverage()
            if path == "/api/gaps":
                return self._api_gaps(query)
            if path == "/api/themes":
                return self._api_themes()
            if path == "/api/setup":
                return self._api_setup_get()
            if path == "/api/overrides":
                return self._api_overrides_get()
            if path == "/api/content-overrides":
                return self._api_content_overrides_get()
            if path == "/api/search":
                return self._api_search(query)
            if path == "/api/preview":
                return self._api_preview(query)
            if path == "/api/history":
                return self._api_history(query)
            m = BUCKET_PATH_RE.match(path)
            if m:
                return self._api_bucket(m.group("bucket"), query)
            return self._not_found()
        except Exception as exc:  # noqa: BLE001
            _log(f"web GET {path}: {exc!r}", err=True)
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": repr(exc)})

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # Resolve the route FIRST so an unknown path returns 404 before we
        # ask for a token — otherwise a scanner hitting random URLs would be
        # told "401 token required" and learn that the service exists.
        routes = {
            "/api/overrides": self._api_overrides_post,
            "/api/content-overrides": self._api_content_overrides_post,
            "/api/bake": self._api_bake_post,
            "/api/setup": self._api_setup_post,
            "/api/action/skip": self._action_skip,
            "/api/action/unskip": self._action_unskip,
            "/api/action/theme": self._action_theme,
            "/api/action/quiet": self._action_quiet,
            "/api/action/rerender": self._action_rerender,
        }
        handler = routes.get(path)
        if handler is None:
            return self._not_found()
        if not self._check_token():
            return
        try:
            return handler()
        except ValueError as exc:
            # Body/payload validation failure — structured 400 marker so an
            # operator can tell a curl-it-wrong from a real 5xx blow-up.
            self._emit_web_telemetry({
                "mode": "web_error", "status": 400, "path": path, "error": str(exc),
            })
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            _log(f"web POST {path}: {exc!r}", err=True)
            self._emit_web_telemetry({
                "mode": "web_error", "status": 500, "path": path, "error": repr(exc),
            })
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": repr(exc)})

    # -- GET endpoints --------------------------------------------------------

    def _api_current(self) -> None:
        from idle_hours import run_clock
        ctx = self._ctx()
        state = ctx.state
        now = run_clock.current_time_str()
        with state.lock:
            quote_id = state.last_quote_id
            bucket = state.last_bucket or bucket_for_time(now)
            theme = state.last_effective_theme or run_clock.resolve_effective_theme(
                state.theme_arg, now, state.manual_theme,
                current_random_theme=state.current_random_theme,
                **run_clock._auto_theme_kwargs(ctx.args),
            )
            manual_quiet = state.manual_quiet
            manual_theme = state.manual_theme
        payload = {
            "time": now,
            "bucket": bucket,
            "theme": theme,
            "theme_arg": state.theme_arg,
            "manual_theme": manual_theme,
            "manual_quiet": manual_quiet,
            "mode": ctx.args.mode,
            "source_id": quote_id[0] if quote_id else None,
            "line_number": quote_id[1] if quote_id else None,
            "display_quote": quote_id[2] if quote_id and len(quote_id) > 2 else None,
            "matched_text": quote_id[3] if quote_id and len(quote_id) > 3 else None,
        }
        self._json(HTTPStatus.OK, payload)

    def _api_telemetry(self, query: dict) -> None:
        from idle_hours import idle_hours_health
        try:
            hours = int(query.get("hours", ["24"])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "hours must be int"})
        hours = max(1, min(hours, 24 * 30))  # clamp 1h..30d
        ctx = self._ctx()
        if not ctx.telemetry_path:
            return self._json(HTTPStatus.OK, {"hours": hours, "render_count": 0, "error_count": 0,
                                              "render_p50_ms": None, "render_p95_ms": None,
                                              "display_p50_ms": None, "display_p95_ms": None,
                                              "last_error": None, "note": "telemetry disabled"})
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
        entries = idle_hours_health.load_entries(Path(ctx.telemetry_path).expanduser(), since)
        summary = idle_hours_health.summarise(entries)
        self._json(HTTPStatus.OK, {"hours": hours, **summary})

    def _api_metrics(self) -> None:
        """Prometheus text-format scrape endpoint over a 24h window.

        Re-uses :func:`idle_hours_health.load_entries` + :func:`idle_hours_health.summarise`
        so the metric values match exactly what ``idle-hours health --json`` reports;
        no parallel aggregation logic to drift. Window is fixed at 24h because
        Prometheus is responsible for time-windowing on its end (rate(),
        increase()): exposing a configurable window via query string here would
        confuse the scraper, since Prometheus expects counters to be cumulative
        OR a fixed-window gauge.

        Output is the standard ``# HELP`` / ``# TYPE`` text exposition format
        (Prometheus 0.0.4) — no client_python dependency, just stdlib string
        formatting. Counters are exported as ``_total``-suffixed gauges over
        the 24h window because we don't have process-lifetime monotonic
        counters; that's good enough for "is the appliance rendering and is
        the error rate sane" alerting. Histograms are summarised as p50 / p95
        gauges (no native histogram bucket support) — same reason.

        Stays open without auth (matches the rest of the GET surface) so a
        Prometheus scraper running on the same LAN can hit it without
        managing a token. Operators concerned about leaking telemetry to
        the LAN already bind to 127.0.0.1.
        """
        from idle_hours import idle_hours_health
        ctx = self._ctx()
        lines: list[str] = []
        if ctx.telemetry_path:
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
            entries = idle_hours_health.load_entries(Path(ctx.telemetry_path).expanduser(), since)
            summary = idle_hours_health.summarise(entries)
        else:
            # Telemetry disabled: still emit the metric names with zero values
            # so a Prometheus scrape against a fresh appliance doesn't 500 or
            # produce missing-series gaps that confuse rate() on first
            # success.
            summary = {
                "render_count": 0, "error_count": 0, "heartbeat_count": 0,
                "action_count": 0, "press_dropped_count": 0,
                "web_auth_fail_count": 0, "web_error_count": 0,
                "quiet_enter_count": 0, "quiet_exit_count": 0,
                "render_p50_ms": None, "render_p95_ms": None,
                "display_p50_ms": None, "display_p95_ms": None,
                "last_heartbeat_ts": None,
            }

        def metric(name: str, value: float | int | None, help_text: str, mtype: str = "gauge") -> None:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {mtype}")
            # Prometheus convention: missing/null gauge → omit the sample line
            # (HELP/TYPE alone is fine). A literal NaN would also work but
            # alerting rules then have to handle NaN explicitly.
            if value is not None:
                lines.append(f"{name} {value}")

        metric("idle_hours_renders_total", summary.get("render_count", 0),
               "Successful renders in the last 24 hours.", mtype="gauge")
        metric("idle_hours_errors_total", summary.get("error_count", 0),
               "Render / display / runtime errors in the last 24 hours.", mtype="gauge")
        metric("idle_hours_heartbeats_total", summary.get("heartbeat_count", 0),
               "Loop heartbeat pings in the last 24 hours.", mtype="gauge")
        metric("idle_hours_actions_total", summary.get("action_count", 0),
               "Operator actions (button + web) in the last 24 hours.", mtype="gauge")
        metric("idle_hours_press_dropped_total", summary.get("press_dropped_count", 0),
               "Button presses dropped because a render was in flight.", mtype="gauge")
        metric("idle_hours_web_auth_fails_total", summary.get("web_auth_fail_count", 0),
               "Web UI POSTs that failed token auth in the last 24 hours.", mtype="gauge")
        metric("idle_hours_web_errors_total", summary.get("web_error_count", 0),
               "Web UI 4xx/5xx responses in the last 24 hours.", mtype="gauge")
        metric("idle_hours_quiet_enter_total", summary.get("quiet_enter_count", 0),
               "Quiet-hours rising-edge transitions in the last 24 hours.", mtype="gauge")
        metric("idle_hours_quiet_exit_total", summary.get("quiet_exit_count", 0),
               "Quiet-hours falling-edge transitions in the last 24 hours.", mtype="gauge")
        metric("idle_hours_render_p50_ms", summary.get("render_p50_ms"),
               "Median render subprocess duration over the last 24 hours.")
        metric("idle_hours_render_p95_ms", summary.get("render_p95_ms"),
               "p95 render subprocess duration over the last 24 hours.")
        metric("idle_hours_display_p50_ms", summary.get("display_p50_ms"),
               "Median Inky display push duration over the last 24 hours.")
        metric("idle_hours_display_p95_ms", summary.get("display_p95_ms"),
               "p95 Inky display push duration over the last 24 hours.")

        # Heartbeat age is the metric an operator alerts on for "is the loop
        # alive" — equivalent to idle-hours health's --max-heartbeat-age-minutes.
        last_hb = summary.get("last_heartbeat_ts")
        if last_hb:
            try:
                hb_dt = dt.datetime.fromisoformat(last_hb)
                if hb_dt.tzinfo is None:
                    hb_dt = hb_dt.replace(tzinfo=dt.timezone.utc)
                age_seconds = (dt.datetime.now(dt.timezone.utc) - hb_dt).total_seconds()
                metric("idle_hours_last_heartbeat_age_seconds", int(max(0, age_seconds)),
                       "Seconds since the last loop heartbeat. Alerts fire on rising edges.")
            except ValueError:
                pass

        body = ("\n".join(lines) + "\n").encode("utf-8")
        self.send_response(HTTPStatus.OK)
        # Prometheus text format 0.0.4. The scraper picks up the version
        # from the Content-Type and parses accordingly.
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api_coverage(self) -> None:
        ctx = self._ctx()
        if not ctx.coverage_path.exists():
            return self._json(HTTPStatus.OK, {"total_rows": 0, "bucket_counts": {}})
        try:
            payload = json.loads(ctx.coverage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": repr(exc)})
        self._json(HTTPStatus.OK, payload)

    def _api_gaps(self, query: dict) -> None:
        """Return empty / sparse buckets with phrase suggestions for the harvester.

        Reuses :data:`target_sparse_buckets.STATE_TEMPLATES` so the suggested
        phrases match what ``target_sparse_buckets.py`` would actually search
        for if invoked from the CLI — same bucket → same phrase set, so an
        operator who runs the CLI mining job after seeing the UI gap-list gets
        consistent results. ``--threshold`` controls "sparse" (default ≤3
        candidates, matching the bucket-coverage shading).
        """
        from idle_hours import target_sparse_buckets
        ctx = self._ctx()
        try:
            threshold = int(query.get("threshold", ["3"])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "threshold must be int"})
        threshold = max(0, min(threshold, 50))
        if not ctx.coverage_path.exists():
            return self._json(HTTPStatus.OK, {"threshold": threshold, "buckets": []})
        try:
            coverage = json.loads(ctx.coverage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": repr(exc)})
        bucket_counts = coverage.get("bucket_counts") or {}
        gaps: list[dict] = []
        for bucket, count in bucket_counts.items():
            if count > threshold:
                continue
            # bucket like "h7_twenty_to" → ("h7", "twenty_to")
            try:
                hour_part, state = bucket.split("_", 1)
                hour = int(hour_part.lstrip("h"))
            except (ValueError, AttributeError):
                continue
            if state == "exact":
                # The exact-hour bucket is a single canonical phrase per hour
                # ("seven o'clock"); STATE_TEMPLATES doesn't enumerate it
                # because the harvester already saturates it from the
                # bare ``oclock_word`` regex. Emit a hint anyway so the UI can
                # show something for the rare empty exact-hour bucket.
                hour_word = target_sparse_buckets.HOUR_WORDS.get(hour, "")
                phrases = [f"{hour_word} o'clock", f"{hour_word} o’clock"] if hour_word else []
            else:
                templates = target_sparse_buckets.STATE_TEMPLATES.get(state, [])
                hour_word = target_sparse_buckets.HOUR_WORDS.get(hour, "")
                next_hour_word = target_sparse_buckets.HOUR_WORDS.get(
                    (hour % 12) + 1 if hour < 12 else 1, ""
                )
                phrases = [
                    template.format(hour=hour_word, next_hour=next_hour_word)
                    for template, _label in templates
                ]
            gaps.append({"bucket": bucket, "count": count, "phrases": phrases})
        # Sort emptiest-first so the UI naturally surfaces the worst gaps.
        gaps.sort(key=lambda g: (g["count"], g["bucket"]))
        self._json(HTTPStatus.OK, {"threshold": threshold, "buckets": gaps, "total": len(gaps)})

    def _api_setup_get(self) -> None:
        """Return the first-run wizard's status + the values it needs to render.

        Returns ``setup_complete`` (whether the operator has dismissed the
        wizard already), plus a snapshot of the values the UI shows the
        operator: the active theme, the configured quiet hours, and the
        registered theme list. The wizard reads from this single endpoint
        so a freshly-booted appliance hits one URL on first paint to decide
        whether to overlay the wizard or load the normal UI.
        """
        from idle_hours.theme_names import theme_cycle
        ctx = self._ctx()
        with ctx.state.lock:
            setup_complete = ctx.state.setup_complete
            manual_theme = ctx.state.manual_theme
            theme_arg = ctx.state.theme_arg
        self._json(HTTPStatus.OK, {
            "setup_complete": setup_complete,
            "themes": list(theme_cycle()),
            "theme_arg": theme_arg,
            "manual_theme": manual_theme,
            "quiet_start": getattr(ctx.args, "quiet_start", None),
            "quiet_end": getattr(ctx.args, "quiet_end", None),
            "quiet_off": getattr(ctx.args, "quiet_off", False),
            "mode": getattr(ctx.args, "mode", "debug"),
        })

    def _api_setup_post(self) -> None:
        """Mark the first-run wizard complete; optionally apply a chosen theme.

        Body shape: ``{"theme": "<name>"?}``. When ``theme`` is present the
        target is applied via the same ``run_clock.action_theme`` path the
        web dropdown uses, so the panel updates and ``manual_theme`` is
        persisted.

        Failure handling:

        * **Unknown theme** → 400, ``setup_complete`` stays False so the
          wizard reappears with no state mutation.
        * **Render in flight (``error: "busy"``)** → 409, ``setup_complete``
          stays False. Re-flipping setup_complete=True without a successful
          theme apply would close the wizard while the panel still shows
          the old theme — confusing UX. The operator's next click will
          retry once the in-flight render finishes.
        * **Generic 5xx from action_theme** → 500, same rollback. Theme
          handler errors are not the operator's problem to debug from a
          wizard.
        * **Persist failure (state.json write)** → log and swallow; the
          in-memory flag stays True so the current session works. The
          wizard will retry on next reload if state.json is genuinely
          unwritable.

        State-mutation discipline: the ``setup_complete`` flip and the
        ``save_runtime_state`` call are both inside ``state.lock`` to
        match the persist seams in ``runtime_actions.action_theme`` /
        ``action_quiet``. Without this, a near-simultaneous button-press
        snapshot taken between our flip and our save could persist a
        ``setup_complete=False`` over our True, silently re-triggering
        the wizard on next page load.

        Returns the same shape as ``GET /api/setup`` so the UI doesn't need
        a follow-up request to update its in-memory state.
        """
        from idle_hours import run_clock
        ctx = self._ctx()
        body = self._read_json_body()
        target_theme = body.get("theme") if isinstance(body, dict) else None
        if target_theme is not None and not isinstance(target_theme, str):
            return self._json(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "theme must be a string"},
            )
        applied_theme: dict | None = None
        if target_theme:
            applied_theme = run_clock.action_theme(
                ctx.args, ctx.state, label="web", target=target_theme,
            )
            if applied_theme.get("error") == "unknown_theme":
                return self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": f"unknown theme {target_theme!r}"},
                )
            if not applied_theme.get("ok"):
                # Theme apply failed (busy / handler exception). Don't
                # silently flip setup_complete — the operator clicked a
                # theme thumbnail expecting the panel to update, and
                # closing the wizard now hides the failure.
                status = HTTPStatus.CONFLICT if applied_theme.get("error") == "busy" else HTTPStatus.INTERNAL_SERVER_ERROR
                return self._json(status, {
                    "ok": False,
                    "setup_complete": False,
                    "applied_theme": applied_theme,
                })
        # Hold state.lock across both the in-memory flip AND the disk
        # persist. The save_runtime_state call routes through atomic_io
        # so it doesn't block long; serialising it against concurrent
        # snapshotters (button presses, action_theme persists) is the
        # only way to guarantee the wizard's flip lands durably.
        with ctx.state.lock:
            ctx.state.setup_complete = True
            snapshot = ctx.state.snapshot_for_persistence()
            try:
                from idle_hours.runtime_store import save_runtime_state
                save_runtime_state(getattr(ctx.args, "state_path", None), snapshot)
            except Exception as exc:  # noqa: BLE001
                _log(f"web: setup_complete persist failed: {exc!r}", err=True)
                # In-memory flip stays — the current session's UI no longer
                # shows the wizard. Next process restart re-triggers it if
                # state.json is genuinely unwritable; that's a separate,
                # louder failure mode the operator will see in the journal.
        _log("web: first-run setup wizard dismissed")
        self._json(HTTPStatus.OK, {
            "ok": True,
            "setup_complete": True,
            "applied_theme": applied_theme,
        })

    def _api_themes(self) -> None:
        """Expose the theme cycle so the UI dropdown and the Python cycle stay aligned.

        Lazy import via :mod:`theme_names` keeps Pillow off the web-server
        module's load-time import graph, and a broken renderer install
        degrades to the historical pair instead of a 500 that would hide the
        rest of the UI. ``theme_arg`` / ``manual_theme`` / ``effective`` give
        the UI everything it needs to render the dropdown with the current
        value pre-selected without a second request.

        State discipline: snapshot the three fields under ``state.lock`` and
        release it *before* calling ``resolve_effective_theme``. That helper
        imports ``render_quote`` lazily (to keep PIL off the import graph)
        and holding the lock across a module import violates the lock
        discipline in CLAUDE.md even though Python's import lock is
        reentrant. The snapshot is a consistent-enough view: effective
        resolution only uses wall time + the snapshotted values.
        """
        from idle_hours.theme_names import theme_cycle
        ctx = self._ctx()
        order = list(theme_cycle())
        from idle_hours import run_clock
        now = dt.datetime.now().strftime("%H:%M")
        with ctx.state.lock:
            manual = ctx.state.manual_theme
            theme_arg = ctx.state.theme_arg
            last_effective = ctx.state.last_effective_theme
            current_random = ctx.state.current_random_theme
        effective = last_effective or run_clock.resolve_effective_theme(
            theme_arg, now, manual,
            current_random_theme=current_random,
            **run_clock._auto_theme_kwargs(ctx.args),
        )
        self._json(HTTPStatus.OK, {
            "themes": order,
            "theme_arg": theme_arg,
            "manual_theme": manual,
            "effective": effective,
        })

    def _api_overrides_get(self) -> None:
        ctx = self._ctx()
        defaults = {
            "ban_source_ids": [],
            "boost_source_ids": [],
            "preferred_buckets": {},
            "ban_quote_keys": [],
        }
        payload = defaults
        if ctx.overrides_path.exists():
            # Fail open on a corrupt / hand-truncated / non-object file rather
            # than 500-ing the whole overrides editor: a bad save should still
            # let the operator see (and overwrite) the defaults.
            try:
                loaded = json.loads(ctx.overrides_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                # Surface ban_quote_keys to the UI even on legacy files that
                # pre-date it, so the editor doesn't have to special-case the
                # missing key.
                loaded.setdefault("ban_quote_keys", [])
                payload = loaded
        self._json(HTTPStatus.OK, payload)

    def _api_content_overrides_get(self) -> None:
        """Return the per-row content-overrides sidecar.

        Read directly from disk on every request rather than caching: the
        sidecar is operator-edited and small (a few KB at most), and a stale
        cache after a CLI re-edit would surprise an operator who flips between
        SSH and the web UI. ``apply_content_overrides.load_overrides`` is
        already fail-open on a corrupt file — if the sidecar is malformed we
        return ``{}`` rather than 5xx so the UI's editor can still load and the
        operator can replace the bad content.
        """
        ctx = self._ctx()
        payload = apply_content_overrides.load_overrides(ctx.content_overrides_path)
        self._json(HTTPStatus.OK, payload)

    def _api_search(self, query: dict) -> None:
        """Linear search across the raw corpus by text / author / title / bucket.

        Stdlib only, case-insensitive substring match. The corpus is ~3K rows
        so a per-request scan is well under 50 ms — no need for an index. The
        raw corpus is the right source here (not the baked DB) because an
        operator searching "is this quote in the corpus?" wants to find rows
        the baker dropped (low quality, daypart-only) too, so they understand
        why the row isn't appearing.
        """
        ctx = self._ctx()
        q = (query.get("q", [""])[0] or "").strip().lower()
        author = (query.get("author", [""])[0] or "").strip().lower()
        title = (query.get("title", [""])[0] or "").strip().lower()
        bucket = (query.get("bucket", [""])[0] or "").strip()
        try:
            limit = int(query.get("limit", ["50"])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "limit must be int"})
        limit = max(1, min(limit, 500))
        if not (q or author or title or bucket):
            return self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "at least one of q / author / title / bucket is required"},
            )
        if bucket and bucket not in pick_quote_module.valid_bucket_names():
            return self._json(HTTPStatus.BAD_REQUEST, {"error": f"unknown bucket {bucket!r}"})
        results: list[dict] = []
        if not ctx.raw_corpus_path.exists():
            return self._json(HTTPStatus.OK, {"results": [], "total": 0, "note": "raw corpus missing"})
        # Stream so we don't load the full corpus into memory just to scan it.
        from idle_hours.jsonl_io import iter_jsonl
        scanned = 0
        for row in iter_jsonl(ctx.raw_corpus_path):
            scanned += 1
            if bucket and row.get("fuzzy_bucket") != bucket:
                continue
            if q:
                hay = (row.get("display_quote") or "").lower()
                if q not in hay:
                    continue
            if author:
                if author not in (row.get("author") or "").lower():
                    continue
            if title:
                if title not in (row.get("title") or "").lower():
                    continue
            results.append({
                "source_id": row.get("source_id"),
                "line_number": row.get("line_number"),
                "fuzzy_bucket": row.get("fuzzy_bucket"),
                "normalized_time": row.get("normalized_time"),
                "display_quote": row.get("display_quote"),
                "matched_text": row.get("matched_text"),
                "author": row.get("author"),
                "title": row.get("title"),
                "quality_score": row.get("quality_score"),
            })
            if len(results) >= limit:
                break
        self._json(HTTPStatus.OK, {"results": results, "total": len(results), "scanned": scanned})

    def _api_preview(self, query: dict) -> None:
        """Render a PNG of the current quote in the requested theme without committing.

        Returns image/png bytes so the UI can show side-by-side theme thumbnails
        cheaply (one ``<img>`` per theme). Does not touch the panel or the state
        — purely a renderer-only path. Picks the quote at the requested time
        (default: now) just like the live picker would, so what you see matches
        what the clock would actually show in that theme.
        """
        from io import BytesIO

        from idle_hours import render_quote
        ctx = self._ctx()
        theme = (query.get("theme", [""])[0] or "default").strip()
        if theme not in render_quote.THEMES:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": f"unknown theme {theme!r}"})
        time_str = (query.get("time", [""])[0] or "").strip() or dt.datetime.now().strftime("%H:%M")
        # Validate HH:MM shape AND ranges. ``bucket_for_time`` calls
        # ``minute_bucket`` which uses ``((minute + 2) // 5) * 5`` to round —
        # an out-of-range minute (e.g. ``03:99``) silently yields a list
        # index past ``BUCKET_ORDER`` and surfaces as a ``KeyError`` /
        # ``IndexError`` that the GET-handler catches as 500. We want a 400
        # at the API boundary instead so a fat-finger client gets a clear
        # error and the operator's telemetry doesn't fill with bogus 5xx.
        try:
            h_str, m_str = time_str.split(":", 1)
            h = int(h_str)
            m = int(m_str)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError(f"time {time_str!r} out of range (need 00:00–23:59)")
        except (ValueError, AttributeError):
            return self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "time must be HH:MM (00:00–23:59)"},
            )
        try:
            row = pick_quote_module.select_quote(
                time_str=time_str,
                database_path=str(ctx.baked_db_path),
                input_path=str(ctx.raw_corpus_path),
                # Preview must honour the operator's relocated sidecar, or the
                # thumbnail would show a quote the panel will never pick.
                overrides_path=str(ctx.overrides_path),
                history_path=None,  # Preview should be deterministic — don't tie it to ledger state.
            )
        except SystemExit as exc:
            return self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        try:
            mode = (query.get("mode", [""])[0] or "production").strip()
            width = int(query.get("width", [str(ctx.args.width)])[0])
            height = int(query.get("height", [str(ctx.args.height)])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "width/height must be int"})
        # Cap dimensions: preview is used for thumbnails, and full panel size is
        # already enough detail while avoiding slow/high-memory renders from a
        # hostile or buggy client.
        width = max(PREVIEW_MIN_WIDTH, min(width, PREVIEW_MAX_WIDTH))
        height = max(PREVIEW_MIN_HEIGHT, min(height, PREVIEW_MAX_HEIGHT))
        image = render_quote.render(time_str, row, width, height, mode=mode, theme=theme)
        buf = BytesIO()
        try:
            image.save(buf, format="PNG")
        finally:
            image.close()
        data = buf.getvalue()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _api_history(self, query: dict) -> None:
        ctx = self._ctx()
        try:
            limit = int(query.get("limit", ["50"])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "limit must be int"})
        limit = max(1, min(limit, 500))
        entries: list[dict] = []
        if ctx.history_path:
            path = Path(ctx.history_path).expanduser()
            if path.exists():
                # Hold ledger_lock so a concurrent button-A long-press
                # (remove_history_entries → atomic rewrite) can't surface a
                # torn snapshot. The lock is also what append_history callers
                # acquire from the main loop.
                ledger_lock = getattr(ctx.state, "ledger_lock", None)
                lock_ctx = ledger_lock if ledger_lock is not None else contextlib.nullcontext()
                with lock_ctx:
                    with path.open(encoding="utf-8") as handle:
                        for line in handle:
                            line = line.strip()
                            if not line:
                                continue
                            with contextlib.suppress(ValueError):
                                entries.append(json.loads(line))
        entries.reverse()  # newest first
        self._json(HTTPStatus.OK, {"entries": entries[:limit], "total": len(entries)})

    def _api_bucket(self, bucket: str, query: dict) -> None:
        ctx = self._ctx()
        try:
            top_n = int(query.get("top", ["10"])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "top must be int"})
        top_n = max(1, min(top_n, 50))  # cap at 50; dense buckets can exceed 200 candidates
        time_str = query.get("time", [None])[0]
        try:
            candidates = pick_quote_module.select_candidates(
                time_str=time_str, bucket=bucket, top_n=top_n,
                # Deliberately the RAW corpus (see CLAUDE.md): the inspector
                # must show rows the baker dropped so an operator can see why a
                # quote never appears. Overrides come from the same relocated
                # sidecar the picker uses, so override_bonus reads true.
                input_path=str(ctx.raw_corpus_path),
                overrides_path=str(ctx.overrides_path),
                history_path=None,  # UI wants the full corpus view, not the anti-repeat-filtered one
            )
        except SystemExit as exc:
            return self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        self._json(HTTPStatus.OK, {"bucket": bucket, "time": time_str, "candidates": candidates})

    # -- POST endpoints -------------------------------------------------------

    def _api_overrides_post(self) -> None:
        ctx = self._ctx()
        payload = self._read_json_body()
        cleaned = validate_overrides_payload(payload)
        write_overrides_atomic(ctx.overrides_path, cleaned)
        _log(f"web: overrides updated -> {ctx.overrides_path}")
        self._json(HTTPStatus.OK, {"ok": True, "path": str(ctx.overrides_path)})

    def _api_content_overrides_post(self) -> None:
        """Replace the per-row content-overrides sidecar atomically.

        Validation is strict (every key must look like ``"<source_id>:<line_number>"``,
        every value field must be in ``apply_content_overrides.ALLOWED_FIELDS``).
        Writing through here does NOT immediately affect what the panel shows —
        the bake stage that consumes the sidecar runs separately. The UI's
        "Bake now" button (``POST /api/bake``) is the second step.

        We record this as an operator action for audit-grep purposes, but
        deliberately as ``mode="action"`` rather than as a successful
        render-class entry.
        """
        ctx = self._ctx()
        payload = self._read_json_body()
        cleaned = validate_content_overrides_payload(payload)
        write_content_overrides_atomic(ctx.content_overrides_path, cleaned)
        _log(f"web: content overrides updated -> {ctx.content_overrides_path} ({len(cleaned)} entries)")
        self._emit_web_telemetry({
            "mode": "action",
            "action": "content_overrides_save",
            "label": "web",
            "ok": True,
            "entries": len(cleaned),
        })
        self._json(HTTPStatus.OK, {"ok": True, "path": str(ctx.content_overrides_path), "entries": len(cleaned)})

    def _api_bake_post(self) -> None:
        """Re-bake ``assets/quote_database.jsonl`` from the raw corpus + sidecar.

        Runs the bake in-process (it's pure-Python and finishes in <1s for the
        ~3K-row corpus). Then re-applies the content-overrides sidecar so a
        recent ``POST /api/content-overrides`` is reflected in the freshly-baked
        DB without requiring a CLI step.

        The runtime picker reloads the baked DB on every ``select_quote`` call
        (it goes through ``_resolve_corpus`` which reads from disk), so the next
        tick will see the newly-baked rows automatically — no in-memory cache
        invalidation is needed.

        Held under ``state.render_lock`` so a concurrent render isn't reading
        the baked DB while we're swapping it (atomic_write_lines makes the swap
        atomic at the FS level, but the picker's read+score is non-atomic above
        that). Returns 409 (busy) if a render is already in flight rather than
        queueing — the operator can retry.
        """
        from idle_hours import bake_quote_database
        from idle_hours.jsonl_io import iter_jsonl
        ctx = self._ctx()
        state = ctx.state
        # Non-blocking acquire so a long render doesn't pin the HTTP thread.
        if not state.render_lock.acquire(blocking=False):
            return self._json(HTTPStatus.CONFLICT, {"ok": False, "error": "busy"})
        try:
            if not ctx.raw_corpus_path.exists():
                return self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"raw corpus missing at {ctx.raw_corpus_path}"},
                )
            # Re-apply content overrides to a fresh in-memory copy of the raw
            # corpus before baking, so a just-saved ``POST /api/content-overrides``
            # is reflected in the baked DB. Operator workflow: edit row → save
            # overrides → click Bake; both should land on the panel within seconds.
            sidecar = apply_content_overrides.load_overrides(ctx.content_overrides_path)
            rows = list(iter_jsonl(ctx.raw_corpus_path))
            if sidecar:
                rows, applied = apply_content_overrides.apply_overrides(
                    rows, sidecar, overrides_path=str(ctx.content_overrides_path),
                )
            else:
                applied = 0
            # Re-derive fuzzy_bucket from the post-override normalized_time so
            # the baker sees the same buckets it would after a full pipeline run.
            for row in rows:
                normalized = row.get("normalized_time")
                if isinstance(normalized, str) and ":" in normalized:
                    try:
                        row["fuzzy_bucket"] = bucket_for_time(normalized)
                    except (ValueError, KeyError):
                        pass
            baked, stats = bake_quote_database.bake_rows(rows, min_quality=60)
            atomic_io.atomic_write_lines(
                ctx.baked_db_path,
                (json.dumps(row, ensure_ascii=False) for row in baked),
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"web: bake failed: {exc!r}", err=True)
            self._emit_web_telemetry({
                "mode": "action", "action": "bake", "label": "web", "ok": False, "error": repr(exc),
            })
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": repr(exc)})
        finally:
            state.render_lock.release()
        _log(f"web: baked {stats['kept']} rows -> {ctx.baked_db_path}")
        self._emit_web_telemetry({
            "mode": "action", "action": "bake", "label": "web", "ok": True,
            "kept": stats["kept"], "applied": applied,
        })
        self._json(HTTPStatus.OK, {
            "ok": True,
            "path": str(ctx.baked_db_path),
            "kept": stats["kept"],
            "input": stats["input"],
            "applied_overrides": applied,
            "drops": stats["drops"],
            "per_bucket": stats["per_bucket"],
        })

    def _action_skip(self) -> None:
        from idle_hours import run_clock
        result = run_clock.action_skip(self._ctx().args, self._ctx().state, label="web")
        self._json(_status_from_result(result), result)

    def _action_unskip(self) -> None:
        from idle_hours import run_clock
        result = run_clock.action_unskip(self._ctx().args, self._ctx().state, label="web")
        self._json(_status_from_result(result), result)

    def _action_theme(self) -> None:
        # Optional ``{"theme": "scholar"}`` body lets the web dropdown jump
        # straight to a named theme; an empty body (or omitted field) matches
        # the physical button B behaviour and advances one step through the
        # cycle. ``action_theme`` validates the target name and returns
        # ``unknown_theme`` when it isn't registered.
        #
        # Malformed JSON or an oversized body raises ``ValueError`` from
        # ``_read_json_body`` and propagates up to ``do_POST``, which
        # emits a ``mode="web_error"`` telemetry entry and replies 400.
        # We deliberately do NOT catch it here and fall back to ``{}`` —
        # doing that would turn a bad-client error into a silent theme
        # cycle (state mutation on invalid input), which is the bug
        # chatgpt-codex-connector flagged on PR #72. ``_read_json_body``
        # already returns ``{}`` for length=0, so the "no body" cycle
        # path is unaffected.
        from idle_hours import run_clock
        body = self._read_json_body()
        target = body.get("theme") if isinstance(body, dict) else None
        if target is not None and not isinstance(target, str):
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "theme must be a string"})
            return
        result = run_clock.action_theme(
            self._ctx().args, self._ctx().state, label="web", target=target,
        )
        status = HTTPStatus.BAD_REQUEST if result.get("error") == "unknown_theme" else _status_from_result(result)
        self._json(status, result)

    def _action_quiet(self) -> None:
        from idle_hours import run_clock
        result = run_clock.action_quiet(self._ctx().args, self._ctx().state, label="web")
        self._json(_status_from_result(result), result)

    def _action_rerender(self) -> None:
        from idle_hours import run_clock
        result = run_clock.action_rerender(self._ctx().args, self._ctx().state, label="web")
        self._json(_status_from_result(result), result)


def _status_from_result(result: dict) -> int:
    """Map an ``action_*`` result dict to an HTTP status code."""
    if result.get("ok"):
        return HTTPStatus.OK
    if result.get("error") == "busy":
        return HTTPStatus.CONFLICT  # 409 — render already in flight
    return HTTPStatus.INTERNAL_SERVER_ERROR


# ----------------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------------

def start_web_server(
    args: argparse.Namespace,
    state: object,
    *,
    token: str = "",
    token_file: str | Path | None = None,
) -> tuple:
    """Bind and start the curator HTTP server on a daemon thread.

    Returns ``(server, thread)``. Caller should hold the reference for the
    lifetime of the process (or pass it to :func:`run_clock.stop_web_server`
    for a clean teardown in tests). Raises ``ValueError`` when ``--web-bind``
    is malformed, and ``PermissionError`` / ``OSError`` when the port is in
    use — the main loop catches those and keeps rendering.

    Refuses to start when the bind host is not localhost and no effective token
    (either ``token`` or a readable ``token_file``) is provided, so an operator
    can't accidentally put the POST surface on the network. Localhost binds
    with an empty token are fine — loopback is presumed trusted.

    ``token_file`` is restated on every request so rotating the shared secret
    is a single file edit — no ``systemctl reload`` required.
    """
    host, port = _parse_bind(args.web_bind)
    ctx = WebContext(args, state, token=token, token_file=token_file)
    if _is_non_localhost_host(host) and not ctx.current_token():
        raise ValueError(
            f"--web-bind {args.web_bind!r} exposes the UI beyond 127.0.0.1 but no "
            "--web-token / --web-token-file was provided. Either bind to 127.0.0.1 "
            "or set a token before starting the server."
        )
    server = _IdleHoursHTTPServer((host, port), CuratorHandler, ctx)
    thread = threading.Thread(target=server.serve_forever, name="idle-hours-web", daemon=True)
    thread.start()
    return server, thread
