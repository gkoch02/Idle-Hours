# Semiotic Standard signs

`../semiotic_signs.png` — the sprite sheet the `semiotic` theme paints its
signs from — is built from **Semiotic Standard** by
[LouH](https://github.com/louh/semiotic-standard), licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

- Original designs: Ron Cobb, *Semiotic Standard For All Commercial
  Trans-Stellar Utility Lifter And Heavy Element Transport Spacecraft*, drawn
  for *Alien* (1979) and republished in his book *Colorvision* (1981).
- Vector adaptation: LouH, after Brandon Gamm's recreations on The Noun
  Project. See also <https://semioticstandard.org>.
- Source commit: `louh/semiotic-standard@21a46f6d2c57a02449083ede0c98818f7bfe11b6`
- Built by: `scripts/ingest_semiotic_signs.py`

**Changes made:** the 34 signs are downscaled to 250×262 px and packed into
one sheet in legend order (001–030, with 020A–C and 029A). At render time each
sign is resized and its colours re-mapped onto the Spectra 6 panel's six inks
(the mid grey becomes a black/white checkerboard stipple).
