# Corpus pipeline & quote selection

Reference for the build side of the repo (mining, cleaning, scoring,
attribution, overrides, baking) and for the runtime picker that reads its
output (`pick_quote.py`, the selection overrides, the anti-repeat ledger).
This is the one home for these details: `CLAUDE.md` keeps only the invariants
and links here, and the README covers the operator's view of the same files
("Runtime data contract", "Build pipeline notes").

## Pipeline flow

```
Gutenberg texts / local .txt files
  ↓ gutenberg_time_miner.py
candidates-*.jsonl  (multiple runs possible)
  ↓ merge_candidates.py
candidates-merged.jsonl
  ↓ bucket_coverage.py
bucket-coverage.json  ← identifies gaps
  ↓ target_sparse_buckets.py
targeted-candidates.jsonl
  ↓ import_targeted_hits.py + merge_candidates.py
candidates-merged-plus-targeted.jsonl
  ↓ clean_display_quotes.py
candidates-cleaned.jsonl
  ↓ quality_filter.py
candidates-quality.jsonl
  ↓ fix_substring_time_matches.py (legacy; no-op on fresh harvests)
  ↓ fix_legacy_buckets.py           (legacy; no-op on fresh harvests)
  ↓ enrich_metadata.py
candidates-attributed.jsonl
  ↓ apply_content_overrides.py (layer assets/content_overrides.json on top)
assets/candidates-attributed.jsonl    ← raw attributed corpus (curator UI --input)
  ↓ bake_quote_database.py (drop daypart/low-quality, pre-score, per-bucket sort)
assets/quote_database.jsonl           ← pick_quote.py default --database
  ↓ pick_quote.py
JSON quote for requested time
  ↓ render_quote.py (imports pick_quote in-process)
output/current.png  (overwritten per render — stable filename)
  ↓ display_inky.py (optional, Pi-only)
Inky Impression eInk panel
  ↑ run_clock.py orchestrates the render→display loop
```

## Commands

```bash
# Mine a single Gutenberg ebook by ID
idle-hours mine --gutenberg-id 1342 --strict --output output/candidates.jsonl

# Mine multiple IDs
bash scripts/run_batch2.sh

# Mine local text files
idle-hours mine --input ~/books/ --output output/candidates.jsonl

# Merge multiple harvest runs (deduplicates)
idle-hours merge output/run1.jsonl output/run2.jsonl
# → candidates-merged.jsonl + candidates-merged-summary.json

# One-shot "mine + pipeline + merge into live corpus" driver for a curated list
# of clock-precise Gutenberg IDs (gutenberg_dawn_expansion_ids.txt).
# Safe to re-run — downloads cache in data/gutenberg/, merge_candidates dedupes.
bash scripts/run_dawn_expansion.sh

# Analyze which time buckets have few/no quotes. Counts DISPLAYABLE rows
# (quality ≥ 60, not banned — the baker's and picker's own gates); raw
# tallies ride alongside as raw_bucket_counts.
idle-hours coverage output/candidates-merged.jsonl
idle-hours coverage idle_hours/assets/candidates-attributed.jsonl --min-quality 60 \
    --overrides idle_hours/assets/selection_overrides.json \
    --output-json idle_hours/assets/bucket-coverage.json --output-md idle_hours/assets/bucket-coverage.md
# → bucket-coverage.json + bucket-coverage.md

# Search specifically for sparse/empty bucket phrases
idle-hours target-sparse output/bucket-coverage.json
# → targeted-candidates.jsonl

# Convert targeted hits for merging
idle-hours import-targeted output/targeted-candidates.jsonl
# → targeted-candidates-importable.jsonl

# Normalize excerpts into display-ready text
idle-hours clean output/candidates-merged.jsonl
# → candidates-cleaned.jsonl

# Add quality scores and flags
idle-hours quality output/candidates-cleaned.jsonl
# → candidates-quality.jsonl

# Repair rows whose matched_text is a substring of a longer time phrase
# (e.g. "five minutes past two" mis-captured inside "thirty-five minutes past two")
idle-hours fix-substring-times output/candidates-quality.jsonl

# Repair rows left tagged with legacy 8-state bucket names ("just_after",
# "half_pastish", etc.) from the pre-buckets.py drift era; also normalises
# embedded-newline matched_text back to a single clean phrase.
idle-hours fix-legacy-buckets output/candidates-quality.jsonl

# Attach title/author from Gutenberg headers
idle-hours enrich output/candidates-quality.jsonl
# → idle_hours/assets/candidates-attributed.jsonl

# Layer durable hand-curated fixes from the sidecar on top.
# No-op when the sidecar is empty; otherwise patches matching rows in place,
# stamps override_applied=true, and re-derives fuzzy_bucket from any
# time-affecting overrides. Warns on stderr for dangling keys.
idle-hours apply-overrides idle_hours/assets/candidates-attributed.jsonl
# → idle_hours/assets/candidates-attributed.jsonl (raw attributed corpus)

# Final stage: bake the display-ready runtime quote database.
# Drops daypart-only rows and rows below --min-quality, pre-computes the
# nine row-intrinsic score components + source rarity (against the full raw
# corpus so picks stay equivalent) into baked_score, caches
# inferred_quote_minute, and assigns a per-bucket baked_rank. The runtime
# picker reads this file by default and only recomputes the two request-time
# components (minute_penalty, override_bonus) per pick.
idle-hours bake idle_hours/assets/candidates-attributed.jsonl
# → idle_hours/assets/quote_database.jsonl (pick_quote.py default --database)
```

## Data model at a glance

The canonical runtime input is **`idle_hours/assets/quote_database.jsonl`** — the baked, display-ready DB produced by `bake_quote_database.py`. Everything else in `idle_hours/assets/` is either the raw corpus that feeds the baker, a hand-edited sidecar, or a build-time artifact. Use this table to answer "what's source-of-truth vs derived vs per-appliance state?":

The per-file table (role, committed, ships to the Pi, produced by) is the README's [Runtime data contract](../README.md#runtime-data-contract); it is not repeated here.

**These four paths are relocatable (v2.0.x).** `run_clock` exposes `--overrides` / `--content-overrides` / `--raw-corpus` / `--baked-db` (config keys `overrides` / `content_overrides` / `raw_corpus` / `baked_db`), defaulting to the bundled package copies. The appliance preset relocates all four into `/var/lib/idle-hours/`, because the shipped systemd unit's `ProtectSystem=strict` mounts the installed package read-only — with the defaults, `POST /api/overrides`, `POST /api/content-overrides`, and `POST /api/bake` all fail with a read-only-filesystem error (issue #179). `_seed_writable_corpus_paths` copies the bundled file to any relocated path that doesn't exist yet at startup (never overwriting), so the migration is automatic and lossless. Whatever these are set to is threaded to *both* the runtime picker (`_corpus_kwargs` → `peek_quote_id` + the renderer subprocess argv) and the curator UI (`web_server.WebContext` reads the same four Namespace attributes) — splitting them would let the UI write a file the panel never reads.

Four invariants to keep in mind when touching this layer:

1. **Source-of-truth is the raw corpus + `content_overrides.json`.** If you want a row to change, change those. The baked DB is re-derivable from them; changes made directly to `quote_database.jsonl` will be clobbered the next time someone runs the pipeline.
2. **Runtime reads the baked DB.** `run_clock`, `render_quote`, and the `pick_quote` CLI all pass `database_path=DEFAULT_DATABASE_PATH` explicitly. A raw-corpus commit with no matching bake means the new rows are invisible to the appliance — the expand-corpus drivers (`run_dawn_expansion.sh`) include `bake_quote_database.py` as the last step for exactly this reason.
3. **Curator UI reads the raw corpus deliberately.** `/api/bucket` calls `pick_quote.select_candidates` (raw path) so an operator can see rows the baker dropped (daypart-only, quality below floor) and understand *why* a quote never appeared. Switching the curator to the baked DB would regress that visibility — don't.
4. **Every picker default must be an absolute, existing path.** `select_quote` / `select_candidates` previously defaulted `overrides_path` to the bare relative string `"assets/selection_overrides.json"`, which stopped existing when v2.x moved the tree under `idle_hours/`. `load_overrides` fail-opens on a missing file, so every caller relying on the default — including `render_quote.pick_quote`, i.e. the actual runtime render path — silently applied **no** bans, boosts, or preferred buckets: the curator's "Ban this quote" button wrote a ban the panel ignored forever. Both defaults are now `DEFAULT_OVERRIDES_PATH`, and `tests/test_pick_quote.py::TestOverridesPathDefaults` fails any picker default that is relative or non-existent. A CWD-relative default in this layer is always a bug — it resolves differently depending on where the process was started.

## Fuzzy Bucket System

The core abstraction. Each of 12 hours is divided into 12 minute-state buckets (144 total), named `h{HOUR}_{STATE}`. Plus `daypart` buckets (midnight, small_hours, dawn, morning, noon, afternoon, dusk, evening, night) for time references that don't specify an hour.

`buckets.py` is the single source of truth (`BUCKET_ORDER`, `DEFAULT_BUCKET_MINUTES`, `minute_bucket`, `bucket_for_time`, `neighbor_buckets`); `gutenberg_time_miner.py`, `run_clock.py`, `pick_quote.py`, `bucket_coverage.py`, and `fix_substring_time_matches.py` all import from it, so the rounding rule `rounded = ((minute + 2) // 5) * 5` only lives in one place.

| Rounded minute | State |
|---|---|
| 0 | `exact` |
| 5 | `five_past` |
| 10 | `ten_past` |
| 15 | `quarter_past` |
| 20 | `twenty_past` |
| 25 | `twenty_five_past` |
| 30 | `half_past` |
| 35 | `twenty_five_to` |
| 40 | `twenty_to` |
| 45 | `quarter_to` |
| 50 | `ten_to` |
| 55 | `five_to` |

**History:** An earlier revision of `fix_substring_time_matches.py` kept a private copy of the state names in the legacy 8-state form (`just_after`, `early_past`, etc.), which silently produced invalid `fuzzy_bucket` values no downstream consumer could match. The shared `buckets.py` module was extracted specifically to kill that class of drift — avoid reintroducing a second state table.

## Match Types

`gutenberg_time_miner.py` detects time phrases using named-group regexes:
- `digital` — `14:30` format
- `oclock_word` — "three o'clock"
- `quarter_half` — "quarter past six", "half past two", and (issue #301) the hyphenated "half-past ten" and the "quarter after seven" / "half after four" forms, which used to yield no row. `minutes_past_to` also takes the archaic reversed compound "five-and-twenty minutes past seven" (= 07:25, previously mined as 07:20). A minutes-less "ten past two" pattern is deliberately *not* added: "ten to one" is betting odds as often as a time.
- `quarter_to` — "quarter to eight"
- `minutes_past_to` — "ten minutes past five"
- `just_after_before` — "shortly after noon", "almost three"
- `clock_struck` — "the clock struck midnight". A bare `struck N` is accepted only with a striker (clock / watch / bell / chime / chronometer / church / tower / steeple / hour …) within 60 characters on either side, when N is `midnight` / `noon`, or when `o'clock` follows it directly (`struck one o'clock`); otherwise it is the verb ("she struck one of the fish", "struck one as an uncommonly strong dose" — five such rows sat at 01:00 in the baked DB, issue #298). An `o'clock` elsewhere nearby is *not* a striker: `\b` sits between the apostrophe and `clock`, so without an explicit lookbehind every nearby "o'clock" counted as one.
- `daypart` — bare "morning", "dusk" etc. (excluded by `--strict`)

**Overlapping spans are resolved, longest first (issue #298).** The patterns used to run independently over the text, so `oclock_word` also fired *inside* a `just_after_before` or `minutes_past_to` span and the same sentence was filed at two times: "just after nine o'clock" gave 09:03 *and* a wrong 09:00, "nearly one o'clock" 12:57 *and* 01:00 — 111 such pairs in the shipped corpus, which `merge_candidates` cannot collapse because `normalized_time` is in its key, and the wrong-time twin rendered with "one o'clock" bolded while the text said "nearly". `_non_overlapping_matches` collects every pattern's matches, sorts by `(start, -length, pattern order)` and drops any match whose span overlaps an accepted one, so the longer, more specific phrase wins. Candidates are therefore yielded in *text* order rather than pattern order, which is also what `--max-per-file` should count. Both fixes only affect future mines; the committed corpus had the affected rows purged and was re-baked.

Use `--strict` for production runs to reduce false positives (excludes `daypart` and `digital` matches). `--skip-fetch-errors` keeps batch runs alive when a Gutenberg download 404s.

**Known limitation — `digital` matcher drops in-prose times (issue #159, closed won't-fix).** The `digital` pattern's trailing lookahead `(?!\s+[A-Z][a-z])` runs under `re.IGNORECASE`, where `[A-Z]` / `[a-z]` both match any letter — so the lookahead rejects essentially every digital time followed by a word (`"14:30 in the afternoon"` → dropped; only punctuation-trailed times like `"9:15."` survive). **No production impact:** `--strict` excludes the `digital` match type entirely, so the committed corpus / baked DB were never built from digital matches. Left unfixed deliberately — the defect lives in a code path nobody exercises in production, and a fix would require a non-strict re-mine. If the matcher is ever revived for non-strict use, the fix is: (1) scope the trailing-capital lookahead case-sensitively, `(?!\s+(?-i:[A-Z][a-z]))` (valid under `requires-python >= 3.11`), so it only guards Title-Case headings; (2) extend the existing post-match reference guard at `gutenberg_time_miner.py` (`context_probe` → `\b(?:chapter|psalm|verse|book|epistle)\b`) with `section|canto|hymn` plus a leading-only, period-anchored guard for `No.`/`p.`/`pp.` — but **not** bare `no` (it would reject the common word). Note the `context_probe` guard already rejects chapter/psalm/verse independently of the lookahead, so the scoped-flag fix alone does not break the scripture-rejection tests in `tests/test_miner_match_types.py`.

## JSONL Record Schema

Fields accumulate as rows flow through the pipeline:

```
# From gutenberg_time_miner.py
source_path, source_id, match_type, matched_text, quote_text, context_text,
hour, minute, normalized_time, fuzzy_bucket, daypart_bucket, line_number, match_start, match_end

# Added by merge_candidates.py
canonical_quote, canonical_context

# Added by clean_display_quotes.py
display_quote, display_fragment (bool), cleanup_status ("complete_sentence" | "expanded_with_context" | "fragment_fallback" | "empty")

# Added by quality_filter.py
quality_score (0–100), quality_flags (list of penalty reasons)

# Added by enrich_metadata.py
author, title  # parsed from the cached Gutenberg header when available
```

## Deduplication Key

`merge_candidates.dedupe_key` identifies a hit by *where and what it matched*: `(source_id, line_number, matched_text.lower(), normalized_time)`. The same phrase at the same place in the same book is one hit however wide the sentence window around it was cut, and a different phrase or time on the same line is a different hit. On collision, keeps the entry with longer `context_text`. Rows with no `source_id` (local text files) fall back to `(normalized_time, daypart_bucket, canonical_quote)`, where `canonical_quote` is the lowercased, smart-quote-normalised `quote_text`. The earlier key was `(normalized_time, fuzzy_bucket, daypart_bucket, canonical_quote)` — both buckets are *derived* from the time, so a harvest-to-harvest change in the derivation let byte-identical hits through, and `canonical_quote` is the pre-clean window, so two fragments the cleaner later expands to the same sentence were distinct (issue #294). Merge cannot see display text at all (it runs before `clean`), which is why the picker also collapses textual twins at pick time — see "Quote Selection".

## Quality Scoring

`quality_filter.py` starts each row at 100 and applies penalties (see `BAD_PATTERNS` and `score_quote`). Heavy hitters:
- `contains_time_range` (`3:00–5:00`) and `contains_metadata` (copyright/project gutenberg/ebook): −55
- `contains_work_schedule` (schedule text: "working hours", "work shift", "nine to five") and `contains_modern_am_pm` (`am`/`pm` only as a clock suffix after a number; dotted `a.m.`/`p.m.` alone): −45. Both were far looser until issue #296 — `\bwork\b` hit the verb in ordinary prose and a bare `am` hit "I am", which was every one of the 56 am/pm flags in the shipped corpus; between them they kept ~80 good quotes under the bake floor.
- `contains_structural_label` (a *heading* — "Chapter IV", "BOOK 2", all-caps `ACT`/`SCENE` — never the words in prose, and a lone roman "I" only before punctuation so "the book I read" is the pronoun): −35
- `leading_heading` (issue #308): the excerpt still *opens* with a heading the cleaner strips — a bare Roman numeral of two or more letters ("XXXIV. Next morning…", or with no period when a capitalised sentence follows: "XI Emil came home…") or a run of three or more all-caps words before a sentence ("—CONTINUATION OF THE ENIGMA The night wind…"): −35. Defence in depth; `clean_edges` / `strip_heading_prefix` remove both, plus a leading ellipsis, orphan `_` markers, and PRIME / DOUBLE PRIME (tofu in forty bundled faces). `uppercase_heavy` (−15) stays mild on purpose: what it flags after the cleaner is mostly play speaker labels.
- `fragment`: −30, `too_short` (<50 chars) / `too_long` (>260 chars): −20
- Cleanup status other than `complete_sentence` or `expanded_with_context`: −20
- `digit_heavy` (≥6 digits): −25, `uppercase_heavy` (>18% uppercase): −15
- `weak_ending` (no terminal punct/quote): −10
- `unbalanced_quotes` (an odd count of `"`, or `“`/`”` that do not match one for one; single quotes are not checked because `’` is also the apostrophe): −15. Defence in depth behind the cleaner (issue #297): `clean_edges` keeps an edge quotation mark whose partner is inside the text and strips only an unpaired one (a closing mark at the start is always junk), `best_display_quote` prefers a run whose marks pair up over one that starts with the tail of a speech, and the winner has an unpaired edge mark dropped. What survives is a quotation that genuinely runs past the miner's window, which this penalty ranks below a clean alternative. `tests/test_corpus_invariants.py::TestQuotationBalance` caps the count in the baked DB.

Penalty reasons are appended to `quality_flags`. The score is floored at 0.

## Substring-Collision Fix

`fix_substring_time_matches.py` scans `display_quote` for the full pattern `<minute-word> minutes (past|to) <hour-word>`; if the row's stored `matched_text` is a strict substring of that longer phrase, the row's `matched_text`, `hour`, `minute`, `normalized_time`, and `fuzzy_bucket` are rewritten. Writes in-place by default (pass `--output` to redirect).

It also repairs the **quarter/half swallow**: a legacy `oclock_word` row whose quote reads "half-past ten o'clock", "half after eleven o'clock" or "a quarter before ten" but was filed at :00 with only "ten o'clock" bolded. `repair_row` rewrites it to the bare phrase the miner itself would capture (`half-past ten`, 10:30, `quarter_half`; `quarter to/before X` → `quarter_to` with the 12→1 wrap), so its dedupe key collides with a correctly mined twin, and `main()` then drops the repaired row in favour of that twin. It skips a row whose bare phrase also stands alone elsewhere in the quote, and any row whose time fields or display text carry a content override. Run over the committed corpus it repaired 66 rows and dropped 12 as twins; `TestQuarterHalfSwallowedPhrases` in `tests/test_corpus_invariants.py` fences the baked DB against a recurrence.

## Legacy-Bucket Repair

`fix_legacy_buckets.py` is the companion cleanup for rows tagged with the obsolete 8-state names (`just_after`, `early_past`, `quarter_pastish`, `half_pastish`, `late_past`, `just_before`, `quarter_toish`) harvested before `buckets.py` was extracted. For each such row with a valid `hour`/`minute`, it recomputes the canonical `h{hour}_{state}` bucket using the shared `minute_bucket` primitive (handling the top-of-hour rollover when `minute ≥ 58`). It also collapses runs of whitespace in `matched_text` back to a single space so phrases captured across a source line break (`"towards\ndusk"`) stay stored as a single clean phrase. `pick_quote.load_rows` already re-derives `fuzzy_bucket` from `normalized_time` so the stale values were not visibly broken at runtime, but storage should match the canonical schema so any future consumer reading `fuzzy_bucket` directly sees correct values and `merge_candidates` dedup keys stay stable. Writes in-place by default.

## Metadata Enrichment

`enrich_metadata.py` walks each row's `source_id`, opens the cached `data/gutenberg/pg<id>.txt`, and scans the first 120 lines for `Title: ` and `Author: ` headers. Results are cached per `source_id` so each file is parsed once. Fills `title`/`author` only when missing — existing values on a row are preserved. Output: `idle_hours/assets/candidates-attributed.jsonl`, consumed by `apply_content_overrides.py` (the next stage) and then by `pick_quote.py`.

## Content Overrides (`idle_hours/assets/content_overrides.json`)

Per-row sidecar for durable hand-curated fixes, applied by `apply_content_overrides.py` as the final pipeline stage on top of `idle_hours/assets/candidates-attributed.jsonl`. Exists because earlier revisions accumulated growing repair scripts (`fix_substring_time_matches.py`, `fix_legacy_buckets.py`) that patched *derivable* artifacts in place — any subsequent miner re-run would silently clobber the patch, so the same display bug could resurrect later. The sidecar decouples hand curation from pipeline regeneration: the fix lives here, and every re-run of the pipeline ends by re-applying it.

Keyed by `"<source_id>:<line_number>"` → partial row dict:

```json
{
  "141:482":  {"display_quote": "…"},
  "1342:99":  {"matched_text": "half past two", "normalized_time": "02:30"}
}
```

Allowed override fields: `display_quote`, `matched_text`, `author`, `title`, `quality_score`, `hour`, `minute`, `normalized_time`. Unknown fields are ignored with a stderr warning. After patching, `fuzzy_bucket` is re-derived from the post-override `normalized_time` (and `normalized_time` itself is re-derived from `hour`/`minute` when those are overridden without an explicit `normalized_time`; conversely an overridden `normalized_time` re-derives whichever of `hour`/`minute` the entry leaves out — issue #305), so time-affecting overrides stay internally consistent. Ill-typed values — a non-int or out-of-range `hour` / `minute` / `quality_score`, a `normalized_time` that is not zero-padded `HH:MM` — are skipped per field with a stderr warning rather than written. A replaced `display_quote` also re-runs the classification the old text went through: `display_fragment` (via the cleaner's `looks_fragment`), `cleanup_status`, `quality_flags` and — unless the entry sets it explicitly, or sets it to a malformed value — `quality_score` (via `quality_filter.score_quote`) are re-derived from the new text and recorded in `override_originals` like any other derived field, so removing the entry restores the fragment-era values. Before this a curator-trimmed sentence kept the score and fragment flag of the text it replaced: four clean quotes sat under the bake floor, and even once lifted they ranked with a fragment penalty. Patched rows are stamped `override_applied: true` for downstream debugging.

**Overrides are reversible (`override_originals`).** The stage writes its output back over its input, and so does the curator's "Bake now", so an override ends up baked into the raw corpus. Without a record of what it replaced, deleting a sidecar entry and re-running changed nothing — the edit was permanent, and unrecoverable on an appliance whose relocated corpus has no git history. The first time the sidecar writes a field, the row's previous value goes into `override_originals` (a derived `normalized_time` is recorded too); a field the sidecar no longer writes is restored from it, and a row left with no originals loses both `override_originals` and `override_applied`. Rows patched before the ledger existed record their already-patched value as the original, because the true one is gone. A sidecar entry that is present but not an object leaves its row untouched: treating a typo like a deletion would silently revert the override. The baker strips `override_originals` from the baked DB (`_RAW_ONLY_FIELDS`); the runtime never reads it.

`apply_content_overrides.apply_overrides` warns on stderr for **dangling keys** — sidecar entries that don't match any row in the input, typically caused by a typo or a row that later got dedup-dropped or filtered out. That's the intended replacement for *silent no-op* editing of `candidates-attributed.jsonl` by hand: fixes either apply (and are stamped) or loudly don't (and are logged).

**Fail-open loading, atomic writeback.** `load_overrides` catches `OSError` / `ValueError` / `JSONDecodeError` and a non-object root, emits one stderr warning, and returns `{}` so an editor-crash-truncated `content_overrides.json` doesn't abort the entire bake — worst case the picker runs with no sidecar patches applied. When `--output` is omitted (the default), output equals input, so `main` writes through `atomic_io.atomic_write_lines` (sibling-tmp → fsync → `os.replace` → dir-fsync). A crash mid-writeback leaves the existing `idle_hours/assets/candidates-attributed.jsonl` byte-identical instead of truncating the picker's runtime corpus.

**Soft discipline:** if you find yourself overriding more than a handful of rows for the same reason, that's a signal the upstream stage has a bug — push the fix into the miner / cleaner / quality filter rather than accumulating per-row patches.

**Curator UI editing.** As of v2 the sidecar is editable from the web UI via `GET /api/content-overrides` (returns the raw dict) and `POST /api/content-overrides` (validated atomic rewrite). The UI's "Bake now" button (`POST /api/bake`) runs `bake_quote_database.bake_rows` in-process so a save-then-bake round-trip drops the new excerpts onto the panel within seconds without an SSH session. Validation rejects unknown fields and bad key shapes with a 400; the same `apply_content_overrides.ALLOWED_FIELDS` set is the single source of truth.

**Legacy fix scripts.** `fix_substring_time_matches.py` and `fix_legacy_buckets.py` are retained as one-shot migration tools for corpus rows harvested by earlier miner revisions (the miner now collapses `matched_text` whitespace and the shared `buckets.py` prevents legacy 8-state names). Fresh mines should make them no-ops; see each script's docstring.

## Baked Quote Database (`idle_hours/assets/quote_database.jsonl`)

Final pipeline stage output, produced by `bake_quote_database.py` from the raw attributed corpus. This is the *display-ready database* the runtime picker consults by default; `candidates-attributed.jsonl` stays on disk as the raw corpus and is used by the curator UI's bucket inspector (`/api/bucket`).

**Why it exists.** Of the twelve score components in `pick_quote.score_row`, nine are row-intrinsic (`fragment`, `cleanup`, `metadata`, `dialogue`, `opening`, `source_bonus`, `quality`, `length_exactness`, `length_tiebreak`) and one more — `source_rarity_penalty` — depends only on the corpus as a whole; only `minute_penalty` and `override_bonus` actually change per request. Computing those ten components once at bake time, shipping them inline on each row, and dropping rows the picker would have filtered anyway (daypart-only rows with no `fuzzy_bucket`, rows below `--min-quality`) makes the runtime pick deterministic, smaller, and git-diffable: a regression in the scorer shows up as a diff to the committed database, not a silent drift in what the clock displays.

**Row schema additions.** Every baked row keeps its original fields plus:

- `baked_score` — list of ten ints in `BAKED_SCORE_COMPONENTS` order (see `bake_quote_database.py` and `pick_quote.py`). Drift between the two constant lists is how pick-equivalence silently breaks, so they're cross-checked in tests.
- `inferred_quote_minute` — what minute this row claims, cached once so `minute_penalty` doesn't re-run the regex sweep per tick.
- `baked_rank` — 0-based ordinal within the row's bucket after sorting ascending by `baked_score`. Purely for curator readability (the file is `(bucket, rank)`-ordered on disk); the runtime picker still sorts again once it has the two request-time components.
- `schema_version` — integer marker matching `BAKED_SCORE_SCHEMA_VERSION` in `bake_quote_database.py` / `pick_quote.py`. Bump whenever `BAKED_SCORE_COMPONENTS` changes (order, length, or semantics). `pick_quote._resolve_corpus` reads this field on the first baked row it encounters; a mismatch (stale `quote_database.jsonl` paired with a freshly `git pull`-ed `pick_quote.py`, or vice versa) triggers a fallback to the raw corpus with a stderr warning instead of silently scoring against a mis-aligned tuple. A baked DB pre-dating the field is treated as version 0 so upgrades surface loudly on first boot.

**Rarity is baked against the raw corpus**, not the baked subset — otherwise a source whose low-quality rows get dropped at bake time would count lower in the baked rarity than in the live one, and pick-equivalence between the two paths would break for that source's surviving rows. `tests/test_bake_quote_database.TestBakeRows::test_rarity_uses_full_input_corpus` pins this.

**Runtime lookup.** `pick_quote.select_quote` reads `idle_hours/assets/quote_database.jsonl` by default. If the file is missing, empty or schema-mismatched it falls back to the raw corpus with a stderr warning, so a bad bake degrades instead of crashing the loop. The warning fires once per version of the file, not once per pick (issue #234): the schema verdict is cached in `_SCHEMA_VERDICT_CACHE` on the same `(st_mtime_ns, st_size)` stamp the row cache uses, and the missing/empty cases latch on the path in `_DEGRADED_WARNED`. Two rules keep that correct:

- **Cache the verdict under the stamp the rows were loaded with.** `_load_rows_with_stamp` returns `(rows, stamp)` together and `_schema_mismatch_cached` takes that stamp. Re-statting would let a "Bake now" landing between load and stat cache an old verdict under the new file's stamp, and the latch would then hide it until the file changed again.
- **Any branch where the file exists clears the missing/empty latch.** That includes the schema-mismatch branch, so missing, then a bad bake, then missing again still warns each time.

`clear_corpus_cache()` resets both caches and the latch for tests. A process-local latch cannot cover the render subprocess, which starts with empty globals, so `run_clock` sets `pick_quote.SUPPRESS_WARNINGS_ENV` (`IDLE_HOURS_SUPPRESS_CORPUS_WARNINGS=1`) in its environment; the parent has already warned during its own peek. Only the exact string `"1"` suppresses, and a standalone `idle-hours render` still warns. It is an environment variable rather than a flag because an operator's own `--render-script` would reject an unknown flag and send the appliance into render backoff.

`score_row` detects `baked_score in row` and short-circuits into `compose_baked_score_key`, which interleaves the two request-time components back into the pre-baked tuple at the correct positions to reproduce `score_row`'s original 12-tuple layout exactly. `tests/test_bake_equivalence.py` sweeps all 144 canonical buckets and asserts baked and raw picks return the same `(source_id, line_number)`.

**What's still live, not baked.** `selection_overrides.json` (bans / boosts / preferred buckets) stays runtime, because the web UI rewrites it via `POST /api/overrides` — re-baking on every edit would block the UI on a CLI run. Bans are a cheap post-filter; boost/preferred bonuses fold into the `override_bonus` position of the sort key. The anti-repeat history ledger is also runtime (it mutates on every render).

**When to re-bake.** Any time `idle_hours/assets/candidates-attributed.jsonl` changes — expand-corpus drivers like `run_dawn_expansion.sh` already run `bake_quote_database.py` as the last pipeline step, and the git commit it suggests includes `idle_hours/assets/quote_database.jsonl` alongside the raw corpus and coverage snapshot. A raw-corpus commit without a matching baked-DB commit means the picker will happily ignore the newly added quotes until the next bake.

## Quote Selection (`pick_quote.py`)

Default database: `idle_hours/assets/quote_database.jsonl` (the baked DB — see "Baked Quote Database" above); raw-corpus fallback `idle_hours/assets/candidates-attributed.jsonl` via `--input`. Rows below `--min-quality` (default 60) are filtered out before scoring (a no-op on baked rows since the baker already enforces the floor); banned `source_id`s (from `selection_overrides.json`) are dropped entirely.

Candidates in a bucket are ranked by a long lexicographic tuple (lower is better at every position):

```
(fragment_penalty,           # 0 if display_fragment is False, else 1
 cleanup_penalty,             # 0 if cleanup_status in {"complete_sentence", "expanded_with_context"}, else 1
 minute_penalty,              # abs(requested_minute - inferred_quote_minute); 99 if either is None
 metadata_bonus,              # -3 both author+title, -1 one, +2 neither
 dialogue_penalty,            # +2 if text contains "he said" / "she said" / etc.
 opening_penalty,             # +2 weak opener (and/but/so/…), +1 pronoun opener
 source_bonus,                # +1 if no source_id
 override_bonus,              # -5 preferred_buckets[bucket] hit, -3 boost_source_ids hit
 -quality_score,              # higher quality wins
 length_penalty + exactness_bonus,
                              # |len(display_quote) - 140|, +80 cliff when len < 60
                              # (defence-in-depth so stubbornly short quotes lose to
                              # any reasonable-length alternative in-bucket), plus:
                              #   -2 for "five/ten minutes to" or "fifty-five minutes past"
                              #   -1 for "quarter"/"half" matches
 source_rarity_penalty,       # count of this row's source_id in the full corpus;
                              # ties between top-scored candidates go to rarer sources
 len(display_quote))          # final tiebreak
```

If no candidate in the target bucket qualifies, it walks outward through sibling minute-states of the same hour in alternating ±distance order (see `neighbor_buckets`); the chosen bucket is returned as `resolved_bucket` with `used_fallback: true`.

Among equally top-scoring rows, a seeded `random.Random(seed)` picks one so results are stable for a given `--seed`.

## Selection Overrides (`idle_hours/assets/selection_overrides.json`)

A small editable JSON doc consulted by `pick_quote.py` (its default `--overrides` path):

```json
{
  "ban_source_ids": [],        // source_ids excluded entirely
  "boost_source_ids": [],      // −3 in the ranking tuple
  "preferred_buckets": {},     // { "h3_late_past": 12345 } → that source_id wins in that bucket (−5)
  "ban_quote_keys": []         // ["141:482", ...] — per-row permanent bans (v2)
}
```

IDs are compared as strings. Edit this file rather than editing the scorer when you want to manually curate a specific bucket. `pick_quote.load_overrides` warns on stderr if any `preferred_buckets` key is not a valid `h{1..12}_{state}` bucket, so typos surface loudly instead of silently never firing. The loader fails open (issue #186): a truncated save or a non-object root degrades to empty overrides with a warning, and `sanitize_overrides` checks each field on its own, dropping a wrong-typed field or entry with a warning while the rest still applies. That is the only validator for this file: the curator UI's save runs the same function with `strict=True`, which raises on the first problem instead, and `TestSanitizeOverridesModes` holds the two modes together. Raising would freeze the panel in render backoff. The parsed result is cached on the file's stat stamp, so warnings fire once per version of the file, and the render subprocess stays quiet under `SUPPRESS_WARNINGS_ENV` like the corpus warnings.

**Per-row bans (`ban_quote_keys`, v2).** `ban_source_ids` blacklists every row from a Gutenberg ID — coarse but useful for "this whole book is unsuitable." `ban_quote_keys` is the fine-grained companion: a list of `"<source_id>:<line_number>"` strings, each dropping one row from the candidate pool **and every row that displays the same text** (issue #294): the committed corpus carries one passage under several keys — the miner fires on adjacent lines and the cleaner expands each to the same sentence run (`98:3534` … `98:3541`), and two Gutenberg editions of one book (`43` / `42`, `15` / `2701`) match identically — so a ban that matched only its own key was defeated by the twin. `pick_quote._twin_texts` resolves the banned keys to their `normalize_display_text` forms in one pass over the corpus, only when the list is non-empty. The anti-repeat ledger gets the same treatment, and `pick_best` collapses same-text candidates to their best-scored copy after scoring so a duplicated passage does not get two entries in the tie-break or two rows in the curator's inspector. The collapse runs identically on the baked and raw paths, which is what keeps `tests/test_bake_equivalence.py` green. Powers the curator UI's "Ban this quote" buttons (Now tab, bucket inspector, search results) so an operator can blacklist a single bad quote without nuking the rest of its source. `pick_quote.is_banned` checks both lists; the per-row check requires both `source_id` and `line_number` to be set on the row, so a malformed row can't be accidentally banned by a list entry. `load_overrides` defaults the field on legacy v1 sidecars so the rest of the picker doesn't have to special-case its absence. Every key check, in the loader and in the web UI, goes through `pick_quote.is_quote_key`, which uses `fullmatch` with ASCII digits so a key with a trailing newline or non-ASCII digits, which could never match a row, is rejected. The wholesale save layers the validated, normalised keys over the submitted document, so an operator's own extra top-level keys (a `_comment`, a field from a newer schema) survive the editor round-trip, as they do through the ban endpoint; the loader ignores them.

## Anti-Repeat History Ledger

A display-history ledger filters recently-shown quotes out of the candidate pool so the clock doesn't replay the same line twice in the same week. Default path is `~/.idle-hours/history.jsonl`; default window is 7 days. One entry per successful render:

```json
{"ts": "2026-04-19T14:30:00+00:00", "source_id": "141", "line_number": 482}
```

`pick_quote.load_recent_history` reads the ledger, drops entries older than `--history-days`, and returns a set of `(source_id, line_number)` tuples. `pick_best` applies a strict fresh-first filter: rows whose key is in that set are excluded before scoring, and if the filter empties the candidate pool the full list is used so sparse buckets still render something. `pick_quote.append_history` writes one line per successful render and then `fsync`s the handle so a power loss immediately after the call can't leave the entry buffered in the kernel — the worst failure case is one lost entry, never ledger-wide corruption. `pick_quote.remove_history_entries` (called by the button-A long-press "un-skip" action; removes *every* entry for the key, since a skip leaves both the render append and the ban append — issue #183) is the only code path that can rewrite the ledger from scratch; it goes through `atomic_io.atomic_write_text` so a `SIGKILL` between the read and the rewrite leaves either the pre-delete content (acceptable) or the post-delete content (acceptable) but never an empty or truncated ledger. If `load_recent_history` encounters a malformed line (partial write or external corruption), it logs a one-shot warning to stderr (`"history ledger {path}: malformed line skipped (corrupt or partial write); subsequent bad lines in this read will be suppressed"`) and continues; further bad lines in the same read are suppressed so a torn file doesn't spam the log.

Disable the filter by passing `--history-path ""` or `--history-days 0`. `select_quote` (the library entry point) defaults to **disabled** so unit tests and one-off callers are not affected; `run_clock.py` and `pick_quote.py`'s CLI default to **enabled**. `run_clock.py`:
- Calls `peek_quote_id` before `render_now` and forwards the peeked identity to the render subprocess as `--pin-quote SOURCE_ID:LINE --pin-matched-text TEXT`, so the subprocess renders *that exact row* instead of re-picking. The peek is authoritative; the old "peek and subprocess independently reach the same answer because they share a ledger snapshot" contract was only ever an implicit guarantee, and it broke outright on theme-only repaints, where the anti-repeat filter excluded the currently-displayed quote and silently swapped it (issue #190). run_clock still appends to the ledger only after the subprocess returns 0.

  **The pin key must carry `matched_text`.** `(source_id, line_number)` does **not** identify a corpus row — a single source line can carry several time phrases, so the committed `quote_database.jsonl` holds 128 duplicate `(source_id, line_number)` keys, many spanning different buckets (`"ten o'clock"` in `h10_exact` alongside `"close on ten o'clock"` in `h9_five_to`). A bare-key pin resolved to whichever copy came first on disk, which made ~8% of clock times render a phrase the picker never chose and report a bogus `resolved_bucket` / `used_fallback` in the debug footer. `run_clock._pin_key_for` therefore appends the peeked `matched_text` — the same discriminator `peek_quote_id` already tracks for dedup, for exactly this reason. Rows that still tie on `(key, matched_text)` but disagree on `fuzzy_bucket` (the same phrase mis-bucketed twice in the corpus) are broken by `neighbor_buckets(target_bucket)` order, so the pinned result reproduces the natural pick's bucket too. `tests/test_pick_quote.py::TestPinFidelityAgainstShippedCorpus` sweeps every canonical time against the real database and fails on any divergence — the synthetic-corpus pin tests all used unique keys, so they could not see this.

  **The pin respects bans but not the quality floor.** `pick_quote.is_banned` is re-checked on the pinned row, so a curator's "Ban this quote" click isn't undone by the next theme repaint; a banned, missing, or matched-text-mismatched pin falls through to a normal pick with a stderr warning. `--min-quality` is deliberately *not* re-applied — the row was already on the panel, and re-filtering it would swap the quote on a repaint, which is the bug the pin exists to prevent.
- Appends only after a successful render — never during quiet hours, never on failure, never when the dedup "quote unchanged" branch skips the redraw.
- Forwards `--history-path` / `--history-days` to `render_quote.py` via subprocess args so both processes agree on which ledger to consult.

**Ledger compaction.** `pick_quote.compact_history` drops entries older than `2 × --history-days` so a multi-year-running appliance doesn't linearly grow the file that every pick must stream through. The main loop calls `_maybe_compact_history` once per local-date rollover (gated by `state.last_compacted_date`) so we don't re-parse the ledger on every tick; `last_compacted_date` is set *before* the rewrite so a mid-compact crash doesn't re-trigger a retry storm the next tick. Rewrite routes through `atomic_io.atomic_write_text`, so a crash mid-compact leaves the original ledger intact. The `2×` slack means a short clock drift or an operator bumping `--history-days` up a day or two doesn't immediately evict rows that are about to be re-consulted. Malformed lines are preserved as-is (the compact pass is about bounded growth, not corruption repair — that's `load_recent_history`'s job).

## Contact Sheet (`contact_sheet.py`)

Offline QA tool. For each of the 144 `h{1..12}_{state}` buckets, calls `pick_quote.select_quote` at the bucket's canonical `HH:MM` (e.g. `h3_twenty_past` → `03:20`; `h12_*` maps to `00:MM`), renders the full 800×480 frame via `render_quote.render`, and downscales it into a tile on a 12×12 grid. Each tile gets a small `HH:MM  h{hour}_{state}` caption below so you can locate specific buckets at a glance. Flags: `--tile-width`/`--tile-height` (defaults 200×120), `--caption-height` (18), `--margin` (6), `--theme`, `--overrides` (defaults to the bundled sidecar; point it at an appliance's relocated copy), and `--mode` — defaults to `production` so the debug footer doesn't dominate small tiles. History filtering is forced off (snapshot of the whole corpus, not anti-repeated picks). Use this to spot regressions after a corpus change: layout bugs, malformed `matched_text`, repeat authors in adjacent buckets, or fallback-bucket frames that look visually wrong.
