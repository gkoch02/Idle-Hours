"""The ``lieder`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random
from itertools import pairwise

from PIL import Image, ImageDraw

from .._paths import NOTOMUSIC_REGULAR
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import _row_digest, fallback_title
from ..layout import strip_underscore_emphasis, tokenize_quote
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..spec import FrameSpec
from ._shared import _astrarium_paint_cream_wash

# ─── lieder (engraved art-song manuscript) ───────────────────────────────────
#
# The quote as the vocal line of a Lied; the time signature is the hour over 4
# and the tempo mark the minute, so ``time_str`` IS used here, for that chrome.
# Design notes: docs/themes.md § lieder.

_LIEDER_STAVE_GAP = 7            # px between adjacent staff lines (staff = 4×)
_LIEDER_MARGIN_L = 46
_LIEDER_MARGIN_R = 754
_LIEDER_MAX_SYSTEMS = 3
_LIEDER_BAND = (100, 446)        # vertical band the systems are laid out within
_LIEDER_HEADROOM = 4.0           # staff spaces reserved above a staff (stems/slur)
_LIEDER_LYRIC_OFFSET = 5.0       # staff spaces from staff bottom to lyric baseline
                                 # (clears a down-stem, which hangs 3.4 spaces below a
                                 #  middle-line notehead, by ~7px at the largest lyric)
_LIEDER_STEM_LEN = 3.4           # staff spaces
_LIEDER_BEAM_REACH = 2.5         # staff spaces a beam may lie outside the staff (clears the lyric)
_LIEDER_BEAM_MIN_STEM = 1.5      # staff spaces a shortened beamed stem keeps past its head
_LIEDER_BEAM_CLEARANCE = 2       # px between a down beam and the lyric's tallest ink
_LIEDER_LYRIC_RISE_PROBE = "bdfhklABDHKLT'\u201c"  # the lyric's tallest glyphs
_LIEDER_PITCH_MIN = -2           # one ledger line below the staff
_LIEDER_PITCH_MAX = 10           # one ledger line above the staff
_LIEDER_FONT_MAX = 26
_LIEDER_FONT_MIN = 13
_LIEDER_SYSTEM_GAP = 6           # px between one system's lyric and the next staff's headroom
# Melodic steps in staff positions (1 = the next line-or-space up), weighted
# toward stepwise motion — a uniform choice reads as noise, not melody.
_LIEDER_MELODY_STEPS = (-4, -3, -2, -2, -1, -1, -1, 0, 1, 1, 1, 2, 2, 3, 4)
# Italian tempo words, one per 12-minute band; paired with ♩ = 60 + minute so
# the word and the metronome figure always agree.
_LIEDER_TEMPO_WORDS = ("Larghetto", "Andante", "Moderato", "Allegretto", "Allegro")
# Expression marks for the second system, chosen by the per-quote seed.
_LIEDER_EXPRESSION = ("dolce", "espressivo", "cantabile", "sotto voce", "teneramente", "con moto")
_MUSIC_G_CLEF = "\U0001D11E"
_MUSIC_NOTEHEAD = "\U0001D158"
_MUSIC_NOTEHEAD_VOID = "\U0001D157"   # half / dotted half
# Rests, longest first — the greedy set used to pad an incomplete final bar.
_MUSIC_RESTS = ((4.0, "\U0001D13B"), (2.0, "\U0001D13C"), (1.0, "\U0001D13D"), (0.5, "\U0001D13E"))
_MUSIC_QUARTER_NOTE = "♩"


def _lieder_clock(time_str: str) -> tuple[int, int]:
    """``(hour 1..12, minute 0..59)`` parsed defensively from ``HH:MM``.

    Preview and source-card renders can reach this with an odd string; a bad
    parse falls back to 12/00 rather than raising into the render path.
    """
    try:
        hh, mm = time_str.split(":")[:2]
        hour = int(hh) % 12 or 12
        minute = max(0, min(59, int(mm)))
    except (AttributeError, ValueError):
        return 12, 0
    return hour, minute


# Words the syllabifier below gets wrong (TeX's ``\hyphenation{}`` list).
# Keep it small and evidence-driven: only words actually frequent in
# ``quote_database.jsonl`` belong here.
_LIEDER_SYLLABLE_EXCEPTIONS = {
    "another": ("an", "oth", "er"),
    "business": ("busi", "ness"),
    "curious": ("cu", "ri", "ous"),
    "eleven": ("e", "lev", "en"),
    "entirely": ("en", "tire", "ly"),
    "exactly": ("ex", "act", "ly"),
    "precisely": ("pre", "cise", "ly"),
    "quiet": ("qui", "et"),
    "quietly": ("qui", "et", "ly"),
    "serious": ("se", "ri", "ous"),
    "something": ("some", "thing"),
    "sometimes": ("some", "times"),
    "somewhere": ("some", "where"),
    "therefore": ("there", "fore"),
    "various": ("va", "ri", "ous"),
}
# Consonant pairs that are one sound and must never be split across syllables.
_LIEDER_DIGRAPHS = ("th", "sh", "ch", "wh", "ph", "gh", "ck", "ng", "qu")
_LIEDER_VOWELS = frozenset("aeiouy")
# Unstressed function words — set to a weak, short note.
_LIEDER_FUNCTION_WORDS = frozenset(
    "a an the of and to in is was were it its that this these those his her their they them "
    "he she we you i be been am are had has have do did for with on at as by but or from not "
    "no so then than there which who what when all one up out into upon own who's".split()
)
# Prefixes that carry no stress, so the stress falls on the SECOND syllable
# (a-bout, be-fore, re-turn).
_LIEDER_WEAK_PREFIXES = ("a", "be", "re", "de", "con", "ex", "in", "un", "for", "to", "per", "pro")
_LIEDER_PHRASE_END = ".,;:!?—"


def _lieder_syllables(word: str) -> list[str]:
    """Split one word into display syllables.

    A heuristic, deliberately: what matters musically is the syllable *count*
    (how many notes the word gets), not the exact split point. The exception
    table covers frequent words the rules miss.

    Rules, in the order they matter: ``qu`` is a consonant (so ``quiet`` has
    one vowel run, not two); a final silent ``e`` is not a syllable (``time``)
    unless it is the ``-le`` of ``ta-ble``; ``-ed`` is silent except after t/d
    (``slipped`` is one syllable, ``wanted`` two); ``-es`` is silent except
    after a sibilant; a consonant pair that is a digraph never splits; a
    doubled consonant always splits between the pair; and a consonant+``le``
    ending takes the consonant with it.
    """
    core = "".join(ch for ch in word if ch.isalpha() or ch == "'")
    if len(core) <= 3:
        return [word]
    low = core.lower()
    if low in _LIEDER_SYLLABLE_EXCEPTIONS:
        lengths = [len(p) for p in _LIEDER_SYLLABLE_EXCEPTIONS[low]]
        cuts, run = [], 0
        for length in lengths[:-1]:
            run += length
            cuts.append(run)
        return _lieder_apply_cuts(word, cuts)

    groups, i = [], 0
    while i < len(low):
        if low[i] in _LIEDER_VOWELS:
            if low[i] == "u" and i and low[i - 1] == "q":   # "qu" is a consonant
                i += 1
                continue
            j = i
            while j < len(low) and low[j] in _LIEDER_VOWELS:
                if low[j] == "u" and low[j - 1] == "q":
                    break
                j += 1
            groups.append((i, j))
            i = j
        else:
            i += 1
    if len(groups) < 2:
        return [word]

    le_ending = len(low) > 3 and low.endswith("le") and low[-3] not in _LIEDER_VOWELS
    if not le_ending and low.endswith("e") and groups[-1] == (len(low) - 1, len(low)):
        groups.pop()
    if len(groups) > 1 and low.endswith("ed") and low[-3:-2] not in ("t", "d"):
        if groups[-1][0] == len(low) - 2:
            groups.pop()
    if len(groups) > 1 and low.endswith("es") and low[-3:-2] not in ("s", "z", "x", "h", "c", "i"):
        if groups[-1][0] == len(low) - 2:
            groups.pop()
    if len(groups) < 2:
        return [word]

    cuts = []
    for (_, end_a), (start_b, _) in pairwise(groups):
        between = low[end_a:start_b]
        n = len(between)
        if le_ending and start_b == len(low) - 1 and n >= 2:
            cut = start_b - 2                       # ta-ble, lit-tle, pos-si-ble
        elif n <= 1:
            cut = end_a                             # o-ver
        elif n == 2:
            cut = end_a if between in _LIEDER_DIGRAPHS else end_a + 1   # an-oth-er / af-ter
        elif between[0] == between[1]:
            cut = end_a + 2                         # still-ness
        elif between[1:3] in _LIEDER_DIGRAPHS:
            cut = end_a + 1
        elif between[:2] in _LIEDER_DIGRAPHS:
            cut = end_a + 2
        else:
            cut = end_a + 1
        cuts.append(cut)
    kept, prev = [], 0
    for cut in cuts:
        # Never strand a fragment of under two letters — it is not a syllable
        # and it looks like a typo under a notehead.
        if cut - prev >= 2 and len(low) - cut >= 2:
            kept.append(cut)
            prev = cut
    return _lieder_apply_cuts(word, kept) if kept else [word]


def _lieder_apply_cuts(word: str, cuts: list[int]) -> list[str]:
    """Slice ``word`` at cut positions expressed in *letters-only* coordinates.

    The cuts are computed against the alphabetic core, but the displayed word
    still carries its punctuation ("o'clock,"), so the indices are mapped back
    onto the original string before slicing.
    """
    if not cuts:
        return [word]
    positions, seen = [], 0
    for index, ch in enumerate(word):
        if seen in cuts and ch.isalpha():
            positions.append(index)
            cuts = [c for c in cuts if c != seen]
        if ch.isalpha() or ch == "'":
            seen += 1
    pieces, start = [], 0
    for pos in positions:
        if pos > start:
            pieces.append(word[start:pos])
            start = pos
    pieces.append(word[start:])
    return [p for p in pieces if p] or [word]


def _lieder_notes(quote_row: dict) -> list[dict]:
    """Build the per-syllable note list: one dict per note, in singing order.

    Each carries what the later passes need — ``matched`` (inside the sung time
    phrase), ``hyphen`` (another syllable of the same word follows, so a lyric
    hyphen is drawn), ``breath`` (a phrase boundary follows) and ``stress``
    (2 phrase-final, 1 stressed, 0 weak), which is what the rhythm pass turns
    into note durations.
    """
    text = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    notes: list[dict] = []
    word_index = 0
    for chunk, matched in tokenize_quote(text, quote_row.get("matched_text") or ""):
        for word in chunk.split():
            bare = word.strip(_LIEDER_PHRASE_END + "\"'”“’")
            low = "".join(ch for ch in bare if ch.isalpha()).lower()
            pieces = _lieder_syllables(word)
            ends_phrase = any(word.endswith(ch) for ch in _LIEDER_PHRASE_END)
            weak_word = low in _LIEDER_FUNCTION_WORDS
            # Stress lands on the second syllable when the word opens with an
            # unstressed prefix (a-BOUT, be-FORE, re-TURN).
            accent = 0
            if len(pieces) > 1 and any(low.startswith(p) for p in _LIEDER_WEAK_PREFIXES):
                accent = 1
            for position, piece in enumerate(pieces):
                last = position == len(pieces) - 1
                if weak_word:
                    stress = 0
                elif position == accent:
                    stress = 1
                else:
                    stress = 0
                if last and ends_phrase:
                    stress = 2
                notes.append({
                    "text": piece,
                    "matched": matched,
                    "hyphen": not last,
                    "breath": last and ends_phrase,
                    "stress": stress,
                    "word": word_index,
                })
            word_index += 1
    if notes:
        notes[-1]["stress"] = 2
        notes[-1]["breath"] = False
    return notes


def _lieder_is_dotted(beats: float) -> bool:
    """A dot adds half again, so 1.5 (dotted quarter) and 3.0 (dotted half)."""
    return abs(beats - 1.5) < 1e-9 or abs(beats - 3.0) < 1e-9


def _lieder_rhythm(notes: list[dict], numerator: int) -> None:
    """Assign each note a duration in beats and mark where barlines fall.

    Durations come from stress: a phrase-final syllable is held (a dotted half
    at the very end), a stressed syllable takes a quarter, a weak one an
    eighth.

    Bars are filled to *exactly* ``numerator`` beats. A note is shortened
    rather than allowed to overflow, since a note straddling a barline would
    need a tie.
    """
    remaining = float(numerator)
    for index, note in enumerate(notes):
        if remaining <= 1e-9:
            remaining = float(numerator)
            note["bar"] = index > 0
        else:
            note["bar"] = False
        if note["stress"] >= 2:
            want = 3.0 if index == len(notes) - 1 else 2.0
        elif note["stress"] == 1:
            want = 1.0
        else:
            want = 0.5
        options = [d for d in (3.0, 2.0, 1.0, 0.5) if d <= remaining + 1e-9]
        beats = next((d for d in options if d <= want), options[-1] if options else 0.5)
        note["beats"] = beats
        note["dotted"] = _lieder_is_dotted(beats)
        remaining -= beats
    # Fill the last bar exactly: first grow the last note (a notehead can only
    # express a few durations), then pad whatever remains with rests.
    if notes and remaining > 1e-9:
        last = notes[-1]
        for grown in (3.0, 2.0, 1.5, 1.0):
            if grown > last["beats"] and grown <= last["beats"] + remaining + 1e-9:
                remaining -= grown - last["beats"]
                last["beats"] = grown
                last["dotted"] = _lieder_is_dotted(grown)
                break
        while remaining > 1e-9:
            value = next((v for v, _ in _MUSIC_RESTS if v <= remaining + 1e-9), None)
            if value is None:
                break
            notes.append({
                "text": "", "matched": False, "hyphen": False, "breath": False,
                "stress": 0, "word": last["word"], "beats": value, "dotted": False,
                "bar": False, "rest": True, "pitch": 4,
            })
            remaining -= value


def _lieder_chord_tone(pitch: int) -> int:
    """Nudge a pitch onto the nearest tonic-triad degree (C, E or G).

    In this key (no key signature, so C major) every staff position is a
    diatonic degree, and the triad sits on degrees 0/2/4 of the seven. Any
    pitch is at most one step from one of them, so this never leaps.
    """
    for delta in (0, -1, 1, -2, 2):
        candidate = pitch + delta
        if _LIEDER_PITCH_MIN <= candidate <= _LIEDER_PITCH_MAX and (candidate + 2) % 7 in (0, 2, 4):
            return candidate
    return pitch


def _lieder_contour(seed: int, notes: list[dict]) -> None:
    """Give the line a singable shape, and make it end like a piece of music.

    A weighted random walk, shaped by four rules:

    * **Downbeat gravity** — the first note of each bar is pulled onto a tonic
      triad degree.
    * **Leap resolution** — after a leap of three degrees or more the next move
      is a step in the opposite direction.
    * **Phrase resolution** — a phrase-final syllable settles onto a chord tone.
    * **Cadence** — the final note lands on the tonic, approached by step.

    The matched phrase keeps an upward bias so the sung phrase peaks; the
    range edges pull back toward the middle.
    """
    rng = random.Random(seed)
    pitch = _lieder_chord_tone(4)
    previous_step = 0
    # Trailing rests carry no pitch, and the cadence must land on the last sung
    # syllable rather than on a rest. Mutating these dicts still updates `notes`.
    sung = [n for n in notes if not n.get("rest")]
    total = len(sung)
    for index, note in enumerate(sung):
        if index == 0 or note.get("bar"):
            pitch = _lieder_chord_tone(pitch)
        note["pitch"] = pitch
        if index == total - 1:
            break
        if abs(previous_step) >= 3:
            step = -1 if previous_step > 0 else 1
        elif note["breath"]:
            step = _lieder_chord_tone(pitch) - pitch or rng.choice((-1, 1))
        else:
            step = rng.choice(_LIEDER_MELODY_STEPS)
            if note["matched"] and step < 0 and pitch < 7:
                step = -step
        if pitch >= 8 and step > 0:
            step = -step
        elif pitch <= 0 and step < 0:
            step = -step
        previous_step = step
        pitch = max(_LIEDER_PITCH_MIN, min(_LIEDER_PITCH_MAX, pitch + step))
    if total >= 2:
        tonic = min((-2, 5), key=lambda t: abs(t - sung[-1]["pitch"]))
        sung[-1]["pitch"] = tonic
        approach = sung[-2]["pitch"]
        if abs(approach - tonic) != 1:
            sung[-2]["pitch"] = max(_LIEDER_PITCH_MIN, min(_LIEDER_PITCH_MAX,
                                                           tonic + (1 if approach >= tonic else -1)))


def _lieder_slot(note: dict, min_gap: int, base: float) -> float:
    """Horizontal space one note owns.

    The larger of the syllable's text plus breathing room and a duration
    share. The 0.6 exponent compresses duration spacing as engravers do: a
    half note gets more room than an eighth, nowhere near four times more.
    """
    if note.get("rest"):
        return base * (note["beats"] ** 0.6)
    return max(note["width"] + min_gap * 0.75, base * (note["beats"] ** 0.6))


def _lieder_wrap(notes: list[dict], widths: list[int], min_gap: int, base: float) -> list[list[dict]]:
    """Break the notes into systems, never splitting a word across two staves.

    Keeping words whole avoids the continuation hyphen a split would need at
    the next line head, at the cost of a little justification slack.
    """
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_w = 0.0
    index = 0
    while index < len(notes):
        word = notes[index]["word"]
        group = []
        while index < len(notes) and notes[index]["word"] == word:
            group.append(notes[index])
            index += 1
        group_w = sum(_lieder_slot(n, min_gap, base) for n in group)
        avail = widths[min(len(lines), len(widths) - 1)]
        if current and current_w + group_w > avail:
            lines.append(current)
            current, current_w = [], 0.0
        current.extend(group)
        current_w += group_w
    if current:
        lines.append(current)
    return lines


def _lieder_system_core(size: int, gap: int) -> int:
    """Vertical extent of one system: headroom + staff + lyric descent."""
    return int((_LIEDER_HEADROOM + 4 + _LIEDER_LYRIC_OFFSET) * gap) + size


def _lieder_fit(draw, notes: list[dict], widths: list[int], gap: int) -> tuple:
    """Shrink the lyric font until the syllables fit the page as engraved systems.

    Per size, the notes must wrap into at most ``_LIEDER_MAX_SYSTEMS`` staves
    and those systems (headroom + staff + lyric) must fit the vertical band.

    The size range is deliberately narrow: lyric size tracks staff size, so
    quote length is absorbed by the number of systems instead.
    """
    regular_chain = theme_font_candidates("lieder", "quote_regular")
    bold_chain = theme_font_candidates("lieder", "quote_bold")
    band_height = _LIEDER_BAND[1] - _LIEDER_BAND[0]
    lines: list = []
    size = _LIEDER_FONT_MIN
    regular = load_font(regular_chain, size=size)
    bold = load_font(bold_chain, size=size)
    min_gap = 0
    for size in range(_LIEDER_FONT_MAX, _LIEDER_FONT_MIN - 1, -1):
        regular = load_font(regular_chain, size=size)
        bold = load_font(bold_chain, size=size)
        min_gap = max(7, int(size * 0.38))
        base = min_gap * 2.1
        for note in notes:
            note["width"] = int(draw.textlength(note["text"], font=bold if note["matched"] else regular))
        lines = _lieder_wrap(notes, widths, min_gap, base)
        if len(lines) > _LIEDER_MAX_SYSTEMS:
            continue
        block = len(lines) * _lieder_system_core(size, gap) + (len(lines) - 1) * _LIEDER_SYSTEM_GAP
        if block <= band_height:
            return regular, bold, lines, size, min_gap, base
    if len(lines) > _LIEDER_MAX_SYSTEMS:
        lines = lines[:_LIEDER_MAX_SYSTEMS]
        if lines and lines[-1]:
            tail = lines[-1][-1]
            tail["text"] = tail["text"].rstrip(".,;:!?") + "…"
            tail["hyphen"] = False
            tail["width"] = int(draw.textlength(tail["text"], font=bold if tail["matched"] else regular))
    return regular, bold, lines, size, min_gap, max(7, int(size * 0.38)) * 2.1


def _lieder_pitch_y(staff_top: float, pitch: int, gap: int) -> float:
    """Staff position → y. Position 0 is the bottom line, 8 the top line."""
    return staff_top + 4 * gap - pitch * (gap / 2.0)


def _lieder_draw_glyph(draw, ch: str, font, cx: float, cy: float, fill) -> None:
    """Draw a music glyph with its ink bbox centred on ``(cx, cy)``."""
    x0, y0, x1, y1 = font.getbbox(ch, anchor="ls")
    draw.text((cx - (x0 + x1) / 2.0, cy - (y0 + y1) / 2.0), ch, font=font, fill=fill, anchor="ls")



def _lieder_paint_header(draw, quote_row: dict, time_str: str) -> None:
    """Title (centred), composer credit and tempo mark — the head of a song.

    Title centred at the top, composer flush right below it, tempo mark flush
    left at the same height.
    """
    BLACK = SPECTRA6["black"]
    width = 800  # header is laid out against the canonical canvas; see render_lieder_frame
    _, minute = _lieder_clock(time_str)
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    author = (quote_row.get("author") or "").strip()

    if title:
        font = load_font(theme_font_candidates("lieder", "card_quote_bold"), size=24)
        text = title if len(title) <= 46 else title[:45].rstrip(" ,;:") + "…"
        draw.text((width / 2, 44), text, font=font, fill=BLACK, anchor="ms")

    italic = load_font(theme_font_candidates("lieder", "ornament"), size=16)
    if author:
        name = author if len(author) <= 34 else author[:33].rstrip(" ,;:") + "…"
        draw.text((_LIEDER_MARGIN_R, 82), name, font=italic, fill=BLACK, anchor="rs")

    # Tempo: Italian word + a real quarter-note glyph + the metronome figure.
    word = _LIEDER_TEMPO_WORDS[min(len(_LIEDER_TEMPO_WORDS) - 1, minute // 12)]
    x = _LIEDER_MARGIN_L
    draw.text((x, 82), word, font=italic, fill=BLACK, anchor="ls")
    x += draw.textlength(word, font=italic) + 12
    note_font = load_font([NOTOMUSIC_REGULAR], size=24)
    _lieder_draw_glyph(draw, _MUSIC_QUARTER_NOTE, note_font, x, 76, BLACK)
    draw.text((x + 10, 82), f"= {60 + minute}", font=italic, fill=BLACK, anchor="ls")


def _lieder_paint_clef_and_meter(draw, x: float, staff_top: float, gap: int, numerator: int, first: bool) -> float:
    """Draw the G clef (and, on the first system, the time signature).

    Returns the x at which the notes may begin. The clef's baseline goes on
    the bottom staff line (Noto Music's metric), so no hand-tuned offset.
    """
    BLACK = SPECTRA6["black"]
    staff_bottom = staff_top + 4 * gap
    clef_font = load_font([NOTOMUSIC_REGULAR], size=gap * 4)
    cx0, _, cx1, _ = clef_font.getbbox(_MUSIC_G_CLEF, anchor="ls")
    draw.text((x, staff_bottom), _MUSIC_G_CLEF, font=clef_font, fill=BLACK, anchor="ls")
    x += (cx1 - cx0) + gap

    if first:
        # Numerator centred between the top and middle lines, denominator
        # between the middle and bottom lines — the standard placement.
        meter_font = load_font(theme_font_candidates("lieder", "card_quote_bold"), size=int(gap * 3.0))
        widest = max(draw.textlength(str(numerator), font=meter_font), draw.textlength("4", font=meter_font))
        for text, cy in ((str(numerator), staff_top + gap), ("4", staff_top + 3 * gap)):
            draw.text((x + widest / 2.0, cy), text, font=meter_font, fill=BLACK, anchor="mm")
        x += widest + gap * 1.6
    return x


def _lieder_beam_groups(line: list[dict]) -> list[list[int]]:
    """Index runs of consecutive eighths that should share a beam.

    Eighths are beamed across syllables (modern vocal style; a row of single
    flags reads as noise at a 7 px staff gap). Runs break at a barline and are
    capped at four so they still group by beat.
    """
    groups: list[list[int]] = []
    run: list[int] = []
    for index, note in enumerate(line):
        is_eighth = abs(note["beats"] - 0.5) < 1e-9 and not note.get("rest")
        if run and (not is_eighth or (index > 0 and note.get("bar")) or len(run) >= 4):
            if len(run) >= 2:
                groups.append(run)
            run = []
        if is_eighth:
            run.append(index)
    if len(run) >= 2:
        groups.append(run)
    return groups


def _lieder_paint_head(draw, cx: float, note_y: float, gap: int, note: dict, fill) -> float:
    """Notehead, ledger line and augmentation dot. Returns the notehead width.

    Void notehead for a half or dotted half, filled otherwise.
    """
    note_font = load_font([NOTOMUSIC_REGULAR], size=gap * 4)
    glyph = _MUSIC_NOTEHEAD_VOID if note["beats"] >= 2.0 else _MUSIC_NOTEHEAD
    nx0, _, nx1, _ = note_font.getbbox(glyph, anchor="ls")
    head_w = max(4.0, float(nx1 - nx0))
    _lieder_draw_glyph(draw, glyph, note_font, cx, note_y, fill)

    if note["pitch"] <= _LIEDER_PITCH_MIN or note["pitch"] >= _LIEDER_PITCH_MAX:
        half = head_w / 2.0 + 3
        draw.line((cx - half, note_y, cx + half, note_y), fill=fill, width=1)

    if note["dotted"]:
        # The dot always sits in a space, so a note on a line pushes it up one.
        dot_y = note_y if note["pitch"] % 2 else note_y - gap / 2.0
        dot_x = cx + head_w / 2.0 + 3
        draw.ellipse((dot_x - 1.5, dot_y - 1.5, dot_x + 1.5, dot_y + 1.5), fill=fill)
    return head_w


def _lieder_paint_stem(draw, cx: float, note_y: float, gap: int, head_w: float,
                       down: bool, tip_y: float, flag: bool, fill) -> None:
    """Stem from the notehead to ``tip_y``, with a flag when it stands alone.

    Stems attach left of the head going down, right going up. A flag always
    hangs to the *right* of the stem, whatever the stem direction.
    """
    sx = cx - head_w / 2.0 + 1 if down else cx + head_w / 2.0 - 1
    draw.line((sx, note_y, sx, tip_y), fill=fill, width=1)
    if not flag:
        return
    direction = -1.0 if down else 1.0
    draw.polygon(
        [(sx, tip_y),
         (sx + gap * 0.85, tip_y + direction * gap * 0.55),
         (sx + gap * 0.75, tip_y + direction * gap * 1.45),
         (sx + gap * 0.15, tip_y + direction * gap * 0.8)],
        fill=fill,
    )


def _lieder_paint_rest(draw, cx: float, staff_top: float, gap: int, beats: float, fill) -> None:
    """Draw the rest glyph for ``beats``, at its conventional staff position.

    A whole rest hangs *below* the fourth line, a half rest sits *on* the
    middle line, and quarter / eighth rests centre on the middle line.
    """
    glyph = next((g for value, g in _MUSIC_RESTS if abs(value - beats) < 1e-9), None)
    if glyph is None:
        return
    font = load_font([NOTOMUSIC_REGULAR], size=gap * 4)
    x0, _, x1, y1 = font.getbbox(glyph, anchor="ls")
    if beats >= 2.0:
        # Ink bottom rests on the fourth line (whole) or the middle line (half).
        line = 6 if beats >= 4.0 else 4
        pen_y = _lieder_pitch_y(staff_top, line, gap) - y1
        draw.text((cx - (x0 + x1) / 2.0, pen_y), glyph, font=font, fill=fill, anchor="ls")
    else:
        _lieder_draw_glyph(draw, glyph, font, cx, _lieder_pitch_y(staff_top, 4, gap), fill)


def _lieder_paint_breath(draw, x: float, staff_top: float, gap: int, fill) -> None:
    """Breath mark: the comma above the staff that tells a singer to breathe."""
    top = staff_top - gap * 1.3
    draw.line((x, top, x - gap * 0.35, top + gap * 0.75), fill=fill, width=1)
    draw.line((x, top, x + gap * 0.2, top + gap * 0.3), fill=fill, width=1)


def _lieder_paint_slur(draw, xs: list[float], ys: list[float], gap: int) -> None:
    """Phrase slur arcing over the matched-phrase noteheads.

    A single-syllable phrase gets none. The arc box is validated first —
    ``draw.arc`` raises on an inverted box, which a thumbnail can produce.
    """
    if len(xs) < 2:
        return
    x0, x1 = min(xs), max(xs)
    if x1 - x0 < 4:
        return
    rise = max(4, int(gap * 0.9))
    top = min(ys) - gap * 2.2
    box = (x0, top - rise, x1, top + rise)
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    draw.arc(box, start=180, end=360, fill=SPECTRA6["red"], width=2)


def _lieder_lyric_rise(ctx: dict) -> int:
    """How far the lyric's tallest ink rises above its baseline, in either face."""
    return max(-font.getbbox(_LIEDER_LYRIC_RISE_PROBE, anchor="ls")[1] for font in (ctx["regular"], ctx["bold"]))


def _lieder_beam_y(heads: list[float], down: bool, staff_top: float, gap: int,
                   floor: float) -> tuple[bool, float]:
    """A beamed group's stem direction and beam line. The beam lies a full stem past
    the farthest head, but no lower than ``floor`` (where the lyric's tallest ink
    starts, less a clearance, or ``_LIEDER_BEAM_REACH`` spaces below the staff if that
    is higher) and no higher than ``_LIEDER_BEAM_REACH`` spaces above it, shortening
    the stems as an engraver does, never to under ``_LIEDER_BEAM_MIN_STEM`` past a
    head. A down group that cannot keep that minimum above ``floor`` turns up."""
    if down:
        lowest = max(heads)
        beam = max(min(lowest + _LIEDER_STEM_LEN * gap, floor), lowest + _LIEDER_BEAM_MIN_STEM * gap)
        if beam <= floor:
            return True, beam
    highest = min(heads)
    reach = staff_top - _LIEDER_BEAM_REACH * gap
    return False, min(max(highest - _LIEDER_STEM_LEN * gap, reach), highest - _LIEDER_BEAM_MIN_STEM * gap)


def _lieder_paint_system(draw, ctx: dict, index: int, line: list[dict]) -> None:
    """Engrave one staff: lines, clef/meter, barlines, notes, lyrics, slur.

    Geometry is resolved for the whole system first, because beaming needs to
    know where every stem in a group lands before any of them can be drawn.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    gap = ctx["gap"]
    staff_top = ctx["staff_tops"][index]
    staff_bottom = staff_top + 4 * gap
    last_system = index == len(ctx["staff_tops"]) - 1

    for i in range(5):
        y = staff_top + i * gap
        draw.line((_LIEDER_MARGIN_L, y, _LIEDER_MARGIN_R, y), fill=BLACK, width=1)

    x = _lieder_paint_clef_and_meter(draw, _LIEDER_MARGIN_L + 5, staff_top, gap, ctx["numerator"], index == 0)

    # Justify: hand the leftover width back to the notes in proportion to the
    # space each already claims, so a held note keeps its extra room.
    slots = [_lieder_slot(n, ctx["min_gap"], ctx["base"]) for n in line]
    avail = _LIEDER_MARGIN_R - x - gap * 2
    natural = sum(slots)
    if natural > 0 and avail > natural:
        stretch = min(avail / natural, 2.4 if last_system else 6.0)
        slots = [s * stretch for s in slots]

    # Pass 1: where every note sits.
    xs: list[float] = []
    ys: list[float] = []
    cursor = x
    for note, slot in zip(line, slots, strict=True):
        xs.append(cursor + slot / 2.0)
        ys.append(_lieder_pitch_y(staff_top, note["pitch"], gap))
        cursor += slot

    # Pass 2: beam groups. A whole group shares one stem direction (majority
    # side of the middle line) and one horizontal beam clear of every head in it,
    # kept above the lyric's tallest ink (``_lieder_beam_y``), so a group mixing
    # high and low heads cannot hang its beam into the words.
    stem_h = _LIEDER_STEM_LEN * gap
    beamed: dict[int, tuple[bool, float]] = {}
    beams: list[tuple[float, float, float, bool]] = []
    beam_floor = min(staff_bottom + _LIEDER_BEAM_REACH * gap,
                     staff_bottom + _LIEDER_LYRIC_OFFSET * gap - _lieder_lyric_rise(ctx) - _LIEDER_BEAM_CLEARANCE)
    for run in _lieder_beam_groups(line):
        down = sum(1 for i in run if line[i]["pitch"] >= 4) * 2 >= len(run)
        down, beam_y = _lieder_beam_y([ys[i] for i in run], down, staff_top, gap, beam_floor)
        for i in run:
            beamed[i] = (down, beam_y)
        beams.append((xs[run[0]], xs[run[-1]], beam_y, down))

    lyric_baseline = staff_bottom + _LIEDER_LYRIC_OFFSET * gap
    matched_xs: list[float] = []
    matched_ys: list[float] = []
    cursor = x
    for position, (note, slot) in enumerate(zip(line, slots, strict=True)):
        cx, note_y = xs[position], ys[position]

        if note.get("bar"):
            bar_x = cursor - ctx["min_gap"] * 0.35 if position > 0 else x - gap * 0.8
            if _LIEDER_MARGIN_L < bar_x < _LIEDER_MARGIN_R:
                draw.line((bar_x, staff_top, bar_x, staff_bottom), fill=BLACK, width=1)

        ink = RED if note["matched"] else BLACK
        if note.get("rest"):
            _lieder_paint_rest(draw, cx, staff_top, gap, note["beats"], BLACK)
            cursor += slot
            continue
        head_w = _lieder_paint_head(draw, cx, note_y, gap, note, ink)
        if position in beamed:
            down, beam_y = beamed[position]
            _lieder_paint_stem(draw, cx, note_y, gap, head_w, down, beam_y, False, ink)
        else:
            down = note["pitch"] >= 4
            tip = note_y + stem_h if down else note_y - stem_h
            _lieder_paint_stem(draw, cx, note_y, gap, head_w, down,
                               tip, abs(note["beats"] - 0.5) < 1e-9, ink)
        if note["matched"]:
            matched_xs.append(cx)
            matched_ys.append(note_y)

        font = ctx["bold"] if note["matched"] else ctx["regular"]
        draw.text((cx, lyric_baseline), note["text"], font=font, fill=ink, anchor="ms")

        # Lyric hyphen, centred in the gap to the next syllable of the same word.
        if note["hyphen"] and position + 1 < len(line):
            left = cx + note["width"] / 2.0
            right = xs[position + 1] - line[position + 1]["width"] / 2.0
            if right - left > 4:
                mid = (left + right) / 2.0
                hy = lyric_baseline - ctx["size"] * 0.28
                draw.line((mid - 2, hy, mid + 2, hy), fill=ink, width=1)

        if note["breath"]:
            _lieder_paint_breath(draw, cursor + slot, staff_top, gap, BLACK)
        cursor += slot

    # Beams last, so they sit over the stems they cap.
    thickness = max(2, int(gap * 0.5))
    for bx0, bx1, by, down in beams:
        top = by - thickness if down else by
        draw.rectangle((bx0 - 1, top, bx1 + 1, top + thickness), fill=BLACK)

    _lieder_paint_slur(draw, matched_xs, matched_ys, gap)

    if last_system:
        draw.line((_LIEDER_MARGIN_R - 6, staff_top, _LIEDER_MARGIN_R - 6, staff_bottom), fill=BLACK, width=1)
        draw.rectangle((_LIEDER_MARGIN_R - 3, staff_top, _LIEDER_MARGIN_R, staff_bottom), fill=BLACK)
    if index == 1:
        italic = load_font(theme_font_candidates("lieder", "ornament"), size=14)
        draw.text((_LIEDER_MARGIN_L + 4, staff_top - gap * 1.4), ctx["expression"], font=italic, fill=BLACK, anchor="ls")


def _lieder_paint_plate_line(draw, quote_row: dict, width: int, height: int) -> None:
    """Engraver's plate number, centred at the foot — real scores carry one."""
    source_id = str(quote_row.get("source_id") or "").strip()
    text = f"Idle Hours Edition · Pl. {source_id}" if source_id else "Idle Hours Edition"
    font = load_font(theme_font_candidates("lieder", "ornament"), size=13)
    draw.text((width / 2, height - 22), text, font=font, fill=SPECTRA6["black"], anchor="ms")


def render_lieder_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Engraved art-song manuscript (``docs/themes.md`` § lieder).

    Five passes, in dependency order: split the text into sung syllables, give
    them durations and barlines, give them pitches (which needs the barlines,
    since downbeats pull toward the chord), fit and wrap them, then engrave.

    Laid out against the canonical 800×480; smaller canvases (``/api/preview``
    thumbnails) crop rather than reflow. Every primitive is an ``ImageDraw``
    call, which clips silently, so no per-call bounds checks are needed.
    """
    image = Image.new("RGB", (width, height), color=SPECTRA6["white"])
    _astrarium_paint_cream_wash(image)
    draw = ImageDraw.Draw(image)

    hour, _ = _lieder_clock(time_str)
    seed = _row_digest(quote_row)
    notes = _lieder_notes(quote_row)
    if not notes:
        notes = [{"text": "—", "matched": False, "hyphen": False, "breath": False, "stress": 2, "word": 0}]

    gap = _LIEDER_STAVE_GAP
    clef_font = load_font([NOTOMUSIC_REGULAR], size=gap * 4)
    cx0, _, cx1, _ = clef_font.getbbox(_MUSIC_G_CLEF, anchor="ls")
    clef_w = (cx1 - cx0) + gap + 5
    meter_w = gap * 4.6  # the first system also carries the time signature
    span = _LIEDER_MARGIN_R - _LIEDER_MARGIN_L - gap * 2
    widths = [int(span - clef_w - meter_w), int(span - clef_w)]

    _lieder_rhythm(notes, hour)
    _lieder_contour(seed, notes)
    regular, bold, lines, size, min_gap, base = _lieder_fit(draw, notes, widths, gap)

    core = _lieder_system_core(size, gap)
    band_top, band_bottom = _LIEDER_BAND
    block = len(lines) * core + (len(lines) - 1) * _LIEDER_SYSTEM_GAP
    # Slack goes 1/3 above, 2/3 below: engraved music hangs from the top of its
    # type area, and a centred one-system song floats stranded mid-page.
    top = band_top + max(0, (band_bottom - band_top - block) // 3)
    staff_tops = [top + int(_LIEDER_HEADROOM * gap) + i * (core + _LIEDER_SYSTEM_GAP) for i in range(len(lines))]

    ctx = {
        "gap": gap, "regular": regular, "bold": bold, "min_gap": min_gap, "base": base,
        "size": size, "numerator": hour, "staff_tops": staff_tops,
        "expression": _LIEDER_EXPRESSION[seed % len(_LIEDER_EXPRESSION)],
    }
    _lieder_paint_header(draw, quote_row, time_str)
    for index, line in enumerate(lines):
        _lieder_paint_system(draw, ctx, index, line)
    _lieder_paint_plate_line(draw, quote_row, width, height)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


# ─── lieder sleep frame: Brahms, Wiegenlied, Op. 49 No. 4 ───────────────────
#
# The opening phrase of the Lullaby, engraved with the quote frame's own
# painters, in C major (no key signature; Brahms wrote it in E♭). Each entry is
# (syllable, pitch, beats, word continues). The 3/4 phrase opens on a two-quaver
# upbeat: E E | G. E E | G — and a quarter rest stands in for the next
# phrase's upbeat ("mit Ro-"), so the second bar closes full.
_LIEDER_SLEEP_MELODY: tuple[tuple[str, str, float, bool], ...] = (
    ("Gu", "E4", 0.5, True),
    ("ten", "E4", 0.5, False),
    ("A", "G4", 1.5, True),
    ("bend,", "E4", 0.5, False),
    ("gut'", "E4", 1.0, False),
    ("Nacht,", "G4", 2.0, False),
)
_LIEDER_SLEEP_REST = 1.0                 # completes bar 2
_LIEDER_SLEEP_BARS = (2, 5)              # melody indices that open a bar
_LIEDER_SLEEP_RED = ("gut'", "Nacht,")   # "good night", sung in the theme's red
# Staff positions (0 = bottom line) for the pitches the phrase uses.
_LIEDER_SLEEP_POSITIONS = {"E4": 0, "G4": 2}
_LIEDER_SLEEP_GAP = 12                   # larger stave than the quote frame's: one system only
_LIEDER_SLEEP_STAFF_TOP = 152
_LIEDER_SLEEP_LYRIC_SIZE = 28
_LIEDER_SLEEP_STANZA = (
    "Guten Abend, gut' Nacht, mit Rosen bedacht,",
    "mit Näglein besteckt, schlupf' unter die Deck':",
    "Morgen früh, wenn Gott will, wirst du wieder geweckt.",
)
_LIEDER_SLEEP_STANZA_TOP = 338
_LIEDER_SLEEP_STANZA_LEADING = 29


def _lieder_sleep_notes() -> list[dict]:
    """The melody constant as note dicts ``_lieder_paint_system`` understands."""
    notes: list[dict] = []
    for index, (text, pitch, beats, hyphen) in enumerate(_LIEDER_SLEEP_MELODY):
        notes.append({
            "text": text, "matched": text in _LIEDER_SLEEP_RED, "hyphen": hyphen, "breath": False,
            "stress": 0, "word": index, "beats": beats, "dotted": _lieder_is_dotted(beats),
            "bar": index in _LIEDER_SLEEP_BARS, "pitch": _LIEDER_SLEEP_POSITIONS[pitch],
        })
    notes.append({
        "text": "", "matched": False, "hyphen": False, "breath": False, "stress": 0,
        "word": len(notes), "beats": _LIEDER_SLEEP_REST, "dotted": False, "bar": False,
        "rest": True, "pitch": 4,
    })
    return notes


def _lieder_sleep_base(notes: list[dict], min_gap: int, avail: float) -> float:
    """Duration-spacing base that lets the one system fill the stave.

    ``_lieder_paint_system`` stretches a last system by at most 2.4×, which a
    six-note phrase cannot reach; widening the base instead keeps duration
    spacing proportional across the whole line.
    """
    base = float(min_gap)
    while base < avail and sum(_lieder_slot(n, min_gap, base) for n in notes) < avail:
        base += 1.0
    return base


def _lieder_paint_sleep_header(draw) -> None:
    """Title centred, poet credit left and composer right, as a song is headed."""
    black = SPECTRA6["black"]
    title = load_font(theme_font_candidates("lieder", "card_quote_bold"), size=34)
    draw.text((400, 52), "Wiegenlied", font=title, fill=black, anchor="ms")
    italic = load_font(theme_font_candidates("lieder", "ornament"), size=17)
    draw.text((_LIEDER_MARGIN_L, 96), "Aus Des Knaben Wunderhorn", font=italic, fill=black, anchor="ls")
    draw.text((_LIEDER_MARGIN_R, 96), "Johannes Brahms, Op. 49 No. 4", font=italic, fill=black, anchor="rs")


def _lieder_paint_sleep_stanza(draw) -> None:
    """The rest of the first verse, set as text beneath the music."""
    italic = load_font(theme_font_candidates("lieder", "ornament"), size=21)
    for i, line in enumerate(_LIEDER_SLEEP_STANZA):
        y = _LIEDER_SLEEP_STANZA_TOP + i * _LIEDER_SLEEP_STANZA_LEADING
        draw.text((400, y), line, font=italic, fill=SPECTRA6["black"], anchor="ms")


def render_lieder_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: the opening of Brahms's *Wiegenlied* engraved as
    the song's first system, "gut' Nacht" sung in red under its slur.

    Same cream wash, clef, noteheads, beams, lyric face and plate line as the
    quote frame, so it is the same manuscript put to bed. Composed at the
    canonical 800×480 and NEAREST-downsampled. ``time_str`` is unused: the
    meter is the song's 3/4, not the hour.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _astrarium_paint_cream_wash(image)
    draw = ImageDraw.Draw(image)

    gap = _LIEDER_SLEEP_GAP
    regular = load_font(theme_font_candidates("lieder", "quote_regular"), size=_LIEDER_SLEEP_LYRIC_SIZE)
    bold = load_font(theme_font_candidates("lieder", "quote_bold"), size=_LIEDER_SLEEP_LYRIC_SIZE)
    notes = _lieder_sleep_notes()
    for note in notes:
        note["width"] = int(draw.textlength(note["text"], font=bold if note["matched"] else regular))
    min_gap = max(7, int(_LIEDER_SLEEP_LYRIC_SIZE * 0.38))

    # Where the notes may start, as _lieder_paint_system will compute it.
    clef_font = load_font([NOTOMUSIC_REGULAR], size=gap * 4)
    cx0, _, cx1, _ = clef_font.getbbox(_MUSIC_G_CLEF, anchor="ls")
    meter_font = load_font(theme_font_candidates("lieder", "card_quote_bold"), size=int(gap * 3.0))
    meter_w = max(draw.textlength("3", font=meter_font), draw.textlength("4", font=meter_font))
    start = _LIEDER_MARGIN_L + 5 + (cx1 - cx0) + gap + meter_w + gap * 1.6
    avail = _LIEDER_MARGIN_R - start - gap * 2

    ctx = {
        "gap": gap, "regular": regular, "bold": bold, "min_gap": min_gap,
        "base": _lieder_sleep_base(notes, min_gap, avail), "size": _LIEDER_SLEEP_LYRIC_SIZE,
        "numerator": 3, "staff_tops": [_LIEDER_SLEEP_STAFF_TOP], "expression": "",
    }
    _lieder_paint_sleep_header(draw)
    _lieder_paint_system(draw, ctx, 0, notes)
    _lieder_paint_sleep_stanza(draw)
    _lieder_paint_plate_line(draw, {}, 800, 480)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("lieder",), render=render_lieder_frame, sleep=render_lieder_sleep)
