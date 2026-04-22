#!/usr/bin/env bash
set -euo pipefail

REPO_URL="git@github.com:gkoch02/LitClock.git"
REPO_DIR="${HOME}/LitClock"

echo "==> Updating apt package lists"
sudo apt update

echo "==> Installing base dependencies"
sudo apt install -y git python3 python3-pip python3-venv python3-dev

echo "==> Cloning Pimoroni Inky installer if needed"
if [ ! -d "${HOME}/inky" ]; then
  git clone https://github.com/pimoroni/inky "${HOME}/inky"
fi

echo
printf '%s\n' "Next step is interactive Pimoroni installer:" \
  "  cd ~/inky && ./install.sh" \
  "Say yes to virtualenv setup and example dependencies." \
  "After that, reboot and come back to continue."
echo
read -r -p "Press Enter to launch Pimoroni installer..."
cd "${HOME}/inky"
./install.sh

echo
printf '%s\n' "==> Installer finished." \
  "Reboot is recommended before trying the display." \
  "After reboot, run this script again with: CONTINUE_AFTER_REBOOT=1 ./bootstrap_pi_inky.sh"
echo

if [ "${CONTINUE_AFTER_REBOOT:-0}" != "1" ]; then
  exit 0
fi

echo "==> Cloning LitClock repo"
if [ ! -d "${REPO_DIR}" ]; then
  git clone "${REPO_URL}" "${REPO_DIR}"
fi

cd "${REPO_DIR}"

echo "==> Rendering once"
python3 run_clock.py --once

echo "==> Attempting first display push"
python3 display_inky.py output/current.png

echo
printf '%s\n' "==> Optional: install systemd unit" \
  "The sample unit at litclock.service.example uses Type=notify + WatchdogSec," \
  "StateDirectory=litclock (creates /var/lib/litclock), and a modest sandbox." \
  "To install:" \
  "  sudo cp litclock.service.example /etc/systemd/system/litclock.service" \
  "  sudo systemctl daemon-reload" \
  "  sudo systemctl enable --now litclock.service" \
  "  systemctl status litclock.service  # should show Active: active (running); notify" \
  "" \
  "Migrating state from ~/.litclock/ to /var/lib/litclock/ (if needed) is documented" \
  "in pi_setup_inky_impression.md under 'Migrating from ~/.litclock/'."
echo
printf '%s\n' "Success path:" \
  "  cd ~/LitClock" \
  "  python3 run_clock.py --display-script display_inky.py"
