"""Tests for runtime_config.load_config and CONFIG_SCHEMA."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from idle_hours import run_clock, runtime_config


def _hhmm(value: str) -> str:
    # Mirror the run_clock._valid_hhmm contract without importing the real
    # one, so a test failure here localises to runtime_config rather than
    # leaking into run_clock import resolution.
    parts = value.split(":")
    h, m = int(parts[0]), int(parts[1])
    if not (len(parts) == 2 and 0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(value)
    return value


class TestLoadConfigNoop:
    def test_none_path_returns_empty(self):
        assert runtime_config.load_config(None) == {}

    def test_missing_file_path_hard_errors(self, tmp_path):
        """A typoed --config should fail fast, not silently fall back.

        The operator opted in by passing the flag; a non-existent file
        is almost certainly a path bug they want to hear about on the
        next `systemctl restart`, not defaults-in-disguise.
        """
        with pytest.raises(SystemExit):
            runtime_config.load_config(tmp_path / "does_not_exist.toml")


class TestLoadConfigHappyPath:
    def test_reads_every_schema_key(self, tmp_path):
        """A TOML file touching every declared key should round-trip cleanly."""
        lines = [
            'render_script = "render_quote.py"',
            'output = "output/current.png"',
            "interval_seconds = 45",
            "width = 800",
            "height = 480",
            'display_script = "display_inky.py"',
            'mode = "production"',
            'theme = "auto"',
            'auto_day_theme = "scholar"',
            'auto_night_theme = "nightvision"',
            "buttons_off = true",
            'shutdown_command = "systemctl poweroff"',
            'startup_image = "assets/goodnight.png"',
            'state_path = "/var/lib/idle-hours/state.json"',
            'telemetry_path = "/var/lib/idle-hours/telemetry.jsonl"',
            "telemetry_retain_days = 30",
            'quiet_start = "23:00"',
            'quiet_end = "07:00"',
            'quiet_image = "assets/goodnight.png"',
            "quiet_off = false",
            'history_path = "/var/lib/idle-hours/history.jsonl"',
            "history_days = 14",
            'web_bind = "127.0.0.1:8080"',
            'web_token = ""',
            'web_token_file = "/var/lib/idle-hours/web.token"',
            'pidfile = "/var/lib/idle-hours/run_clock.pid"',
            'webhook_url = "https://example.test/hook"',
            "webhook_all_events = false",
        ]
        p = tmp_path / "cfg.toml"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg["mode"] == "production"
        assert cfg["interval_seconds"] == 45
        assert cfg["buttons_off"] is True
        assert cfg["quiet_start"] == "23:00"
        assert cfg["telemetry_retain_days"] == 30
        # Every declared key landed.
        assert set(cfg.keys()) == set(runtime_config.CONFIG_SCHEMA.keys())


class TestLoadConfigFailOpen:
    def test_malformed_toml_warns_and_returns_empty(self, tmp_path, capsys):
        p = tmp_path / "cfg.toml"
        p.write_text("this is = not valid = toml", encoding="utf-8")
        assert runtime_config.load_config(p) == {}
        assert "not valid TOML" in capsys.readouterr().err

    def test_empty_file_is_clean_noop(self, tmp_path, capsys):
        # Empty file parses to {} — valid empty TOML table, no warning.
        p = tmp_path / "cfg.toml"
        p.write_text("", encoding="utf-8")
        assert runtime_config.load_config(p) == {}
        assert capsys.readouterr().err == ""

    def test_non_table_root_warns_and_returns_empty(self, tmp_path, capsys, monkeypatch):
        """Defensive branch: tomllib always returns a dict at the root in
        practice, but the loader guards against it anyway so a future
        parser change can't surprise us with a list or scalar."""
        p = tmp_path / "cfg.toml"
        p.write_text("mode = \"production\"\n", encoding="utf-8")
        monkeypatch.setattr(runtime_config.tomllib, "loads", lambda _: [1, 2, 3])
        assert runtime_config.load_config(p) == {}
        assert "root must be a TOML table" in capsys.readouterr().err

    def test_unreadable_file_warns_and_returns_empty(self, tmp_path, capsys, monkeypatch):
        p = tmp_path / "cfg.toml"
        p.write_text("mode = \"debug\"\n", encoding="utf-8")

        def boom(self):
            raise OSError("simulated read failure")
        monkeypatch.setattr("pathlib.Path.read_bytes", boom)
        assert runtime_config.load_config(p) == {}
        assert "unreadable" in capsys.readouterr().err


class TestLoadConfigSchemaValidation:
    def test_unknown_key_warns_and_drops(self, tmp_path, capsys):
        p = tmp_path / "cfg.toml"
        p.write_text('mystery_flag = "nope"\nmode = "production"\n', encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg == {"mode": "production"}
        assert "unknown key 'mystery_flag'" in capsys.readouterr().err

    def test_type_mismatch_warns_and_drops(self, tmp_path, capsys):
        p = tmp_path / "cfg.toml"
        p.write_text('interval_seconds = "60"\n', encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg == {}
        assert "expected int" in capsys.readouterr().err

    def test_bool_is_not_accepted_for_int_slot(self, tmp_path, capsys):
        """Python bools are ints; guard against a stray `true` sneaking in."""
        p = tmp_path / "cfg.toml"
        p.write_text("interval_seconds = true\n", encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg == {}
        assert "got bool" in capsys.readouterr().err

    def test_hhmm_invalid_warns_and_drops(self, tmp_path, capsys):
        p = tmp_path / "cfg.toml"
        p.write_text('quiet_start = "25:99"\nmode = "debug"\n', encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        # mode keeps going; quiet_start dropped.
        assert cfg == {"mode": "debug"}
        assert "quiet_start" in capsys.readouterr().err

    def test_hhmm_valid_passes_through_validator(self, tmp_path):
        p = tmp_path / "cfg.toml"
        p.write_text('quiet_start = "23:30"\n', encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg["quiet_start"] == "23:30"

    def test_choices_valid_passes(self, tmp_path):
        p = tmp_path / "cfg.toml"
        p.write_text('mode = "production"\n', encoding="utf-8")
        cfg = runtime_config.load_config(
            p,
            hhmm_validator=_hhmm,
            choices_map={"mode": ["production", "debug"]},
        )
        assert cfg == {"mode": "production"}

    def test_choices_invalid_warns_and_drops(self, tmp_path, capsys):
        """A typoed ``mode = "produciton"`` must fail at config load, not
        propagate into render subprocesses where it surfaces hours later."""
        p = tmp_path / "cfg.toml"
        p.write_text(
            'mode = "produciton"\n'      # typo
            'theme = "drak"\n'            # typo
            "interval_seconds = 45\n",   # unaffected
            encoding="utf-8",
        )
        cfg = runtime_config.load_config(
            p,
            hhmm_validator=_hhmm,
            choices_map={
                "mode": ["production", "debug"],
                "theme": ["default", "dark", "auto"],
            },
        )
        assert cfg == {"interval_seconds": 45}
        err = capsys.readouterr().err
        assert "'produciton'" in err
        assert "'drak'" in err

    def test_choices_map_is_optional(self, tmp_path):
        """Absent choices_map means no choices check — every syntactically-
        valid value passes, matching the pre-finding-#2 behaviour for
        keys that don't have choices declared."""
        p = tmp_path / "cfg.toml"
        p.write_text('mode = "anything"\n', encoding="utf-8")
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg == {"mode": "anything"}

    def test_auto_day_theme_loads_from_config(self, tmp_path):
        p = tmp_path / "cfg.toml"
        p.write_text(
            'auto_day_theme = "scholar"\nauto_night_theme = "nightvision"\n',
            encoding="utf-8",
        )
        cfg = runtime_config.load_config(
            p, hhmm_validator=_hhmm,
            choices_map={
                "auto_day_theme": ["default", "dark", "scholar", "nightvision"],
                "auto_night_theme": ["default", "dark", "scholar", "nightvision"],
            },
        )
        assert cfg == {"auto_day_theme": "scholar", "auto_night_theme": "nightvision"}

    def test_auto_day_theme_rejects_auto_value(self, tmp_path, capsys):
        """``auto`` is not a valid day/night pick — it would be a config typo,
        not a useful recursion. Mirrors the argparse rejection so config-file
        installs surface the same error as the CLI."""
        p = tmp_path / "cfg.toml"
        p.write_text('auto_day_theme = "auto"\n', encoding="utf-8")
        cfg = runtime_config.load_config(
            p, hhmm_validator=_hhmm,
            choices_map={"auto_day_theme": ["default", "dark", "scholar"]},
        )
        assert cfg == {}
        assert "auto_day_theme" in capsys.readouterr().err

    def test_transient_keys_rejected(self, tmp_path, capsys):
        p = tmp_path / "cfg.toml"
        p.write_text(
            "once = true\nskip_preflight = true\nconfig = \"nested.toml\"\n"
            'mode = "production"\n',
            encoding="utf-8",
        )
        cfg = runtime_config.load_config(p, hhmm_validator=_hhmm)
        assert cfg == {"mode": "production"}
        err = capsys.readouterr().err
        assert "'once'" in err
        assert "'skip_preflight'" in err
        assert "'config'" in err


class TestSchemaSync:
    """Cross-check CONFIG_SCHEMA against the live argparse parser.

    Every argparse dest (minus the documented transient set and the
    ``--config`` flag itself) must have a matching entry in
    ``CONFIG_SCHEMA``. Adding a new ``run_clock`` flag without thinking
    about the config file is the mistake this test catches.
    """

    def _parser_dests(self) -> set[str]:
        # Invoke the real parse_args with no argv so every action's
        # dest lands on the returned Namespace with its default. Walk
        # the Namespace for the dest list.
        saved = sys.argv
        try:
            sys.argv = ["run_clock.py"]
            ns = run_clock.parse_args()
        finally:
            sys.argv = saved
        return set(vars(ns).keys()) - {"config"} - runtime_config.TRANSIENT_KEYS

    def test_every_non_transient_dest_is_in_schema(self):
        dests = self._parser_dests()
        missing = dests - set(runtime_config.CONFIG_SCHEMA.keys())
        assert not missing, (
            f"argparse dests missing from runtime_config.CONFIG_SCHEMA: {sorted(missing)}. "
            "Either add them to the schema (so the config file can set them) "
            "or extend TRANSIENT_KEYS (so they're explicitly refused)."
        )

    def test_schema_has_no_phantom_keys(self):
        # The reverse direction: a key in the schema that argparse no
        # longer exposes means CONFIG_SCHEMA drifted out of sync after
        # a flag rename / removal.
        dests = self._parser_dests()
        phantom = set(runtime_config.CONFIG_SCHEMA.keys()) - dests
        assert not phantom, (
            f"runtime_config.CONFIG_SCHEMA has keys that no longer exist "
            f"on the argparse parser: {sorted(phantom)}"
        )


class TestRunClockIntegration:
    """The real precedence tests — config loaded via run_clock.parse_args."""

    def test_config_seeds_defaults(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.toml"
        p.write_text('interval_seconds = 45\nmode = "production"\n', encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--config", str(p)])
        args = run_clock.parse_args()
        assert args.interval_seconds == 45
        assert args.mode == "production"
        # Untouched argparse defaults stay put.
        assert args.width == 800
        assert args.theme == "default"

    def test_cli_overrides_config(self, tmp_path, monkeypatch):
        p = tmp_path / "cfg.toml"
        p.write_text('interval_seconds = 45\n', encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            ["run_clock.py", "--config", str(p), "--interval-seconds", "30"],
        )
        args = run_clock.parse_args()
        assert args.interval_seconds == 30  # CLI wins

    def test_no_config_keeps_argparse_defaults(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["run_clock.py"])
        args = run_clock.parse_args()
        assert args.interval_seconds == 60
        assert args.mode == "debug"

    def test_missing_config_path_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["run_clock.py", "--config", str(tmp_path / "nope.toml")],
        )
        with pytest.raises(SystemExit):
            run_clock.parse_args()

    def test_empty_string_config_is_noop(self, monkeypatch):
        """``--config ""`` must be treated as "no config file", not as a
        pointer to a zero-length path. ``Path("")`` doesn't exist, so a
        naive implementation would fire the typo-guard SystemExit."""
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--config", ""])
        args = run_clock.parse_args()
        # Argparse defaults survive — nothing came from a config file.
        assert args.mode == "debug"
        assert args.interval_seconds == 60

    def test_choices_bad_config_value_dropped_at_load(self, tmp_path, monkeypatch, capsys):
        """A typoed ``mode`` in config must be dropped at load time so the
        argparse default (``debug``) survives, not silently propagate into
        ``args.mode`` and fail hours later in the render subprocess."""
        p = tmp_path / "cfg.toml"
        p.write_text('mode = "produciton"\n', encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--config", str(p)])
        args = run_clock.parse_args()
        assert args.mode == "debug"   # argparse default, not "produciton"
        assert "not in allowed choices" in capsys.readouterr().err

    def test_shipped_example_loads_through_parse_args(self, monkeypatch):
        """The committed ``idle_hours/assets/config.toml.example`` must load cleanly
        through the *real* parse_args pipeline (not just the loader),
        so type coercion + choices validation are exercised end-to-end.

        Prevents silent rot where someone edits the example into an
        invalid shape (typo in ``mode``, new CONFIG_SCHEMA key that
        doesn't exist in argparse, HH:MM value the validator rejects)
        and operators copy-paste a broken config.
        """
        example = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "config.toml.example"
        assert example.exists(), "missing idle_hours/assets/config.toml.example"
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--config", str(example)])
        args = run_clock.parse_args()
        # Spot-check that the example actually affected the namespace
        # (a silently-empty-returning loader would leave argparse
        # defaults in place and this assert would fail).
        assert args.mode == "production"
        assert args.theme == "auto"

    def test_shipped_example_keys_are_all_in_schema(self):
        """Every uncommented key in the example must be a real schema key.

        Complements ``TestSchemaSync`` (which pins argparse ↔ schema) by
        pinning example ↔ schema. Without this, adding a typoed key to
        the example would warn at runtime but never fail a test."""
        example = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "config.toml.example"
        import tomllib
        raw = tomllib.loads(example.read_text(encoding="utf-8"))
        unknown = set(raw.keys()) - set(runtime_config.CONFIG_SCHEMA.keys())
        assert not unknown, (
            f"idle_hours/assets/config.toml.example has keys not in CONFIG_SCHEMA: "
            f"{sorted(unknown)}"
        )


class TestShippedDefaultsFile:
    """``idle_hours/assets/config.toml.defaults`` is the faithful dump: every key set
    to the argparse default. Copying it verbatim must be a no-op vs. no
    --config at all, so operators who want an explicit, reviewable
    reference can diff it against future upstream bumps.
    """

    def _defaults_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "config.toml.defaults"

    def test_file_exists(self):
        assert self._defaults_path().exists(), "missing idle_hours/assets/config.toml.defaults"

    def test_loads_through_parse_args_without_warnings(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--config", str(self._defaults_path())])
        run_clock.parse_args()
        err = capsys.readouterr().err
        # No warnings means no dropped keys, bad types, or stale entries.
        assert err == "", (
            f"defaults file produced warnings (stale schema?):\n{err}"
        )

    def test_values_match_argparse_defaults(self, monkeypatch):
        """The whole point of this file: every value in it must equal
        what argparse would have returned with no --config at all."""
        # argparse namespace from no-config run
        monkeypatch.setattr("sys.argv", ["run_clock.py"])
        defaults_ns = run_clock.parse_args()

        # argparse namespace from the defaults-file run
        monkeypatch.setattr("sys.argv", ["run_clock.py", "--config", str(self._defaults_path())])
        config_ns = run_clock.parse_args()

        # Ignore ``config`` itself (None vs the file path) — everything
        # else must match.
        d_vars, c_vars = vars(defaults_ns), vars(config_ns)
        for key in d_vars:
            if key == "config":
                continue
            assert d_vars[key] == c_vars[key], (
                f"defaults file diverged for {key!r}: "
                f"argparse default={d_vars[key]!r}, config value={c_vars[key]!r}"
            )

    def test_covers_every_non_none_default(self):
        """Every CONFIG_SCHEMA key whose argparse default is representable
        in TOML (not ``None``) must appear in the file. ``None`` defaults
        are commented out because TOML has no null literal, so they live
        in the file as guidance but not as active keys."""
        import tomllib
        raw = tomllib.loads(self._defaults_path().read_text(encoding="utf-8"))

        # Re-derive the "representable defaults" set from argparse itself.
        import sys
        saved = sys.argv
        try:
            sys.argv = ["run_clock.py"]
            ns = run_clock.parse_args()
        finally:
            sys.argv = saved
        ns_vars = vars(ns)
        expected = {
            key for key in runtime_config.CONFIG_SCHEMA
            if ns_vars.get(key) is not None
        }
        missing = expected - set(raw.keys())
        assert not missing, (
            f"idle_hours/assets/config.toml.defaults missing schema keys with "
            f"non-None argparse defaults: {sorted(missing)}"
        )
