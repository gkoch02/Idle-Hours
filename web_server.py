#!/usr/bin/env python3
"""Curator web UI for LitClock — local HTTP surface for browsing and tweaking the clock.

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
* Token is checked via the ``X-LitClock-Token`` header only, never a query string,
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

import atomic_io
import pick_quote as pick_quote_module
from buckets import bucket_for_time
from runtime_log import _log

BASE_DIR = Path(__file__).resolve().parent
WEB_ROOT = BASE_DIR / "web"
DEFAULT_COVERAGE_PATH = BASE_DIR / "assets" / "bucket-coverage.json"
DEFAULT_OVERRIDES_PATH = BASE_DIR / "assets" / "selection_overrides.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "output" / "current.png"

TOKEN_HEADER = "X-LitClock-Token"
MAX_BODY_BYTES = 64 * 1024  # Overrides payloads are tiny; cap to stop runaway requests.
BUCKET_PATH_RE = re.compile(r"^/api/bucket/(?P<bucket>h(?:[1-9]|1[0-2])_[a-z_]+)$")
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
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


class _LitClockHTTPServer(ThreadingHTTPServer):
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

OVERRIDES_KEYS = ("ban_source_ids", "boost_source_ids", "preferred_buckets")


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
    if not isinstance(ban, list) or not all(_is_id(x) for x in ban):
        raise ValueError("ban_source_ids must be a list of string/int ids")
    if not isinstance(boost, list) or not all(_is_id(x) for x in boost):
        raise ValueError("boost_source_ids must be a list of string/int ids")
    if not isinstance(preferred, dict):
        raise ValueError("preferred_buckets must be an object")
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
    }


def write_overrides_atomic(path: Path, payload: dict) -> None:
    """Atomically write ``payload`` to ``path``.

    Routes through :mod:`atomic_io` so the on-disk overrides file inherits the
    same tmp → fsync → replace → dir-fsync durability contract as persisted
    runtime state and the attributed corpus.
    """
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

    server_version = "LitClockCurator/1.0"

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
        import run_clock
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
            if path == "/api/current":
                return self._api_current()
            if path == "/api/telemetry":
                return self._api_telemetry(query)
            if path == "/api/coverage":
                return self._api_coverage()
            if path == "/api/themes":
                return self._api_themes()
            if path == "/api/overrides":
                return self._api_overrides_get()
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
        import run_clock
        ctx = self._ctx()
        state = ctx.state
        now = run_clock.current_time_str()
        with state.lock:
            quote_id = state.last_quote_id
            bucket = state.last_bucket or bucket_for_time(now)
            theme = state.last_effective_theme or run_clock.resolve_effective_theme(
                state.theme_arg, now, state.manual_theme,
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
        import litclock_health
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
        entries = litclock_health.load_entries(Path(ctx.telemetry_path).expanduser(), since)
        summary = litclock_health.summarise(entries)
        self._json(HTTPStatus.OK, {"hours": hours, **summary})

    def _api_coverage(self) -> None:
        ctx = self._ctx()
        if not ctx.coverage_path.exists():
            return self._json(HTTPStatus.OK, {"total_rows": 0, "bucket_counts": {}})
        try:
            payload = json.loads(ctx.coverage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": repr(exc)})
        self._json(HTTPStatus.OK, payload)

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
        from theme_names import theme_cycle
        ctx = self._ctx()
        order = list(theme_cycle())
        import run_clock
        now = dt.datetime.now().strftime("%H:%M")
        with ctx.state.lock:
            manual = ctx.state.manual_theme
            theme_arg = ctx.state.theme_arg
            last_effective = ctx.state.last_effective_theme
        effective = last_effective or run_clock.resolve_effective_theme(theme_arg, now, manual)
        self._json(HTTPStatus.OK, {
            "themes": order,
            "theme_arg": theme_arg,
            "manual_theme": manual,
            "effective": effective,
        })

    def _api_overrides_get(self) -> None:
        ctx = self._ctx()
        if not ctx.overrides_path.exists():
            payload = {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}
        else:
            payload = json.loads(ctx.overrides_path.read_text(encoding="utf-8"))
        self._json(HTTPStatus.OK, payload)

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
                # (remove_last_history_entry → atomic rewrite) can't surface a
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
        try:
            top_n = int(query.get("top", ["10"])[0])
        except (TypeError, ValueError):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "top must be int"})
        top_n = max(1, min(top_n, 50))  # cap at 50; dense buckets can exceed 200 candidates
        time_str = query.get("time", [None])[0]
        try:
            candidates = pick_quote_module.select_candidates(
                time_str=time_str, bucket=bucket, top_n=top_n,
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

    def _action_skip(self) -> None:
        import run_clock
        result = run_clock.action_skip(self._ctx().args, self._ctx().state, label="web")
        self._json(_status_from_result(result), result)

    def _action_unskip(self) -> None:
        import run_clock
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
        import run_clock
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
        import run_clock
        result = run_clock.action_quiet(self._ctx().args, self._ctx().state, label="web")
        self._json(_status_from_result(result), result)

    def _action_rerender(self) -> None:
        import run_clock
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
    server = _LitClockHTTPServer((host, port), CuratorHandler, ctx)
    thread = threading.Thread(target=server.serve_forever, name="litclock-web", daemon=True)
    thread.start()
    return server, thread
