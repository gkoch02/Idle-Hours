# Pi Setup Guide: Zero 2 W + Inky Impression 7.3 Spectra 6

This is the practical path for turning the literary clock prototype into a personal appliance.

## Hardware

- Raspberry Pi Zero 2 W (headered)
- Pimoroni Inky Impression 7.3 Spectra 6
- microSD card
- appropriate power supply
- Wi-Fi access

## OS baseline

- Raspberry Pi OS **Bookworm or later**
- SSH enabled
- Wi-Fi configured

## One-time Pi prep

Update the system first:

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

## Inky software install

Pimoroni recommends installing via their `inky` repo:

```bash
git clone https://github.com/pimoroni/inky
cd inky
./install.sh
```

Suggested answers during install:
- yes to virtualenv setup
- yes to copying examples
- yes to example dependencies
- docs optional

Then reboot:

```bash
sudo reboot
```

## Verify Inky works

Activate Pimoroni virtualenv:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
```

Run a known-good Spectra example:

```bash
cd ~/Pimoroni/inky/examples/spectra6
python stripes.py
```

If that fails:
- check board seating
- enable `I2C` and `SPI` in `sudo raspi-config`
- reboot and retry

## Literary clock setup

Clone the project:

```bash
git clone git@github.com:gkoch02/LitClock.git
cd LitClock
```

Render once to file:

```bash
python3 run_clock.py --once
```

Push the current render to Inky:

```bash
python3 display_inky.py output/current.png
```

Run full loop with hardware handoff:

```bash
python3 run_clock.py --display-script display_inky.py
```

## Suggested service shape

The loop is good enough to run under `systemd` once the manual path works.

Recommended progression:
1. manual render test
2. manual Inky display test
3. manual combined loop
4. `systemd` service

## Notes

- The renderer currently targets a generic canvas and resizes to panel dimensions in `display_inky.py`.
- That is fine for first bring-up.
- Once the panel is in hand, tune renderer dimensions to the panel's native resolution and visual character.
