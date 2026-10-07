# Jean Dodal tarot trumps

These scans are trumps I–XII and XVIII from Jean Dodal's *Tarot de Marseille*
(Lyon, 1701–1715). I–XII are the tarot theme's hour-mapped illustrations;
XVIII, *La Lune*, is its sleep frame. They are kept together so build tooling
can consume them without mixing raw scans with generated runtime assets.

- Source: [Wikimedia Commons category](https://commons.wikimedia.org/wiki/Category:Tarot_de_Marseille_-_Jean_Dodal)
- Files: `trump_01.jpg` through `trump_12.jpg`, and `trump_18.jpg`
- Creator: Jean Dodal
- Rights: public domain
- Commons credit: [tarot-history.com/Jean-Dodal](http://www.tarot-history.com/Jean-Dodal/)

The images are the original-resolution files served by Wikimedia Commons.
`trump_18.jpg` is [File:Jean_Dodal_Tarot_trump_18.jpg](https://commons.wikimedia.org/wiki/File:Jean_Dodal_Tarot_trump_18.jpg)
from the same category, at 213×395, inside the deck's own 205–258 px range of
scan widths. If any scan is replaced, regenerate its plate with the ingest
script (`--single` for XVIII); `tests/test_ingest_tarot_plates.py` fails until
each committed plate matches its scan.
