# LitClock

LitClock is a literary clock built from public-domain text. It picks a time-matched quote, renders it as a designed image, and can display it on eInk hardware like the Pimoroni Inky Impression 7.3.

![Current LitClock render preview](output/preview-current-design-v2.png)

## What it does

- picks a quote for the current fuzzy time bucket
- renders it in a centered, editorial QOTD-style layout tuned for the 800×480 Inky Impression 7.3 panel
- highlights the operative time phrase inside the quote
- snaps the final render to the exact Spectra 6 palette for cleaner hardware output
- supports `debug` and cleaner `production` render modes
- can run as a hands-free boot appliance on a Pi

## How it works

In plain English, LitClock was built in stages:

1. **Mine public-domain books for time references**
   - A custom miner scans books, looking for phrases like "quarter past seven" or "ten minutes to midnight".
   - Every hit gets sorted into a fuzzy time bucket rather than a single exact minute.

2. **Clean and score the candidate quotes**
   - Raw matches are often ugly, repetitive, or overly dialogue-heavy.
   - Cleanup scripts trim them into displayable quotes, add metadata, and rank them for readability and fit.

3. **Build a quote set that covers the whole clock**
   - Coverage tools show which time buckets are strong, weak, or empty.
   - When a bucket is missing or poor, targeted mining/backfill scripts hunt for better material.

4. **Pick the best quote for the current time**
   - At runtime, LitClock figures out the current fuzzy bucket, selects the best available quote for that bucket, and falls back nearby if one bucket is still weak or empty.

5. **Render it as a designed display image**
   - The renderer lays out the quote, highlights the matching time phrase, applies the current typography/theme, and prepares a final 800×480 image.

6. **Display it on the eInk panel**
   - On the Pi, the runtime can hand that image to the Inky display script.
   - In appliance mode, the service simply refreshes whenever the fuzzy time bucket changes.

So the short version is: **mine quotes, clean them up, organize them by fuzzy time, pick the best one for now, render it nicely, and push it to the display.**

## Quick start

### Local render test

```bash
python3 run_clock.py --once
```

### Push to Inky once

```bash
python3 run_clock.py --once --display-script display_inky.py --mode production
```

### Run the full loop locally

```bash
python3 run_clock.py --display-script display_inky.py --mode production
```

## Raspberry Pi / Inky setup

If Inky is already installed and working on the Pi, the short path is:

```bash
source ~/.virtualenvs/pimoroni/bin/activate
git clone git@github.com:gkoch02/LitClock.git
cd LitClock
python3 run_clock.py --once
python3 display_inky.py output/current.png
python3 run_clock.py --once --display-script display_inky.py --mode production
```

For full Pi setup and appliance boot instructions, see:

- [pi_setup_inky_impression.md](pi_setup_inky_impression.md)
- [inky_impression_notes.md](inky_impression_notes.md)
- [`litclock.service.example`](litclock.service.example)
- [`bootstrap_pi_inky.sh`](bootstrap_pi_inky.sh)

## Project structure

### Core runtime
- `run_clock.py` - runtime loop, bucket-change refresh behavior, optional display handoff, and service entrypoint
- `render_quote.py` - centered quote rendering, typography, highlighting, and Spectra 6 palette snapping
- `pick_quote.py` - quote selection from the attributed corpus
- `display_inky.py` - thin Inky display bridge

### Corpus and mining tools
- `gutenberg_time_miner.py`
- `clean_display_quotes.py`
- `quality_filter.py`
- `enrich_metadata.py`
- `merge_candidates.py`
- `bucket_coverage.py`
- `fix_substring_time_matches.py`

For mining/backfill work and corpus expansion notes, see:

- [gutenberg_expansion_plan.md](gutenberg_expansion_plan.md)
- `gutenberg_expansion_batch1.sh`
- `gutenberg_expansion_batch2.sh`
- `run_batch2.sh`

## Notes

- The clock refreshes when the fuzzy bucket changes, not every minute.
- The default picker uses the attributed dataset: `output/candidates-attributed.jsonl`.
- Production mode hides debug metadata for a cleaner display.
- The render pipeline now snaps output to the exact Spectra 6 palette, which materially improves color fidelity on hardware.
- The current renderer is tuned specifically for the Pimoroni Inky Impression 7.3 / Spectra 6 800×480 panel.
- One bucket currently remains unfilled (`h3_late_past`), so that time falls back to the nearest neighboring bucket rather than leaving the display blank.
