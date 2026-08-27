# -*- coding: utf-8 -*-
"""Emit data/demand/tasks.csv (Data Spec Section 9).

The central artefact of the project. All five points of view, all four models and
the optimiser read from this one object; three source systems with three
vocabularies collapse into it.

Two rules govern what goes in this file:

1. **Derived fields are never ingested.** Section 9 marks geo_key,
   predicted_duration_p50/p80/p95, escalation_hazard_daily, availment_risk,
   risk_score and score_factors with a star and the words "Derived by the system -
   never ingested". They are therefore absent from this CSV. Emitting them would
   be emitting model output as if it were input, and every downstream metric
   computed against them would be circular.

2. **Arrival is traffic-weighted, not uniform.** Defects cluster where tonnage
   and train count are highest. Spreading tasks evenly over 23 spans would put
   about three on each, below the five-to-twenty per block section that Blueprint
   6.2 assumes and that makes merging possible at all. The weighting comes from
   the asset corpus, which already carries failure_count_12m correlated with
   section traffic.

The three Section 9.1 sample records are emitted verbatim - the spec calls them
"the merge candidate the optimiser must discover" and says to use them as the
first integration test.

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
DEMAND = os.path.join(HERE, os.pardir, "demand")

TODAY = dt.date(2026, 9, 7)
HORIZON_DAYS = 365
TARGET_TASKS = 4000

SOURCE_SYSTEM = {"ENG": "TMS", "SNT": "SMMS", "TRD": "TDMS"}

# Task ids the spec fixes in 9.1. Generated serials skip these so the sample
# records stay unique.
RESERVED_TASK_IDS = {"ENG-2026-04412", "TRD-2026-01188", "SNT-2026-00734"}

# Section 9 origin enumeration, with the share of the corpus each takes. Routine
# and overdue dominate because most maintenance is periodic; the split between
# them is the difference between work done on time and work that has slipped.
ORIGIN_MIX = [("routine", 0.38), ("overdue", 0.20), ("defect", 0.28),
              ("proactive", 0.09), ("emergency_followup", 0.05)]

# Status mix. About 300 tasks should be pending at any one time (12.4), which
# against a 4,000-row year is roughly 7.5 per cent.
STATUS_MIX = [("done", 0.74), ("pending", 0.076), ("scheduled", 0.055),
              ("deferred", 0.055), ("cancelled", 0.036), ("in_progress", 0.038)]

# Rail flaws carry the IMDT/1/2/3 scale; everything else uses critical/major/minor
# (12.1). Which scale applies is decided by the asset, not the department.
RAIL_FLAW_SCALE = [("IMDT", 0.04), ("1", 0.16), ("2", 0.35), ("3", 0.45)]
GENERAL_SCALE = [("critical", 0.10), ("major", 0.33), ("minor", 0.57)]

# Severities that make a task safety-critical, and therefore carry a hard
# deadline. Blueprint 7.3: these never participate in the deferral trade-off.
SAFETY_CRITICAL = {"IMDT", "1", "critical"}
DEADLINE_DAYS = {"IMDT": (1, 3), "1": (7, 21), "critical": (10, 30)}

HEADER = ["task_id", "source_system", "source_ref", "department", "task_type_id",
          "asset_id", "location_kind", "block_section_id", "station_code",
          "start_km", "end_km", "line_id", "origin", "raised_date", "days_pending",
          "severity", "deadline", "safety_critical", "access_required",
          "requested_duration_min", "crew_required", "machine_required",
          "materials_ready", "season_restricted", "night_permitted", "status"]

# The Section 9.1 sample records, verbatim. These three are the merge candidate
# the optimiser must discover: one ENG rail weld, one TRD OHE inspection and one
# SNT point service, all at Tiruvallur on 2026-09-07.
SAMPLE_RECORDS = [
    {"task_id": "ENG-2026-04412", "source_system": "TMS", "source_ref": "TMS-04412",
     "department": "ENG", "task_type_id": "ENG-RAIL-WELD", "asset_id": "RL-TRLAJJ-0421",
     "location_kind": "edge", "block_section_id": "TRL-AJJ-UP", "station_code": "",
     "start_km": "42.10", "end_km": "42.15", "line_id": "UP", "origin": "defect",
     "raised_date": "2026-09-03", "days_pending": "4", "severity": "1",
     "deadline": "2026-09-17", "safety_critical": "true",
     "access_required": "traffic_block", "requested_duration_min": "180",
     "crew_required": "6", "machine_required": "none", "materials_ready": "true",
     "season_restricted": "false", "night_permitted": "true", "status": "pending"},
    {"task_id": "TRD-2026-01188", "source_system": "TDMS", "source_ref": "TDMS-01188",
     "department": "TRD", "task_type_id": "TRD-OHE-INSP", "asset_id": "OHE-TRLAJJ-0402",
     "location_kind": "edge", "block_section_id": "TRL-AJJ-UP", "station_code": "",
     "start_km": "40.00", "end_km": "44.00", "line_id": "UP", "origin": "routine",
     "raised_date": "2026-08-28", "days_pending": "10", "severity": "minor",
     "deadline": "", "safety_critical": "false", "access_required": "power_block",
     "requested_duration_min": "90", "crew_required": "4",
     "machine_required": "OHE_tower_car", "materials_ready": "true",
     "season_restricted": "false", "night_permitted": "true", "status": "pending"},
    {"task_id": "SNT-2026-00734", "source_system": "SMMS", "source_ref": "SMMS-00734",
     "department": "SNT", "task_type_id": "SNT-POINT-SERVICE", "asset_id": "PT-TRL-04",
     "location_kind": "node", "block_section_id": "", "station_code": "TRL",
     "start_km": "42.10", "end_km": "42.10", "line_id": "", "origin": "overdue",
     "raised_date": "2026-08-27", "days_pending": "11", "severity": "major",
     "deadline": "2026-09-30", "safety_critical": "false",
     "access_required": "disconnection", "requested_duration_min": "60",
     "crew_required": "3", "machine_required": "none", "materials_ready": "true",
     "season_restricted": "false", "night_permitted": "true", "status": "pending"},
]


def load(name, folder=REF):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def pick(rng, weighted):
    roll = rng.random()
    cumulative = 0.0
    for value, share in weighted:
        cumulative += share
        if roll <= cumulative:
            return value
    return weighted[-1][0]


def build():
    rng = random.Random(SEED)
    assets = load("assets.csv")
    sections = {r["block_section_id"]: r for r in load("block_sections.csv")}
    task_types = load("task_types.csv")

    # Which task types can act on which asset type, split by department so a
    # task is always raised by the department that maintains the asset.
    acts_on = {}
    for r in task_types:
        if r["applies_to_asset_type"]:
            acts_on.setdefault(r["applies_to_asset_type"], []).append(r)
    # Span-based work has no asset; it is raised against a section directly.
    spanwise = [r for r in task_types if not r["applies_to_asset_type"]]

    # Selection weight per asset. Failure history and criticality already encode
    # the section's traffic and tonnage (see assets.README.md), so weighting on
    # them reproduces the real clustering of work onto busy track without any
    # geography being restated here.
    pool = []
    for a in assets:
        if a["asset_type"] not in acts_on:
            continue
        weight = 1.0
        weight += int(a["failure_count_12m"]) * 1.6
        weight += {"A": 1.2, "B": 0.5, "C": 0.0}[a["criticality_class"]]
        if a["cumulative_tonnage_gmt"]:
            weight += min(float(a["cumulative_tonnage_gmt"]) / 400.0, 2.0)
        pool.append((a, weight))
    total_weight = sum(w for _, w in pool)

    def draw_asset():
        target = rng.random() * total_weight
        running = 0.0
        for asset, weight in pool:
            running += weight
            if running >= target:
                return asset
        return pool[-1][0]

    rows = []
    counters = {"ENG": 4000, "TRD": 1000, "SNT": 500}

    attempts = 0
    while len(rows) < TARGET_TASKS - len(SAMPLE_RECORDS) and attempts < TARGET_TASKS * 20:
        attempts += 1
        # Roughly one task in twelve is span-based work with no single asset.
        if rng.random() < 0.08 and spanwise:
            task_type = rng.choice(spanwise)
            asset = None
        else:
            asset = draw_asset()
            candidates = acts_on[asset["asset_type"]]
            task_type = rng.choice(candidates)

        dept = task_type["department"]
        location_kind = task_type["location_kind"]

        # Place the task. An asset-backed task inherits its asset's location; a
        # span-based one is dropped on a section that suits its location kind.
        # A task keeps its asset whenever its type declares it acts on that
        # asset type, even if another department owns the asset outright. A
        # level crossing is the case that matters: ENG maintains the road
        # surface, S&T the gate interlocking, and CMP-028 already models the two
        # working it together.
        acts = (asset is not None
                and task_type["applies_to_asset_type"] == asset["asset_type"])
        if acts:
            block_section_id = asset["block_section_id"]
            station_code = asset["station_code"]
            anchor_km = float(asset["km"])
            asset_id = asset["asset_id"]
        else:
            asset_id = ""
            block_section_id = station_code = ""
            anchor_km = 0.0
        if not block_section_id and not station_code:
            # Span-based, or an asset maintained by another department: site it
            # on a section of the right kind.
            section = sections[rng.choice(list(sections))]
            if location_kind == "edge":
                block_section_id = section["block_section_id"]
                anchor_km = rng.uniform(float(section["start_km"]),
                                        float(section["end_km"]))
            else:
                continue  # node work needs a real node asset; skip this draw
        if location_kind == "node" and not station_code:
            continue
        if location_kind == "edge" and not block_section_id:
            continue

        if block_section_id:
            section = sections[block_section_id]
            line_id = section["line_id"]
            lo, hi = float(section["start_km"]), float(section["end_km"])
            worksite = float(task_type["worksite_length_km"] or 0.0)
            start_km = max(lo, min(anchor_km, hi))
            end_km = max(lo, min(start_km + worksite, hi))
        else:
            line_id = ""
            start_km = end_km = anchor_km
            section = None

        origin = pick(rng, ORIGIN_MIX)
        # A periodic task type cannot produce a defect; a defect-driven one
        # cannot be routine. Keep origin consistent with the catalogue.
        periodic = bool(task_type["default_periodicity_days"])
        if not periodic and origin in ("routine", "overdue"):
            origin = "defect"
        if periodic and origin == "defect":
            origin = "overdue"

        # Status first, then a raised_date consistent with it. Drawing the date
        # first and correcting the status afterwards emptied the pending pool:
        # most tasks landed months back and were reclassified as done, leaving
        # too few open at once for any block section to reach the five-to-twenty
        # that Blueprint 6.2 assumes.
        status = pick(rng, STATUS_MIX)
        if status in ("pending", "scheduled", "in_progress"):
            # Open work is recent, with a tail of items that have been waiting.
            age = int(abs(rng.gauss(0, 34))) + rng.randint(0, 6)
            age = min(age, 150)
        elif status == "deferred":
            age = rng.randint(30, HORIZON_DAYS)
        else:
            age = rng.randint(3, HORIZON_DAYS)
        raised = TODAY - dt.timedelta(days=age)
        scale = (RAIL_FLAW_SCALE
                 if asset is not None and asset["asset_type"] == "rail"
                 else GENERAL_SCALE)
        severity = pick(rng, scale)
        # Emergency follow-ups are permanent repairs after a failure and are
        # never trivial; proactive work never is urgent by definition.
        if origin == "emergency_followup" and severity in ("minor", "3"):
            severity = "major" if scale is GENERAL_SCALE else "2"
        if origin == "proactive" and severity in SAFETY_CRITICAL:
            severity = "major" if scale is GENERAL_SCALE else "2"

        safety_critical = severity in SAFETY_CRITICAL
        deadline = ""
        if safety_critical:
            lo_d, hi_d = DEADLINE_DAYS[severity]
            deadline = (raised + dt.timedelta(days=rng.randint(lo_d, hi_d))).isoformat()
        elif rng.random() < 0.25:
            deadline = (raised + dt.timedelta(days=rng.randint(30, 120))).isoformat()

        counters[dept] += 1
        while "%s-%d-%05d" % (dept, raised.year, counters[dept]) in RESERVED_TASK_IDS:
            counters[dept] += 1
        serial = counters[dept]
        nominal = int(task_type["nominal_duration_min"])
        min_crew = int(task_type["min_crew"])

        rows.append({
            "task_id": "%s-%d-%05d" % (dept, raised.year, serial),
            "source_system": SOURCE_SYSTEM[dept],
            "source_ref": "%s-%05d" % (SOURCE_SYSTEM[dept], serial),
            "department": dept,
            "task_type_id": task_type["task_type_id"],
            "asset_id": asset_id,
            "location_kind": location_kind,
            "block_section_id": block_section_id,
            "station_code": station_code,
            "start_km": "%.2f" % start_km,
            "end_km": "%.2f" % end_km,
            "line_id": line_id,
            "origin": origin,
            "raised_date": raised.isoformat(),
            # Section 9: recomputed daily. Open work counts to today; closed work
            # froze when it closed.
            "days_pending": (age if status in ("pending", "scheduled", "in_progress")
                             else min(age, rng.randint(1, max(2, age)))),
            "severity": severity,
            "deadline": deadline,
            "safety_critical": str(safety_critical).lower(),
            "access_required": task_type["access_required"],
            "requested_duration_min": int(nominal * rng.uniform(0.75, 1.45)),
            "crew_required": max(min_crew,
                                 int(min_crew * rng.uniform(1.0, 1.35))),
            "machine_required": task_type["machine_required"],
            # Feeds the availment risk model - a block is wasted when the
            # materials never turned up.
            "materials_ready": str(rng.random() > 0.14).lower(),
            "season_restricted": task_type["monsoon_restricted"],
            "night_permitted": task_type["night_permitted"],
            "status": status,
        })

    rows.extend(dict(r) for r in SAMPLE_RECORDS)
    return rows


def main():
    rows = build()
    if not os.path.isdir(DEMAND):
        os.makedirs(DEMAND)
    out = os.path.join(DEMAND, "tasks.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    pending = sum(1 for r in rows if r["status"] == "pending")
    print("tasks.csv: %d rows, %d pending" % (len(rows), pending))


if __name__ == "__main__":
    main()
