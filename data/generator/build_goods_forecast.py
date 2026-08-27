# -*- coding: utf-8 -*-
"""Emit data/supply/goods_forecast.csv (Data Spec 10.2).

Freight is not in the passenger working timetable (Blueprint 5.3): a gap that
looks empty may be filled by a port-bound rake. This table is what converts an
apparent gap into a probabilistic one, so the window enumerator does not hand the
optimiser a window that a coal rake to Ennore is about to occupy.

One row per (forecast_date, freight edge, time_band). The *pattern* is grounded
(spec 12.3 names "port-bound freight patterns on the northern line" as real): the
northern line carries the Chennai Port / Kamarajar (Ennore) traffic and peaks
overnight, which is precisely why Blueprint 5.4 places the freight corridor block
mid-morning, after the peak. The per-day rake counts are synthesised around that
pattern with a fixed seed - no system publishes a forward freight forecast, so
this bucket cannot be anything but modelled, and it says so.

Forecast horizon is 14 days from the pilot's 2026-09-07 "today", covering the
weekly planner's window with margin.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import random

SEED = 26027
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")
SUPPLY = os.path.join(HERE, os.pardir, "supply")

TODAY = dt.date(2026, 9, 7)
HORIZON_DAYS = 14

TIME_BANDS = ["00-06", "06-12", "12-18", "18-24"]
# Overnight and evening are the freight peak to the ports; mid-morning is the
# trough, which is why the freight corridor block sits there (Blueprint 5.4).
BAND_MULT = {"00-06": 1.0, "06-12": 0.35, "12-18": 0.6, "18-24": 0.9}

# The port hub: Chennai Port and Basin Bridge yard feed Kamarajar (Ennore) Port
# and Ennore thermal, so the Basin Bridge - Ennore stretch is heaviest; beyond
# Ennore the line carries through-freight north to Gudur.
PORT_HUB = {"BBQ", "TNP", "ENR"}

HEADER = ["forecast_date", "block_section_id", "time_band",
          "expected_rakes", "confidence"]


def load(name):
    with open(os.path.join(REF, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def base_rakes(sec):
    """Overnight-peak rake count for a section, before the band multiplier."""
    if sec["traffic_type"] == "freight":
        near_port = sec["from_station"] in PORT_HUB or sec["to_station"] in PORT_HUB
        return 7 if near_port else 4
    if sec["traffic_type"] == "trunk":
        return 3  # through-freight to the interior, lighter than the port line
    return 0


def build():
    rng = random.Random(SEED)
    sections = load("block_sections.csv")
    # Freight runs on the main running lines, not the dedicated suburban pairs or
    # the single-line branch. That is the northern freight line and the trunk.
    edges = [s for s in sections
             if s["line_id"] in ("UP", "DN")
             and s["traffic_type"] in ("freight", "trunk")]
    edges.sort(key=lambda r: r["block_section_id"])

    rows = []
    for d in range(HORIZON_DAYS):
        date = TODAY + dt.timedelta(days=d)
        weekend = date.weekday() >= 5  # ports ease slightly at the weekend
        for sec in edges:
            base = base_rakes(sec)
            for band in TIME_BANDS:
                mult = BAND_MULT[band]
                dayvar = rng.uniform(0.75, 1.25) * (0.85 if weekend else 1.0)
                rakes = max(0, int(round(base * mult * dayvar)))
                # Confidence is higher for the regular overnight flow, lower for
                # sporadic daytime spot moves.
                conf = 0.55 + 0.30 * mult + rng.uniform(-0.05, 0.05)
                rows.append({
                    "forecast_date": date.isoformat(),
                    "block_section_id": sec["block_section_id"],
                    "time_band": band,
                    "expected_rakes": rakes,
                    "confidence": "%.2f" % min(0.92, max(0.40, conf)),
                })
    return rows


def main():
    rows = build()
    if not os.path.isdir(SUPPLY):
        os.makedirs(SUPPLY)
    out = os.path.join(SUPPLY, "goods_forecast.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    edges = len({r["block_section_id"] for r in rows})
    print("goods_forecast.csv: %d rows over %d edges, %d days"
          % (len(rows), edges, HORIZON_DAYS))


if __name__ == "__main__":
    main()
