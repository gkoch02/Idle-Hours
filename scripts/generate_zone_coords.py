#!/usr/bin/env python3
"""Generate ``idle_hours/assets/zone_coords.json``: a latitude and longitude for every IANA
time zone name, for the ``astrarium`` theme's solar elevation.

The clock knows its time zone and nothing else about where it is, and that is all the sky
needs to be roughly right: tzdata's ``zone.tab`` gives each zone the coordinates of its
principal city (Los Angeles for ``America/Los_Angeles``), which is within a few degrees of
anywhere the zone is kept. Asking for a location would be more exact and is personal data;
the zone is not.

``zone.tab`` names only canonical zones, and a device may report a link (``US/Pacific``,
``Asia/Calcutta``: Apple's platforms still use some of the old names). The installed
``tzdata.zi`` lists every link (``L Europe/London GB``), and a link takes its target's place.
A name in neither (``UTC``, ``Etc/GMT+8``) is left out: the renderer then places the clock on
the equator at its UTC offset's meridian.

Usage: python3 scripts/generate_zone_coords.py [--zoneinfo /usr/share/zoneinfo]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "idle_hours" / "assets" / "zone_coords.json"


def parse_iso6709(text: str) -> tuple[float, float]:
    """``+3403-11815`` or ``-690022+0393524`` as decimal degrees."""
    m = re.fullmatch(r"([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?", text)
    if not m:
        raise ValueError(f"bad coordinates {text!r}")
    sa, ad, am, as_, so, od, om, os_ = m.groups()
    lat = int(ad) + int(am) / 60 + int(as_ or 0) / 3600
    lon = int(od) + int(om) / 60 + int(os_ or 0) / 3600
    return (-lat if sa == "-" else lat, -lon if so == "-" else lon)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--zoneinfo", type=Path, default=Path("/usr/share/zoneinfo"))
    args = parser.parse_args()
    root = args.zoneinfo

    canonical: dict[str, tuple[float, float]] = {}
    for line in (root / "zone.tab").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        lat, lon = parse_iso6709(fields[1])
        canonical[fields[2]] = (round(lat, 4), round(lon, 4))

    zones = dict(canonical)
    for line in (root / "tzdata.zi").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "L" and fields[1] in canonical:
            zones.setdefault(fields[2], canonical[fields[1]])

    OUT.write_text(json.dumps({"source": "tzdata zone.tab, links from tzdata.zi",
                               "zones": dict(sorted(zones.items()))},
                              indent=0, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {len(canonical)} zones and {len(zones) - len(canonical)} links to {OUT}")


if __name__ == "__main__":
    main()
