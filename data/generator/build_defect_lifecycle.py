# -*- coding: utf-8 -*-
"""Emit data/history/defect_lifecycle.csv (Data Spec 11.2).

The escalation-risk training set. One row per defect; at training time each is
expanded into one row per day it stayed open, for discrete-time survival modelling
(Blueprint 8.2). escalated is the label.

The whole difficulty of this model is a confounding trap the spec names
explicitly (Blueprint 8.2): dangerous-looking defects are fixed fastest, so in the
raw data a severity-1 defect rarely escalates - not because it is safe, but
because it was rescued before it could. A model trained naively learns severity 1
is safe, exactly backwards. This generator builds that trap in deliberately:

  - the *daily hazard* genuinely rises with severity and with asset condition
    (tonnage, age, failures) - the true relationship;
  - but severe defects get a much shorter days_open (attended fast), so their
    *cumulative* escalation stays low despite the high daily hazard.

So a model that asks "does this severity escalate?" is misled, and only one that
asks "given it is still open on day k, what is today's hazard?" recovers the
truth. attended_date is recorded but must never be a feature - it is leakage.

Grounded: defects are raised against the real assets in assets.csv, weighted by
the failure history, criticality and tonnage those assets already carry, so
defects cluster on the track that genuinely wears fastest.

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
HISTORY = os.path.join(HERE, os.pardir, "history")

TODAY = dt.date(2026, 9, 7)
HORIZON_DAYS = 540            # ~18 months of defect history
TARGET_DEFECTS = 3500

DEFECT_TYPES = {
    "rail": ["rail_flaw", "weld_failure", "wear", "corrugation"],
    "sleeper": ["cracked_sleeper", "fastening_failure"],
    "ballast": ["ballast_deficiency", "drainage_choke", "fouling"],
    "turnout": ["switch_wear", "crossing_wear", "gauge_defect"],
    "bridge": ["bearing_defect", "expansion_joint", "corrosion"],
    "level_crossing": ["surface_defect", "check_rail_wear"],
    "OHE_span": ["height_stagger", "hard_spot"],
    "contact_wire": ["wire_wear", "burn_mark"],
    "mast": ["foundation_defect", "corrosion"],
    "insulator": ["cracked_insulator", "flashover_mark"],
    "substation": ["equipment_fault", "transformer_alarm"],
    "signal": ["lamp_failure", "aspect_defect"],
    "point_machine": ["detection_failure", "obstruction", "motor_fault"],
    "track_circuit": ["shunt_failure", "bonding_defect"],
    "axle_counter": ["reset_failure", "head_fault"],
    "interlocking": ["relay_fault", "wire_count_discrepancy"],
}

RAIL_FLAW = [("IMDT", 0.04), ("1", 0.16), ("2", 0.35), ("3", 0.45)]
GENERAL = [("critical", 0.09), ("major", 0.33), ("minor", 0.58)]

# True inherent daily hazard by severity - severe really is more dangerous.
BASE_HAZARD = {"IMDT": 0.032, "1": 0.016, "2": 0.008, "3": 0.004,
               "critical": 0.018, "major": 0.008, "minor": 0.0035}
# Attention latency by severity: severe is attended fast. This is the confounder.
ATTEND_DAYS = {"IMDT": (0, 2), "1": (1, 7), "2": (5, 25), "3": (12, 75),
               "critical": (1, 7), "major": (5, 22), "minor": (10, 70)}

ESC_TYPE_BY_DEPT = {
    "ENG": [("speed_restriction", 0.70), ("failure", 0.18), ("punctuality_incident", 0.12)],
    "TRD": [("failure", 0.55), ("punctuality_incident", 0.30), ("speed_restriction", 0.15)],
    "SNT": [("failure", 0.45), ("punctuality_incident", 0.45), ("speed_restriction", 0.10)],
}

HEADER = ["defect_id", "asset_id", "defect_type", "severity_at_raise",
          "raised_date", "attended_date", "days_open", "temporary_repair_applied",
          "escalated", "escalation_type", "escalation_date"]


def load(name):
    with open(os.path.join(REF, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def pick(rng, weighted):
    roll, acc = rng.random(), 0.0
    for v, w in weighted:
        acc += w
        if roll <= acc:
            return v
    return weighted[-1][0]


def build():
    rng = random.Random(SEED)
    assets = load("assets.csv")

    # Weight assets so defects cluster where wear genuinely concentrates.
    pool = []
    for a in assets:
        if a["asset_type"] not in DEFECT_TYPES:
            continue
        w = 1.0 + int(a["failure_count_12m"]) * 1.6
        w += {"A": 1.2, "B": 0.5, "C": 0.0}[a["criticality_class"]]
        if a["cumulative_tonnage_gmt"]:
            w += min(float(a["cumulative_tonnage_gmt"]) / 400.0, 2.0)
        pool.append((a, w))
    total_w = sum(w for _, w in pool)

    def draw_asset():
        target, run = rng.random() * total_w, 0.0
        for a, w in pool:
            run += w
            if run >= target:
                return a
        return pool[-1][0]

    def condition_factor(a):
        f = 1.0
        f += int(a["failure_count_12m"]) * 0.30
        if a["cumulative_tonnage_gmt"]:
            f += float(a["cumulative_tonnage_gmt"]) / 900.0
        if a["install_date"]:
            age = (TODAY - dt.date(*map(int, a["install_date"].split("-")))).days / 365.25
            f += age * 0.010
        return f

    rows = []
    for i in range(TARGET_DEFECTS):
        a = draw_asset()
        atype = a["asset_type"]
        dtype = rng.choice(DEFECT_TYPES[atype])
        scale = RAIL_FLAW if atype == "rail" else GENERAL
        sev = pick(rng, scale)

        raised = TODAY - dt.timedelta(days=rng.randint(1, HORIZON_DAYS))
        lo, hi = ATTEND_DAYS[sev]
        planned_attend = rng.randint(lo, hi)
        temp_repair = rng.random() < 0.25

        hazard = BASE_HAZARD[sev] * condition_factor(a) * (0.4 if temp_repair else 1.0)

        # Simulate day by day up to attention. Escalation, if it happens, happens
        # while the defect is still open - severe defects rarely get the chance.
        escalated = False
        escalation_day = None
        open_days = (TODAY - raised).days
        limit = min(planned_attend, open_days)
        for day in range(1, max(1, limit) + 1):
            if rng.random() < hazard:
                escalated = True
                escalation_day = day
                break

        still_open = planned_attend >= open_days   # not yet attended as of TODAY
        if still_open:
            attended = ""
            days_open = open_days
        else:
            attended_date = raised + dt.timedelta(days=planned_attend)
            attended = attended_date.isoformat()
            days_open = planned_attend

        esc_type = esc_date = ""
        if escalated:
            esc_type = pick(rng, ESC_TYPE_BY_DEPT[a["department"]])
            esc_date = (raised + dt.timedelta(days=escalation_day)).isoformat()

        rows.append({
            "defect_id": "DFT-%d-%05d" % (raised.year, i + 1),
            "asset_id": a["asset_id"],
            "defect_type": dtype,
            "severity_at_raise": sev,
            "raised_date": raised.isoformat(),
            "attended_date": attended,
            "days_open": days_open,
            "temporary_repair_applied": str(temp_repair).lower(),
            "escalated": str(escalated).lower(),
            "escalation_type": esc_type,
            "escalation_date": esc_date,
        })
    return rows


def main():
    rows = build()
    if not os.path.isdir(HISTORY):
        os.makedirs(HISTORY)
    out = os.path.join(HISTORY, "defect_lifecycle.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    esc = sum(1 for r in rows if r["escalated"] == "true")
    opn = sum(1 for r in rows if not r["attended_date"])
    print("defect_lifecycle.csv: %d defects, %d escalated (%.0f%%), %d still open"
          % (len(rows), esc, 100.0 * esc / len(rows), opn))


if __name__ == "__main__":
    main()
