# -*- coding: utf-8 -*-
"""Emit data/supply/train_paths.csv (Data Spec 10.1).

One row per (train, block_section): the window a train occupies one edge, which
is what the window enumerator (Blueprint 5.2) subtracts from the day to find the
gaps maintenance can work in.

Real identities, computed timing. Two rules govern this file:

1. **Train identity is real, not invented.** The named long-distance and express
   trains carry their actual Indian Railways number, type, priority and running
   days. Chennai-origin departure times are the real ones where verified
   (Shatabdi 06:00, Double Decker 07:25, Brindavan 07:40, Chennai-Howrah Mail
   23:45, Coromandel 08:45, ...); return-direction anchors and a few others are
   approximate, and flagged as such in train_paths.README.md. The user asked for
   real identities with computed times rather than a scraped timetable, so the
   clock anchor is allowed to be approximate while the train is real.

2. **Per-section times are physics, not guesses.** entry/exit on each edge are
   accumulated from the origin anchor and the section run-time = length / speed,
   where speed is the train type's cruising speed capped by the edge's
   sectional_speed_kmph. Stopping types dwell briefly at each block station.
   Nothing is copied from a timetable that could be stale.

The high-frequency EMU / MEMU / goods services are generated from headway
patterns. Their *frequency* is grounded (Blueprint 5.3, spec 12.3: "approximate
suburban headways"); the individual service numbers are representative, drawn in
the real IR series ranges, not claimed as specific timetabled services.

Fixed seed per 12.5, though this generator is almost entirely deterministic.
"""
from __future__ import print_function

import csv
import os
import random

SEED = 26027
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")
SUPPLY = os.path.join(HERE, os.pardir, "supply")

# Cruising speed by train type, km/h. Capped per edge by sectional_speed_kmph, so
# a fast train on a slow suburban edge still crawls. These are averages that fold
# in acceleration from a stop, not maxima.
TYPE_SPEED = {
    "rajdhani_class": 75, "superfast": 68, "express": 55, "passenger": 45,
    "MEMU": 42, "EMU": 40, "goods": 30, "special": 50, "light_engine": 55,
}

# Dwell at each intermediate block station, minutes. Expresses run through the
# modelled block stations without booking a stop; stopping types lose time.
DWELL = {"EMU": 0.6, "MEMU": 0.8, "passenger": 1.0}

# Ordered block-station runs, listed away from Chennai (increasing chainage). A
# service travelling towards Chennai walks these in reverse.
ROUTES = {
    "TRUNK":  ["MAS", "BBQ", "PER", "ABU", "AVD", "TI", "TRL", "AJJ"],
    "TRUNK_AVD": ["MAS", "BBQ", "PER", "ABU", "AVD"],
    "NORTH":  ["MAS", "BBQ", "TNP", "ENR", "MJR", "PON", "GPD"],
    "SOUTH":  ["MSB", "MS", "MBM", "GI", "STM", "PV", "TBM"],
    "SOUTH_MS": ["MS", "MBM", "GI", "STM", "PV", "TBM"],
    "BRANCH": ["CGL", "WJ", "CJ", "TMLP", "TKO", "AJJ"],
}


def line_for(kind, direction):
    """Away from Chennai runs on the DN group, towards it on the UP group; the
    single-line branch has one line either way."""
    if kind == "single":
        return "SINGLE"
    suffix = "_SUB" if kind == "sub" else ""
    return ("DN" if direction == "away" else "UP") + suffix


# --- named real trains -------------------------------------------------------
# (train_no, type, priority_class, route, direction, line_kind, anchor_hhmm,
#  days_mon_sun, divertible). anchor is the clock time at the FIRST station of
#  travel order: a real Chennai departure for away trains, an approximate pilot
#  entry for towards trains (see README).
NAMED = [
    # Trunk, Chennai Central towards Bengaluru / Tirupati via Arakkonam.
    (12007, "superfast", 1, "TRUNK", "away", "main", "06:00", "1110111", True),
    (16057, "express",   3, "TRUNK", "away", "main", "06:25", "1111111", True),
    (22625, "superfast", 2, "TRUNK", "away", "main", "07:25", "1111111", True),
    (12639, "superfast", 2, "TRUNK", "away", "main", "07:40", "1111111", True),
    (12609, "superfast", 2, "TRUNK", "away", "main", "13:35", "1111111", True),
    (12027, "superfast", 1, "TRUNK", "away", "main", "17:30", "1101111", True),
    (16021, "express",   3, "TRUNK", "away", "main", "21:15", "1111111", True),
    (12658, "superfast", 2, "TRUNK", "away", "main", "22:40", "1111111", True),
    # Trunk, towards Chennai (approximate pilot entry at Arakkonam).
    (12657, "superfast", 2, "TRUNK", "toward", "main", "05:00", "1111111", True),
    (12640, "superfast", 2, "TRUNK", "toward", "main", "12:40", "1111111", True),
    (16058, "express",   3, "TRUNK", "toward", "main", "20:30", "1111111", True),
    (12008, "superfast", 1, "TRUNK", "toward", "main", "21:05", "1110111", True),
    # Northern line, Chennai Central towards Gudur / Vijayawada / Howrah.
    (12841, "superfast", 1, "NORTH", "away", "main", "08:45", "1111111", True),
    (12759, "superfast", 2, "NORTH", "away", "main", "18:10", "1111111", True),
    (12616, "superfast", 2, "NORTH", "away", "main", "19:15", "1111111", True),
    (12622, "superfast", 2, "NORTH", "away", "main", "22:00", "1111111", True),
    (12840, "superfast", 2, "NORTH", "away", "main", "23:45", "1111111", True),
    # Northern line, towards Chennai (approximate pilot entry at Gummidipoondi).
    (12842, "superfast", 1, "NORTH", "toward", "main", "05:40", "1111111", True),
    (12621, "superfast", 2, "NORTH", "toward", "main", "04:30", "1111111", True),
    (12839, "superfast", 2, "NORTH", "toward", "main", "02:30", "1111111", True),
    # Southern line, Chennai Egmore towards Villupuram (modelled to Tambaram).
    (20627, "rajdhani_class", 1, "SOUTH_MS", "away", "main", "05:00", "1101111", False),
    (16128, "express",   3, "SOUTH_MS", "away", "main", "07:45", "1111111", True),
    (12635, "superfast", 2, "SOUTH_MS", "away", "main", "13:40", "1111111", True),
    (22153, "superfast", 2, "SOUTH_MS", "away", "main", "23:55", "1111111", True),
    # Southern line, towards Egmore (approximate pilot entry at Tambaram).
    (22154, "superfast", 2, "SOUTH_MS", "toward", "main", "05:20", "1111111", True),
    (12636, "superfast", 2, "SOUTH_MS", "toward", "main", "21:30", "1111111", True),
]

# --- headway patterns for the high-frequency services ------------------------
# (route, direction, line_kind, type, priority, headway_min, start_hhmm,
#  end_hhmm, days, number_base, divertible). One service per headway slot, in
#  both directions where listed twice.
PATTERNS = [
    # Saturated Beach-Tambaram suburban, all-stations on the slow pair: ~6 min.
    ("SOUTH", "away",  "sub", "EMU", 5, 6, "04:00", "23:30", "1111111", 43000, False),
    ("SOUTH", "toward","sub", "EMU", 5, 6, "04:00", "23:30", "1111111", 43500, False),
    # Fast suburban on the Beach-Tambaram main pair: ~12 min. This is what runs on
    # the main lines the Egmore expresses share, and it covers the Beach-Egmore
    # main span the Egmore-origin expresses never touch.
    ("SOUTH", "away",  "main", "EMU", 5, 12, "04:30", "23:00", "1111111", 42500, False),
    ("SOUTH", "toward","main", "EMU", 5, 12, "04:30", "23:00", "1111111", 42600, False),
    # Trunk suburban is dense near Chennai and thins outward, so the frequent EMU
    # turns back at Avadi; only the ~20 min MEMU carries on to Arakkonam. This
    # reproduces the decreasing sub count the reference layer records (175 -> 55).
    ("TRUNK_AVD", "away",  "sub", "EMU", 5, 10, "04:00", "23:00", "1111111", 41000, False),
    ("TRUNK_AVD", "toward","sub", "EMU", 5, 10, "04:00", "23:00", "1111111", 41500, False),
    ("TRUNK", "away",  "sub", "MEMU", 4, 20, "04:30", "22:30", "1111111", 66000, False),
    ("TRUNK", "toward","sub", "MEMU", 4, 20, "04:30", "22:30", "1111111", 66500, False),
    # Northern MEMU to Gummidipoondi on the running lines: ~30 min.
    ("NORTH", "away",  "main", "MEMU", 4, 30, "04:00", "22:30", "1111111", 43800, True),
    ("NORTH", "toward","main", "MEMU", 4, 30, "04:00", "22:30", "1111111", 43850, True),
    # Single-line branch EMU: sparse, matching the 14-18 trains/day on the edge.
    ("BRANCH", "away",  "single", "EMU", 5, 110, "05:00", "21:00", "1111111", 44000, False),
    ("BRANCH", "toward","single", "EMU", 5, 110, "05:00", "21:00", "1111111", 44050, False),
    # Goods: trunk paths through the night, port-bound freight on the north line.
    ("TRUNK", "away",  "main", "goods", 6, 95, "00:00", "23:59", "1111111", 55000, True),
    ("TRUNK", "toward","main", "goods", 6, 95, "00:00", "23:59", "1111111", 55100, True),
    ("NORTH", "away",  "main", "goods", 6, 60, "00:00", "23:59", "1111111", 55500, True),
    ("NORTH", "toward","main", "goods", 6, 60, "00:00", "23:59", "1111111", 55700, True),
]

HEADER = ["path_id", "train_no", "train_type", "block_section_id",
          "entry_time", "exit_time", "days_of_week", "priority_class",
          "divertible"]


def load(name, folder=REF):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fmt(minutes):
    minutes %= 1440
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def build():
    sections = load("block_sections.csv")
    # Index edges by the unordered station pair plus line, so a route pair
    # resolves to one edge regardless of which way the train runs it.
    edge = {}
    for s in sections:
        edge[(frozenset((s["from_station"], s["to_station"])), s["line_id"])] = s

    def run(route_name, direction, kind, train_no, ttype, prio, anchor, days, divertible):
        seq = ROUTES[route_name]
        if direction == "toward":
            seq = list(reversed(seq))
        line = line_for(kind, direction)
        speed_cap = TYPE_SPEED[ttype]
        dwell = DWELL.get(ttype, 0.0)
        clock = float(to_min(anchor))
        out = []
        for a, b in zip(seq, seq[1:]):
            sec = edge.get((frozenset((a, b)), line))
            if sec is None:
                # This route does not carry that line over that span (e.g. a
                # main-line service where only a suburban pair exists). Skip the
                # service rather than invent an edge.
                return []
            length = float(sec["end_km"]) - float(sec["start_km"])
            speed = min(speed_cap, int(sec["sectional_speed_kmph"]))
            run_min = length / speed * 60.0
            entry = clock
            exit_ = clock + run_min
            out.append({
                "path_id": "P-%s-%s-%s" % (train_no, sec["from_station"] + sec["to_station"], line),
                "train_no": train_no,
                "train_type": ttype,
                "block_section_id": sec["block_section_id"],
                "entry_time": fmt(int(round(entry))),
                "exit_time": fmt(int(round(exit_))),
                "days_of_week": days,
                "priority_class": prio,
                "divertible": str(divertible).lower(),
            })
            clock = exit_ + dwell
        return out

    rows = []
    for train_no, ttype, prio, route_name, direction, kind, anchor, days, divertible in NAMED:
        rows.extend(run(route_name, direction, kind, train_no, ttype, prio,
                        anchor, days, divertible))

    for (route_name, direction, kind, ttype, prio, headway, start, end,
         days, base, divertible) in PATTERNS:
        n = 0
        t = to_min(start)
        stop = to_min(end)
        while t <= stop:
            rows.extend(run(route_name, direction, kind, base + n, ttype, prio,
                            fmt(t), days, divertible))
            n += 1
            t += headway
    return rows


def main():
    random.Random(SEED)  # reserved; generation is deterministic
    rows = build()
    if not os.path.isdir(SUPPLY):
        os.makedirs(SUPPLY)
    out = os.path.join(SUPPLY, "train_paths.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    trains = len({r["train_no"] for r in rows})
    print("train_paths.csv: %d rows over %d trains" % (len(rows), trains))


if __name__ == "__main__":
    main()
