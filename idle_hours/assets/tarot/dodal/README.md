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

`trump_01.jpg` to `trump_12.jpg` are the original-resolution files served by
Wikimedia Commons. `trump_18.jpg` was supplied directly by the maintainer at
213×395, smaller than the Commons originals (257×474), and is believed to be
the same deck's XVIII. If the Commons original-resolution file is added in its
place, regenerate the plate with
`python3 scripts/ingest_tarot_plates.py --single --input idle_hours/assets/tarot/dodal/trump_18.jpg --output idle_hours/assets/tarot_moon.png`;
`tests/test_ingest_tarot_plates.py` fails until the plate matches its scan.
