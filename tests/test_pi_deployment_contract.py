"""Static contracts for the Raspberry Pi bootstrap and systemd appliance."""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from idle_hours import run_clock

REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap_pi_inky.sh"
UNIT = REPO_ROOT / "ops" / "idle-hours.service.example"
APPLIANCE_CONFIG = REPO_ROOT / "idle_hours" / "assets" / "config.toml.example"


def test_bootstrap_is_valid_bash():
    subprocess.run(["bash", "-n", str(BOOTSTRAP)], check=True)


def test_bootstrap_installs_os_gpio_backend_and_exposes_it_to_venv():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "python3-lgpio" in text
    assert "python3-rpi-lgpio" in text
    assert "--system-site-packages" in text
    assert "import lgpio, RPi.GPIO" in text


def test_bootstrap_uses_spi_without_kernel_chip_select():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "do_spi 0" in text
    assert "dtoverlay=spi0-0cs" in text
    assert "/dev/spidev0.0" in text


def test_systemd_lgpio_runtime_stays_inside_state_directory():
    text = UNIT.read_text(encoding="utf-8")
    assert "WorkingDirectory=/var/lib/idle-hours" in text
    assert "Environment=LG_WD=/var/lib/idle-hours" in text
    assert "ReadWritePaths=%S/idle-hours" in text
    assert "/home/pi/IdleHours/output" not in text


def test_appliance_render_output_lives_in_state_directory():
    config = tomllib.loads(APPLIANCE_CONFIG.read_text(encoding="utf-8"))
    assert config["output"] == "/var/lib/idle-hours/current.png"


def _unit_directive(text: str, key: str) -> str:
    values = [line.split("=", 1)[1].strip() for line in text.splitlines() if line.startswith(f"{key}=")]
    assert len(values) == 1, f"{key}= must appear exactly once in the unit, found {values!r}"
    return values[0]


def test_systemd_working_directory_and_lg_wd_are_the_same_path():
    """lgpio creates its notification FIFO in LG_WD but its Python wrapper opens it
    relative to CWD, so the two directives are one setting spelled twice. A unit
    that moves one without the other starts the loop with a dead button listener."""
    text = UNIT.read_text(encoding="utf-8")
    assert _unit_directive(text, "WorkingDirectory") == "/var/lib/idle-hours"
    assert _unit_directive(text, "Environment") == "LG_WD=/var/lib/idle-hours"


def test_docs_never_tell_operators_to_relocate_working_directory():
    """The install checklists used to list WorkingDirectory= among the paths to
    edit for the local install; following that advice splits it from LG_WD."""
    for doc in (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "pi_setup_inky_impression.md"):
        text = doc.read_text(encoding="utf-8")
        assert "- `WorkingDirectory=`" not in text, f"{doc.name} still lists WorkingDirectory= as an install-path edit"
        assert "/home/pi/IdleHours/output" not in text


def test_systemd_stop_lets_the_in_flight_push_finish():
    """A ``systemctl restart`` used to SIGTERM the display subprocess too (the
    default KillMode=control-group), cutting the panel refresh short about one
    deploy in ten. ``mixed`` signals only the loop, which drains the render;
    the stop timeout has to outlast that drain or systemd SIGKILLs the child
    regardless."""
    text = UNIT.read_text(encoding="utf-8")
    assert _unit_directive(text, "KillMode") == "mixed"
    stop = _unit_directive(text, "TimeoutStopSec")
    assert stop.endswith("s") and stop[:-1].isdigit(), stop
    assert int(stop[:-1]) > run_clock.SHUTDOWN_DRAIN_SECONDS
