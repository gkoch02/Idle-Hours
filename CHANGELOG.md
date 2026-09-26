# Changelog

Notable user-facing changes to Idle Hours are recorded here. Releases use
canonical `vMAJOR.MINOR.PATCH` Git tags; the package version omits the leading
`v`.

## [Unreleased]

Add release notes here as changes merge. The release preparation tool moves
these entries under the new dated version heading.

- `idle-hours run --once` now pins its render to the quote it picked, and so
  passes `--pin-quote` / `--pin-matched-text` to the render script as the
  main loop already did. A custom `--render-script` that does not accept
  those flags now fails under `--once` too.
- A pidfile that cannot be created because of the configuration (permission,
  a file where a directory should be) exits 42 and halts the systemd unit;
  transient errors such as a full disk still exit 1 and are retried.
- Button D is now a real wake during quiet hours: the clock keeps ticking
  until the window ends, and skip, un-skip, re-render, the source card and
  theme changes no longer paint a clock quote onto a sleeping panel.
- A manual sleep or wake refreshes the panel once instead of twice, and a
  failed quiet-hours entry is retried rather than leaving the last quote up
  all night.
- `--startup-image` no longer leaves the startup frame on the panel until
  the next bucket change after a restart.
- The source card, its restore and re-render show the quote that is on the
  panel rather than the next-best pick.
- Content overrides can be undone: deleting an entry and pressing "Bake now"
  restores the row. "Bake now" also updates the raw corpus, so the inspector
  and search show the patched text.
- Banning a quote now also bans its textual twins, and the anti-repeat
  history treats twins as the same quote.
- The curator UI sends anti-framing and content-security headers, gates the
  image routes behind the token, bounds connection count and lifetime, and
  reports an asleep refusal as such instead of "busy".
- Coverage (grid, gap finder, snapshot) counts only quotes the panel can
  display, with raw counts alongside.
- Corpus quality: quotation marks stay paired, "am" and "work" are no longer
  penalised as modern schedule text, overlapping time phrases no longer file
  one sentence at two times, "struck one of the fish" is no longer a clock,
  and betting odds no longer fill the ten-to and twenty-to-one buckets.
- `idle-hours bake`, `apply-overrides` and `target-sparse` resolve relative
  paths against the current directory.

## [2.5.0] - 2026-09-24

- Aligned package metadata with the 2.5.0 release line and added CI validation
  that release tags match the version built into the Python package.
