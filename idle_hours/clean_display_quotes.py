#!/usr/bin/env python3
"""Improve raw harvested quotes into cleaner display-ready excerpts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from idle_hours import atomic_io
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


TERMINAL_PUNCT = ".!?\"'”’)]"
# Edge junk *other than* quotation marks — those are handled by
# ``clean_edges`` itself, because whether an edge quote is junk depends on
# whether its partner is inside the text (issue #297). A closing mark at the
# start (``” It was ten…``) or an opening mark at the end can never be paired
# and is always stripped.
LEADING_JUNK = re.compile(r'^[\s\[\(”’\-,:;]+')
TRAILING_JUNK = re.compile(r'[\s\[\(“‘\-,:;]+$')
OPENING_QUOTES = '"“‘'
CLOSING_QUOTES = '"”’'
# A ``’`` closes a quotation only when it does not sit between two letters —
# ``o’clock`` and ``don’t`` are apostrophes and must not count as pairs.
_CLOSING_SINGLE = re.compile(r"(?<![A-Za-z])’|’(?![A-Za-z])")

# Titles/honorifics and initials: in natural English prose the period is
# almost always followed by a proper name, not a new sentence. Merging across
# these is nearly always correct, and a display quote that ends at one is
# almost always the miner's context window cutting a name off ("…, said Mr.").
TITLE_ABBREVIATIONS = frozenset({
    "Mr", "Mrs", "Ms", "Mx", "Dr", "St", "Sr", "Jr",
    "Rev", "Hon", "Gen", "Col", "Capt", "Lt", "Sgt", "Maj", "Cpl", "Adm",
    "Mme", "Mlle", "M", "Mons", "Messrs", "Prof",
})

# Abbreviations that can *legitimately* end a sentence ("...at 3 p.m.",
# "Bring snacks, etc."). We still want to undo the false split the regex
# introduces when they occur mid-sentence, but only when the following
# fragment starts lowercase — otherwise we'd glue real sentence boundaries
# like "...etc. Then we left." back together.
SENTENCE_OK_ABBREVIATIONS = frozenset({
    "etc", "viz", "approx", "vs",
    "Mt", "Ave", "Rd", "Blvd",
    "No", "Nos",
})
_LAST_TOKEN_RE = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")
HEADING_PREFIX = re.compile(
    r"^(?:"
    r"(?:[A-Z][A-Z'.-]+(?:\s+[A-Z][A-Z'.-]+){0,5})\s+"
    r"(?:NARRATIVE|CHAPTER|BOOK|PART|SCENE|LETTER|PREFACE|INTRODUCTION)\b"
    r"|"
    r"CHAPTER\s+[IVXLCDM0-9]+[.:]?"
    r"(?:\s+IN\s+WHICH\s+[A-Z ,'-]+?(?=\s+[A-Z][a-z]))?"
    r"|"
    r"BOOK\s+[IVXLCDM0-9]+[.:]?"
    r"|"
    r"PART\s+[IVXLCDM0-9]+[.:]?"
    r"|"
    r"IN\s+WHICH\s+[A-Z ,'-]+?(?=\s+[A-Z][a-z])"
    r"|"
    # A bare Roman-numeral heading: "XXXIV. Next morning, …" (issue #308).
    # At least two numeral letters, because a lone "I." is the pronoun
    # ending a sentence and a lone "C." / "V." is as often an initial. The
    # numeral grammar (not ``[IVXLCDM]+``) keeps "DID." out, and it stops at
    # C..CXCIX: a chapter numbered in the hundreds is vanishingly rare, while
    # every M / D / CC form is also a word or an abbreviation someone shouts
    # at the start of a sentence ("MIX.", "DI.", "MD.", "CC.", "DC."). "LIV."
    # is excluded by name — it is a given name as often as fifty-four.
    r"(?!LIV\.)(?=[CLXVI]{2})C?(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\.(?=\s|$)"
    r"|"
    # ...and the same numeral with no period, running straight into a
    # Title-case sentence: "XI Emil came home at about half-past seven",
    # "III It was eleven o'clock". Nine shipped rows carried one. Without the
    # period the next word has to be capitalised prose, so a lone numeral in
    # running text is never taken.
    r"(?!LIV\b)(?=[CLXVI]{2})C?(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})(?=\s+[A-Z][a-z])"
    r")\s*",
)

# A leading run of all-caps words ending where a Title-case sentence
# begins: the chapter *titles* Gutenberg texts print above a chapter
# ("—CONTINUATION OF THE ENIGMA The night wind had risen…", "TWENTY MINUTES
# PAST TEN TO FORTY-SEVEN MINUTES PAST TEN P. M. As ten o'clock struck…").
# ``HEADING_PREFIX`` only knows headings that carry a keyword such as
# CHAPTER, so these reached the panel verbatim (issue #308).
#
# All-caps prose opens sentences too, and the first cut of this pattern ate
# it: initials ("J. R. R. Tolkien was born"), acronyms ("U. S. A. Troops"),
# a play's speaker label ("SIR TOBY BELCH. Out o' tune") and a shout ("I AM
# NOT. Go away"). What separates them from a title is punctuation — a title
# sits on its own line, so it runs into the sentence with nothing but
# whitespace, where every one of those ends its caps run in a period. So a run
# qualifies in one of two ways:
#
# * it carries a heading signal (CHAPTER / BOOK / PART …, or a clock phrase,
#   which is what the chapter titles of a time-keeping novel are made of) —
#   then its words may carry periods, as "CHAPTER I." and "P. M." do; or
# * its last word does not end in sentence punctuation (``.``, ``!``,
#   ``?``), and it is not made of initials alone. Earlier words may: two
#   headings stacked ("OLIVER WALKS TO LONDON. HE ENCOUNTERS … GENTLEMAN
#   Oliver reached…") and an initial ("BY H. HARRIS, AGENT") both still run
#   into the sentence unpunctuated.
#
# Three words is the floor either way, so a single shouted word or a
# two-word label survives, and the sentence that follows must open with a
# capital and a lowercase letter (or a lone "A" / "I" word) so a heading is
# only ever cut at a sentence start.
_CAPS_WORD = r"[A-Z0-9][A-Z0-9’'.,\-—]*"
_CAPS_WORD_UNSTOPPED = r"[A-Z0-9](?:[A-Z0-9’',\-—]*[A-Z0-9’',\-—])?"
_HEADING_SIGNAL = (
    r"(?:CHAPTER|BOOK|PART|VOLUME|NARRATIVE|PREFACE|INTRODUCTION|EPILOGUE|PROLOGUE"
    r"|O[’']CLOCK|MINUTES?|MIDNIGHT|NOON)"
)
_SENTENCE_START = r"(?=[A-Z](?:[a-z’']|\s+[a-z]))"
LEADING_CAPS_HEADING = re.compile(
    r"^[—\-\s]*(?:"
    # Signalled: the signal must sit inside the caps run. The run cannot
    # contain a lowercase letter, so a lookahead confined to caps, digits,
    # punctuation and spaces can never find the word in the sentence after.
    r"(?=[A-Z0-9’'.,\-—\s]*?(?<![A-Za-z])" + _HEADING_SIGNAL + r"(?![A-Za-z]))"
    r"(?:" + _CAPS_WORD + r"\s+){3,}"
    r"|"
    # Unsignalled: the last word does not end a sentence, and the run is
    # not initials alone.
    r"(?!(?:[A-Z]\.?\s+)+" + _SENTENCE_START + r")"
    r"(?:" + _CAPS_WORD + r"\s+){2,}" + _CAPS_WORD_UNSTOPPED + r"\s+"
    r")" + _SENTENCE_START
)

# Stray-character normalisation for glyphs the bundled faces lack. PRIME
# (U+2032) and DOUBLE PRIME (U+2033) are the minute / second marks of a
# latitude ("20° 7′ north"); forty of the bundled body faces have no glyph for
# them and render tofu (issue #308). The apostrophe and closing double quote
# are the typographic stand-ins every book face carries.
GLYPH_SUBSTITUTIONS = str.maketrans({"\u2032": "\u2019", "\u2033": "''"})

# An opening ellipsis ("… But I have to go…", "... You are right") is the
# source's own elision mark, which reads as a fragment on the panel. Applied
# by ``clean_edges`` to the whole excerpt only.
LEADING_ELLIPSIS = re.compile(r"^(?:\.{2,}|…)\s*")

# Gutenberg's ``_emphasis_`` markers, as ``render_quote.strip_underscore_emphasis``
# pairs them. A marker whose partner fell outside the miner's window survives
# the render as a bare ``_`` (issue #308).
_EMPHASIS_PAIR = re.compile(r"(?<![A-Za-z0-9])_([^_\n]+?)_(?![A-Za-z0-9])")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean raw quote candidates into better display excerpts.")
    parser.add_argument("input", help="Merged candidate JSONL input")
    parser.add_argument(
        "--output",
        default="output/candidates-cleaned.jsonl",
        help="Output JSONL path",
    )
    return parser.parse_args()


def _last_token_head(text: str) -> str | None:
    """Return the non-dotted head of the final dotted token (e.g. ``"Mr." → "Mr"``,
    ``"P.M." → "P.M"``), or ``None`` if `text` doesn't end with a dotted token.
    """
    match = _LAST_TOKEN_RE.search(text)
    if not match:
        return None
    return match.group(1).rstrip(".")


def _ends_with_title_abbreviation(text: str) -> bool:
    """Title-style abbreviation or single-letter initial at the end.

    In natural prose these are (almost) always followed by a proper name, so
    the period is part of the abbreviation rather than a sentence terminator.
    Used both to un-split false regex boundaries and to flag display quotes
    that almost certainly got truncated by the miner's context window.
    """
    head = _last_token_head(text)
    if head is None:
        return False
    if head in TITLE_ABBREVIATIONS:
        return True
    if len(head) == 1 and head.isupper():
        return True
    return False


def _ends_with_sentence_ok_abbreviation(text: str) -> bool:
    """Abbreviation that can *legitimately* terminate a sentence.

    ``etc.``, ``vs.``, ``p.m.``, ``U.S.A.`` and the like. We still undo the
    false regex split when the next fragment continues the same sentence
    (signalled by a lowercase start), but we must not flag these as fragments
    when they're genuinely sentence-final.
    """
    head = _last_token_head(text)
    if head is None:
        return False
    if head in SENTENCE_OK_ABBREVIATIONS:
        return True
    # Short dotted acronym: "P.M", "A.M", "e.g", "i.e", "U.S", "U.S.A".
    # Requires an interior period so bare surnames like "Jones" don't match,
    # and caps length so long hyphenated/dotted constructs don't either.
    if "." in head and len(head) <= 5:
        return True
    return False


def split_sentences(text: str) -> list[str]:
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    text = re.sub(r'([.!?]["”’\]\)]?)\s+', r'\1\n', text)
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    # Undo the false splits the regex above introduces inside abbreviations:
    #   - title-style ("Mr.", "Dr.", "J.") always take a following name, so
    #     we merge unconditionally;
    #   - sentence-capable ("etc.", "p.m.", "U.S.A.") may legitimately end a
    #     sentence, so we only merge when the next fragment starts lowercase
    #     (a strong signal it's a continuation, not a new sentence).
    merged: list[str] = []
    for part in parts:
        if merged:
            prev = merged[-1]
            if _ends_with_title_abbreviation(prev):
                merged[-1] = f"{prev} {part}"
                continue
            if _ends_with_sentence_ok_abbreviation(prev) and part and part[0].islower():
                merged[-1] = f"{prev} {part}"
                continue
        merged.append(part)
    return merged


def unbalanced_quotes(text: str) -> bool:
    """True when the double quotation marks in ``text`` do not pair up.

    Straight ``"`` must come in an even count; curly ``“`` and ``”`` must
    match one for one. Single quotes are deliberately not checked — ``’`` is
    also the apostrophe, and a heuristic that tried to tell them apart
    misfired more than it caught. Shared by the cleaner (to prefer a balanced
    run) and ``quality_filter`` (to penalise what the cleaner could not fix).
    """
    return text.count('"') % 2 == 1 or text.count("“") != text.count("”")


def _leading_quote_is_unpaired(text: str) -> bool:
    mark = text[0]
    if mark == '"':
        return text.count('"') % 2 == 1
    if mark == "“":
        return text.count("“") > text.count("”")
    # ``‘``: unpaired unless a closing single quote follows somewhere.
    return not _CLOSING_SINGLE.search(text[1:])


def _trailing_quote_is_unpaired(text: str) -> bool:
    mark = text[-1]
    if mark == '"':
        return text.count('"') % 2 == 1
    if mark == "”":
        return text.count("”") > text.count("“")
    # ``’`` at the very end after punctuation is a closing quote; it is
    # unpaired unless an opening ``‘`` appears in the text.
    return "‘" not in text


def clean_edges(text: str) -> str:
    """Strip edge junk, but keep a quotation mark whose partner is inside.

    ``LEADING_JUNK`` / ``TRAILING_JUNK`` used to include every quotation mark,
    so ``"It is five o'clock," he said.`` lost its opening ``"`` and reached
    the panel as ``It is five o'clock," he said.`` — 13% of displayable rows
    carried an unbalanced quote that way (issue #297). A quote is stripped
    only when it has no partner in the text; a fully quoted sentence keeps
    both marks.
    """
    text = re.sub(r"\s+", " ", text.translate(GLYPH_SUBSTITUTIONS)).strip()
    while text:
        before = text
        text = LEADING_JUNK.sub("", text)
        text = TRAILING_JUNK.sub("", text).strip()
        if text and text[0] in OPENING_QUOTES and _leading_quote_is_unpaired(text):
            text = text[1:].lstrip()
        if text and text[-1] in CLOSING_QUOTES and _trailing_quote_is_unpaired(text):
            text = text[:-1].rstrip()
        if text == before:
            break
    text = strip_heading_prefix(drop_stray_underscores(text))
    # Only the excerpt's own opening ellipsis is dropped — one inside the
    # text is the author's, and ``strip_heading_prefix`` (which also runs per
    # interior sentence) must leave it alone.
    return LEADING_ELLIPSIS.sub("", text).strip()


def drop_stray_underscores(text: str) -> str:
    """Remove single ``_`` markers that have no emphasis partner.

    Paired ``_emphasis_`` spans are kept (the renderer strips them), and so
    are runs of two or more underscores — the ``____`` a Victorian text
    prints for a suppressed name — and an in-word ``var_name``. What goes is an orphan: ``_It had run
    down…`` whose closing marker lay beyond the window, or the mangled
    ``[Stiffly_._]`` whose two markers pair with nothing.
    """
    if "_" not in text:
        return text
    keep: set[int] = set()
    for match in _EMPHASIS_PAIR.finditer(text):
        keep.update((match.start(), match.end() - 1))
    out = []
    for i, ch in enumerate(text):
        if ch == "_" and i not in keep:
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            in_run = prev == "_" or nxt == "_"
            in_word = prev.isalnum() and nxt.isalnum()
            if not in_run and not in_word:
                continue
        out.append(ch)
    return "".join(out)


def strip_heading_prefix(text: str) -> str:
    """Iteratively strip leading HEADING_PREFIX matches without touching quote
    marks or other content-bearing punctuation. Used for interior sentences in
    ``expand_candidates``: ``clean_edges`` would strip a leading ``"`` or ``'``
    via ``LEADING_JUNK``, which destroys the opening of dialogue when joined
    sentences like ``He paused. "All is ready," she replied.`` are concatenated
    into a run — the interior sentence would become ``All is ready,"`` and
    render with an orphan close-quote.
    """
    while True:
        stripped = HEADING_PREFIX.sub("", text).strip()
        stripped = LEADING_CAPS_HEADING.sub("", stripped).strip()
        if stripped == text:
            break
        text = stripped
    return text


def looks_fragment(text: str) -> bool:
    if not text:
        return True
    if len(text.split()) < 4:
        return True
    if not any(text.endswith(ch) for ch in TERMINAL_PUNCT):
        return True
    if text[0].islower():
        return True
    # Trailing "Mr." / "Mrs." / "J." almost always means the miner's context
    # window cut a sentence short mid-name. Flag as a fragment so quality_filter
    # heavily penalises it. We deliberately do *not* flag "p.m." / "etc." —
    # those can terminate a real sentence and shouldn't be punished here.
    if _ends_with_title_abbreviation(text):
        return True
    return False


EXPANSION_MAX_CHARS = 260  # matches quality_filter's `too_long` ceiling — keep in lockstep.
EXPANSION_NEIGHBOURS = 2

# Catches chapter/book/part/scene/volume/letter markers *anywhere* in a candidate.
# Case-sensitive (ALL CAPS or Title Case only) so we don't flag prose like
# "garden-scene it had". Numerals must be uppercase roman or arabic, so "part 3"
# in lowercase prose does not match either. Used post-join to reject joined runs
# whose neighbour sentence bled a heading into the middle of the display quote.
INTERIOR_HEADING = re.compile(
    r"\b(?:CHAPTER|BOOK|PART|SCENE|VOLUME|LETTER|Chapter|Book|Part|Scene|Volume|Letter)"
    r"\s+(?:[IVXLCDM]+|\d+)(?:[.:]|\b)",
)


def expand_candidates(text: str, matched_text: str) -> tuple[list[str], set[str]]:
    """Build multi-sentence runs centered on sentences containing ``matched_text``.

    Returns ``(runs, single_hits)`` — ``single_hits`` is the subset that are a
    lone hit sentence (no neighbours joined), kept separate so the caller can
    distinguish a naturally-complete sentence from an expanded run.
    """
    if not text:
        return [], set()
    needle = (matched_text or "").replace("\n", " ").strip().lower()
    if not needle:
        return [], set()
    # Use the quote-preserving heading-stripper here, not clean_edges: joined
    # runs must keep opening ``"`` / ``'`` characters on interior dialogue.
    sentences = [strip_heading_prefix(s) for s in split_sentences(text)]
    sentences = [s for s in sentences if s]
    if not sentences:
        return [], set()
    hits = [i for i, s in enumerate(sentences) if needle in s.lower()]
    runs: list[str] = []
    singles: set[str] = set()
    for i in hits:
        for before in range(EXPANSION_NEIGHBOURS + 1):
            for after in range(EXPANSION_NEIGHBOURS + 1):
                lo = i - before
                hi = i + after
                if lo < 0 or hi >= len(sentences):
                    continue
                run = " ".join(sentences[lo:hi + 1]).strip()
                if not run or len(run) > EXPANSION_MAX_CHARS:
                    continue
                runs.append(run)
                if before == 0 and after == 0:
                    singles.add(run)
    return runs, singles


def best_display_quote(row: dict) -> tuple[str, bool, str]:
    candidates = []
    single_hits: set[str] = set()
    for field in ("quote_text", "context_text"):
        value = clean_edges(row.get(field) or "")
        # The whole field is a candidate too, so it gets the same per-sentence
        # heading strip the runs get — otherwise an interior "II." or a
        # mid-text chapter title survives in the one candidate that is not
        # built from ``expand_candidates`` (issue #308).
        value = " ".join(s for s in (strip_heading_prefix(x) for x in split_sentences(value)) if s)
        if not value:
            continue
        runs, singles = expand_candidates(value, row.get("matched_text") or "")
        candidates.extend(runs)
        single_hits.update(singles)
        candidates.append(value)
        # A full field value that is itself a single sentence must also count
        # as a single-hit, otherwise rows with no/empty matched_text (or where
        # the blob is the winning candidate) get mislabelled "expanded".
        if len(split_sentences(value)) == 1:
            single_hits.add(value)

    seen = list(dict.fromkeys(candidates))
    # A candidate that no longer shows the matched phrase cannot be
    # displayed for it: the renderer has nothing to highlight and the row
    # sits at a time its text does not state. This happens when the phrase
    # lived in a heading the cleaner just stripped ("TWENTY MINUTES PAST TEN
    # TO … P. M. As ten o'clock struck…", issue #308); such a row falls back
    # to a fragment so ``quality_filter`` keeps it off the panel.
    needle = " ".join((row.get("matched_text") or "").split()).lower()
    if needle and seen and not any(needle in c.lower() for c in seen):
        return max(seen, key=len), True, "fragment_fallback"
    non_fragments = [c for c in seen if not looks_fragment(c)]
    # Prefer candidates whose interior is heading-free, but only if any survive.
    # Sparse buckets where every candidate bleeds a heading still render something.
    clean_non_fragments = [c for c in non_fragments if not INTERIOR_HEADING.search(c)]
    pool = clean_non_fragments or non_fragments
    # Then prefer a run whose quotation marks pair up (issue #297):
    # ``split_sentences`` splits inside dialogue, so a run can start with the
    # tail of a speech whose opening mark sits in the previous sentence, or
    # end before the closing one. Where a balanced run exists it wins; where
    # none does, ``quality_filter`` penalises the survivor.
    balanced = [c for c in pool if not unbalanced_quotes(c)]
    pool = balanced or pool
    if pool:
        best = min(pool, key=lambda c: (abs(len(c) - 140), len(c)))
        status = "complete_sentence" if best in single_hits else "expanded_with_context"
        # The runs kept their interior quotes on purpose (see
        # ``strip_heading_prefix``), so the winner may still open with a mark
        # whose partner lies beyond the miner's window — the commonest shape
        # left after the balanced-run preference. One last ``clean_edges``
        # drops exactly that unpaired edge mark and nothing else.
        return clean_edges(best), False, status

    if seen:
        best = max(seen, key=len)
        return best, True, "fragment_fallback"

    return "", True, "empty"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    rows = []
    for row in iter_jsonl(input_path):
        display_quote, is_fragment, cleanup_status = best_display_quote(row)
        row["display_quote"] = display_quote
        row["display_fragment"] = is_fragment
        row["cleanup_status"] = cleanup_status
        rows.append(row)

    atomic_io.atomic_write_lines(
        output_path, (json.dumps(row, ensure_ascii=False) for row in rows)
    )

    fragments = sum(1 for row in rows if row["display_fragment"])
    print(f"Wrote {len(rows)} cleaned candidates to {output_path}")
    print(f"Fragment fallbacks: {fragments}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
