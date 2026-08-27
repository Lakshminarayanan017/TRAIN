# -*- coding: utf-8 -*-
"""Emit data/supply/corridor_windows.csv (Data Spec 10.3).

The pre-planned corridor blocks: windows already negotiated into the working
timetable, which the optimiser reads directly (Blueprint 5.1) rather than
detecting. One row per (edge, weekly occurrence).

Generated from the documented pattern in Blueprint 5.4 - the rule set is
configuration, and on deployment this file is replaced wholesale by the
division's actual corridor block table. No claim is made that these are Chennai
Division's real corridor blocks (Blueprint 5.4, "Stated limitation").

The four patterns, verbatim from Blueprint 5.4:
  - Chennai Central - Arakkonam (quadruple trunk): 2 h per line per week, night
    slot 01:00-03:00, staggered across sections.
  - Chennai Beach - Tambaram (saturated suburban): 3 h per line, twice weekly,
    00:30-03:30 - no daytime capacity exists.
  - Arakkonam - Kanchipuram - Chengalpattu (single line): 3 h once weekly,
    mid-morning - low density means a daytime window genuinely exists.
  - Basin Bridge - Gummidipoondi (freight): 2 h twice weekly, mid-morning,
    after the overnight freight peak.

Staggering matters: the parallel lines of one span must never all fall on the
same night, or the corridor block itself would sever the section. Days are
assigned so each span's lines land on different days.
"""
from __future__ import print_function

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")
SUPPLY = os.path.join(HERE, os.pardir, "supply")

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# corridor -> (start_time, duration_min, occurrences_per_week, max_departments)
PATTERN = {
    "MAS-AJJ": ("01:00", 120, 1, 3),   # quadruple trunk, one night slot per line
    "MSB-TBM": ("00:30", 180, 2, 3),   # saturated suburban, twice weekly
    "AJJ-CGL": ("10:00", 180, 1, 2),   # single line, once weekly, mid-morning
    "BBQ-GPD": ("10:00", 120, 2, 2),   # freight, twice weekly, mid-morning
}

HEADER = ["window_id", "block_section_id", "day_of_week", "start_time",
          "duration_min", "window_type", "max_departments"]


def load(name):
    with open(os.path.join(REF, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build():
    sections = load("block_sections.csv")
    by_corridor = {}
    for s in sections:
        by_corridor.setdefault(s["corridor_id"], []).append(s)

    rows = []
    for corridor, edges in by_corridor.items():
        start, dur, freq, max_dept = PATTERN[corridor]
        edges.sort(key=lambda r: r["block_section_id"])
        for idx, sec in enumerate(edges):
            for k in range(freq):
                # Stagger across sections (idx) and across a span's parallel
                # lines (idx already differs per line, since each edge is one
                # row); the second weekly occurrence lands +3 days on, keeping
                # the two blocks of one line well apart.
                day = DAYS[(idx * freq + k * 3) % 7]
                rows.append({
                    "window_id": "W-%s%s-%s-%s"
                    % (sec["from_station"], sec["to_station"], sec["line_id"], day),
                    "block_section_id": sec["block_section_id"],
                    "day_of_week": day,
                    "start_time": start,
                    "duration_min": dur,
                    "window_type": "corridor_block",
                    "max_departments": max_dept,
                })
    return rows


def main():
    rows = build()
    if not os.path.isdir(SUPPLY):
        os.makedirs(SUPPLY)
    out = os.path.join(SUPPLY, "corridor_windows.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print("corridor_windows.csv: %d windows over %d edges"
          % (len(rows), len({r["block_section_id"] for r in rows})))


if __name__ == "__main__":
    main()
