# -*- coding: utf-8 -*-
"""Emit data/reference/machines.csv and crews.csv (Data Spec 8.6).

These two are what turn Blueprint 7.6's "two hard constraints that prevent
impossible plans" from prose into arithmetic:

  - machine transit feasibility - if a tamper is four hours away and the block
    starts in two, that is impossibility, not risk
  - crew rest and duty hours - without them the optimiser will assign the same
    gang a Tuesday night block and a Wednesday morning block

Both files are catalogues, not populations: a division has the fleet and the
gangs it has. Their value is that they are *scarce* enough to bind.

Fixed seed per 12.5.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import random

SEED = 26027
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")

# Planning horizon the availability calendar covers. Brackets the 2026-09-07
# "today" the asset corpus is dated against.
HORIZON_START = dt.datetime(2026, 9, 1, 0, 0)
HORIZON_END = dt.datetime(2026, 9, 30, 23, 59)

# --------------------------------------------------------------------- machines
# machine_type -> (output_rate m/h, transit_time_h per adjacent section)
# Heavy P.Way plant moves slowly between sections; a test car runs at line speed.
MACHINE_CLASS = {
    "tamper":            (350.0, 1.5),
    "BCM":               (60.0,  2.5),
    "USFD_car":          (8000.0, 0.6),
    "OHE_tower_car":     (1200.0, 0.8),
    "ballast_regulator": (900.0, 1.2),
    "rail_grinder":      (500.0, 1.5),
}

# The fleet. Numbering is non-contiguous within a zone, as a real zonal fleet is,
# which is why TAMP-SR-07 exists - it is the Data Spec 8.6 example row, and it is
# based at AVD exactly as the spec has it.
FLEET = [
    ("TAMP-SR-03", "tamper", "AJJ"),
    ("TAMP-SR-05", "tamper", "TBM"),
    ("TAMP-SR-07", "tamper", "AVD"),
    ("BCM-SR-01", "BCM", "AJJ"),
    ("USFD-SR-01", "USFD_car", "MAS"),
    ("USFD-SR-04", "USFD_car", "TBM"),
    ("BRM-SR-02", "ballast_regulator", "AVD"),
    ("BRM-SR-06", "ballast_regulator", "TBM"),
    ("RGM-SR-01", "rail_grinder", "AJJ"),
    ("OHE-TC-01", "OHE_tower_car", "MAS"),
    ("OHE-TC-02", "OHE_tower_car", "PER"),
    ("OHE-TC-03", "OHE_tower_car", "AVD"),
    ("OHE-TC-04", "OHE_tower_car", "AJJ"),
    ("OHE-TC-05", "OHE_tower_car", "ENR"),
    ("OHE-TC-06", "OHE_tower_car", "MSB"),
    ("OHE-TC-07", "OHE_tower_car", "TBM"),
    ("OHE-TC-08", "OHE_tower_car", "CGL"),
]

MACHINE_HEADER = ["machine_id", "machine_type", "home_base", "current_section",
                  "available_from", "available_to", "output_rate", "transit_time_h"]

# ------------------------------------------------------------------------ crews
# Crew archetypes per department: (suffix, size range, qualifications).
# Between them the archetypes must cover every task type of that department, or
# work exists that nobody is qualified to do.
ARCHETYPES = {
    "ENG": [
        ("gang", (10, 20), ["ENG-RAIL-WELD", "ENG-LC-ATTENTION", "ENG-DRAIN-CLEAR",
                            "ENG-TRACK-PATROL", "ENG-YARD-PWAY", "ENG-SLEEPER-RENEWAL"]),
        ("mach", (6, 10),  ["ENG-TAMPING", "ENG-TURNOUT-TAMP", "ENG-BALLAST-REGULATE",
                            "ENG-BALLAST-SCREEN", "ENG-CURVE-REALIGN", "ENG-RAIL-GRIND"]),
        ("renl", (12, 20), ["ENG-RAIL-RENEWAL", "ENG-SLEEPER-RENEWAL",
                            "ENG-DESTRESSING", "ENG-TURNOUT-OVERHAUL"]),
        ("insp", (4, 6),   ["ENG-USFD-TEST", "ENG-BRIDGE-INSP", "ENG-BRIDGE-REPAIR"]),
    ],
    "TRD": [
        ("ohe",  (4, 6), ["TRD-OHE-INSP", "TRD-OHE-INSULATOR", "TRD-OHE-TENSION",
                          "TRD-OHE-DROPPER", "TRD-OHE-EARTHING", "TRD-OHE-FAULT",
                          "TRD-OHE-YARD"]),
        ("hvy",  (6, 8), ["TRD-OHE-WIRE-RENEW", "TRD-OHE-MAST", "TRD-NEUTRAL-SECTION"]),
        ("psi",  (3, 5), ["TRD-SUBSTN-MAINT", "TRD-SWITCHING-POST"]),
    ],
    "SNT": [
        ("mtce", (3, 5), ["SNT-POINT-SERVICE", "SNT-SIGNAL-LAMP", "SNT-TRACK-CIRCUIT",
                          "SNT-AXLE-COUNTER", "SNT-BLOCK-INSTRUMENT", "SNT-LC-GATE"]),
        ("wrks", (4, 6), ["SNT-POINT-REPLACE", "SNT-SIGNAL-REPLACE",
                          "SNT-INTERLOCK-TEST", "SNT-CABLE-LAY"]),
        ("tele", (3, 4), ["SNT-TELECOM", "SNT-RELAY-ROOM"]),
    ],
}

# How many crews of each archetype a department fields, and where. Bases are
# chosen so the busy corridors carry more gangs than the branch, which is what
# makes crew a binding constraint in the right places.
ENG_BASES = ["MAS", "PER", "ABU", "AVD", "TI", "TRL", "AJJ", "TNP", "ENR", "MJR",
             "GPD", "MSB", "MS", "MBM", "GI", "STM", "PV", "TBM", "CGL", "CJ"]
TRD_BASES = ["MAS", "AVD", "AJJ", "ENR", "GPD", "MSB", "GI", "TBM", "CGL"]
SNT_BASES = ["MAS", "PER", "AVD", "TRL", "AJJ", "TNP", "ENR", "GPD", "MSB", "MS",
             "GI", "STM", "TBM", "CGL", "CJ"]

# Duty rules. Hard constraints in Blueprint 7.6, so they are data, not code.
SHIFT_PATTERNS = ["rotating_3", "rotating_2", "day_only"]

CREW_HEADER = ["crew_id", "department", "base_section", "size", "shift_pattern",
               "qualifications", "min_rest_hours", "max_consecutive_nights",
               "max_weekly_duty_hours", "division_id"]


def load(name):
    with open(os.path.join(REF, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def sections_at(sections, code):
    """Block sections touching a station, busiest first."""
    touching = [r for r in sections
                if code in (r["from_station"], r["to_station"])]
    return sorted(touching, key=lambda r: -int(r["daily_train_count"]))


def build_machines(rng, sections):
    """One row per machine per availability window.

    Data Spec 8.6 calls available_from / available_to an *availability calendar*,
    and 12.4 sizes the machine master at ~50 rows against a division fleet that is
    realistically under twenty. Both fit if the row is (machine, window) rather
    than (machine): 17 machines with two to four windows each. The key is
    (machine_id, available_from).

    Gaps between a machine's windows are its own maintenance and commitments
    elsewhere - they are what make the transit constraint bite.
    """
    rows = []
    for machine_id, machine_type, home in FLEET:
        output_rate, transit = MACHINE_CLASS[machine_type]
        near = sections_at(sections, home)
        # Where the machine currently stands. Usually at or near its home base.
        current = near[0]["block_section_id"] if near else ""
        cursor = HORIZON_START + dt.timedelta(hours=rng.randint(0, 18))
        windows = rng.randint(2, 4)
        for _ in range(windows):
            if cursor >= HORIZON_END:
                break
            span_days = rng.randint(3, 9)
            end = min(cursor + dt.timedelta(days=span_days,
                                            hours=rng.randint(0, 12)), HORIZON_END)
            rows.append({
                "machine_id": machine_id,
                "machine_type": machine_type,
                "home_base": home,
                "current_section": current,
                "available_from": cursor.strftime("%Y-%m-%d %H:%M"),
                "available_to": end.strftime("%Y-%m-%d %H:%M"),
                "output_rate": "%.1f" % output_rate,
                "transit_time_h": "%.1f" % transit,
            })
            # Out of service between windows.
            cursor = end + dt.timedelta(days=rng.randint(1, 4),
                                        hours=rng.randint(0, 20))
    return rows


def build_crews(rng, sections):
    """~120 crews. Every task type must be covered by at least one crew.

    Crew counts are set per archetype rather than by cycling through a rotation.
    An earlier revision rotated archetypes by base index, which never advanced far
    enough to create the renewal, inspection, substation and telecom crews - so ten
    task types had nobody qualified to do them. Explicit counts make the coverage
    guarantee checkable, and validate_reference.py now fails the build if any task
    type is left unqualified.
    """
    # Archetype -> crew count. Weighted to the everyday work: general P.Way gangs
    # and S&T maintainers outnumber the specialist renewal and works crews, which
    # is what makes those specialists the binding constraint rather than headcount.
    ESTABLISHMENT = {
        "ENG": [("gang", 26), ("mach", 12), ("renl", 10), ("insp", 8)],
        "TRD": [("ohe", 14), ("hvy", 8), ("psi", 4)],
        "SNT": [("mtce", 18), ("wrks", 12), ("tele", 8)],
    }
    BASES = {"ENG": ENG_BASES, "TRD": TRD_BASES, "SNT": SNT_BASES}

    rows = []
    for dept in ("ENG", "TRD", "SNT"):
        archetypes = {name: (size, quals) for name, size, quals in ARCHETYPES[dept]}
        bases = BASES[dept]
        used = {}
        cursor = 0
        for kind, count in ESTABLISHMENT[dept]:
            size_range, quals = archetypes[kind]
            for _ in range(count):
                base = bases[cursor % len(bases)]
                cursor += 1
                near = sections_at(sections, base)
                base_section = near[0]["block_section_id"] if near else ""
                seq = used.get(base, 0)
                used[base] = seq + 1
                crew_id = "%s-%s-%s" % (dept, base, "ABCDEFGH"[seq])
                # Substation and telecom work is indoors and daytime; everything
                # that touches the track rotates, because blocks happen at night.
                if kind in ("psi", "tele"):
                    pattern = "day_only"
                else:
                    pattern = rng.choice(SHIFT_PATTERNS[:2])
                rows.append({
                    "crew_id": crew_id,
                    "department": dept,
                    "base_section": base_section,
                    "size": rng.randint(*size_range),
                    "shift_pattern": pattern,
                    "qualifications": ";".join(quals),
                    # Hard limits - Blueprint 7.6. A plan that breaches these is
                    # infeasible, not merely undesirable.
                    "min_rest_hours": 12,
                    "max_consecutive_nights": (3 if pattern == "rotating_3"
                                               else (0 if pattern == "day_only" else 2)),
                    "max_weekly_duty_hours": rng.choice([48, 48, 52, 54]),
                    "division_id": "SR-MAS",
                })
    return rows


def main():
    rng = random.Random(SEED)
    sections = load("block_sections.csv")

    machines = build_machines(rng, sections)
    with open(os.path.join(REF, "machines.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MACHINE_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(machines)
    print("machines.csv: %d rows over %d machines"
          % (len(machines), len({r["machine_id"] for r in machines})))

    crews = build_crews(rng, sections)
    with open(os.path.join(REF, "crews.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CREW_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(crews)
    print("crews.csv: %d rows, %d total men"
          % (len(crews), sum(int(r["size"]) for r in crews)))


if __name__ == "__main__":
    main()
