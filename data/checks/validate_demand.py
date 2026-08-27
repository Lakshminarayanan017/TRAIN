# -*- coding: utf-8 -*-
"""Checks over data/demand/tasks.csv (Data Spec Section 9).

Run after validate_reference.py:  python data/checks/validate_demand.py
Exit code 0 when clean, 1 when any check fails.

Section 9 is the central artefact - every model, every point of view and the
optimiser read from it - so almost every check here is a *cross-table* one. A task
row can be internally perfect and still be nonsense: an ENG task pointing at an
S&T asset, a node task carrying a line_id, a severity on the wrong scale for its
asset type. Those are the failures worth catching.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")
DEMAND = os.path.join(HERE, os.pardir, "demand")

DEPARTMENT = {"ENG", "TRD", "SNT"}
SOURCE_SYSTEM = {"ENG": "TMS", "SNT": "SMMS", "TRD": "TDMS"}
LOCATION_KIND = {"edge", "node"}
ACCESS = {"traffic_block", "power_block", "disconnection", "none"}
ORIGIN = {"defect", "overdue", "routine", "emergency_followup", "proactive"}
RAIL_FLAW_SEVERITY = {"IMDT", "1", "2", "3"}
GENERAL_SEVERITY = {"critical", "major", "minor"}
STATUS = {"pending", "scheduled", "in_progress", "done", "deferred", "cancelled"}
SAFETY_CRITICAL = {"IMDT", "1", "critical"}
BOOL = {"true", "false"}
OPEN_STATUS = {"pending", "scheduled", "in_progress"}

# Section 9 marks these "Derived by the system - never ingested". If any appears
# in the CSV, model output is being fed back in as input.
DERIVED = {"geo_key", "predicted_duration_p50", "predicted_duration_p80",
           "predicted_duration_p95", "escalation_hazard_daily", "availment_risk",
           "risk_score", "score_factors"}

# The Section 9.1 merge candidate, which the spec names as the first integration
# test. These ids must survive every regeneration.
SAMPLE_IDS = ["ENG-2026-04412", "TRD-2026-01188", "SNT-2026-00734"]

errors = []
notes = []


def fail(msg):
    errors.append(msg)


def note(msg):
    notes.append(msg)


def load(name, folder=REF):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


stations = {r["station_code"]: r for r in load("stations.csv")}
sections = {r["block_section_id"]: r for r in load("block_sections.csv")}
assets = {r["asset_id"]: r for r in load("assets.csv")}
task_types = {r["task_type_id"]: r for r in load("task_types.csv")}
tasks = load("tasks.csv", DEMAND)

# ---------------------------------------------------------------- derived fields
present = set(tasks[0].keys()) if tasks else set()
for column in sorted(DERIVED & present):
    fail("tasks.csv carries derived column %s; Section 9 marks it never-ingested"
         % column)

# ------------------------------------------------------------------- row checks
seen = set()
for r in tasks:
    tid = r["task_id"]
    if tid in seen:
        fail("duplicate task_id %s" % tid)
    seen.add(tid)

    dept = r["department"]
    if dept not in DEPARTMENT:
        fail("%s: bad department %r" % (tid, dept))
        continue
    # Traceability: three source systems collapse into one schema, and which one
    # a row came from must stay recoverable.
    if r["source_system"] != SOURCE_SYSTEM[dept]:
        fail("%s: %s work cannot come from %s" % (tid, dept, r["source_system"]))
    if not r["source_ref"]:
        fail("%s: source_ref is empty, breaking reconciliation" % tid)

    task_type = task_types.get(r["task_type_id"])
    if task_type is None:
        fail("%s: unknown task_type_id %s" % (tid, r["task_type_id"]))
        continue
    if task_type["department"] != dept:
        fail("%s: %s task raised under department %s"
             % (tid, task_type["department"], dept))

    # Fields the task must inherit unchanged from its type. A task may ask for
    # more time or more men than the catalogue's nominal, but it cannot invent a
    # different access mechanism or work at night when the type forbids it.
    for field in ("access_required", "machine_required", "location_kind"):
        if r[field] != task_type[field]:
            fail("%s: %s=%r but its task type says %r"
                 % (tid, field, r[field], task_type[field]))
    if r["night_permitted"] != task_type["night_permitted"]:
        fail("%s: night_permitted contradicts its task type" % tid)
    if r["season_restricted"] != task_type["monsoon_restricted"]:
        fail("%s: season_restricted contradicts its task type" % tid)

    # Location. Exactly one of the two, matching location_kind.
    on_edge, on_node = bool(r["block_section_id"]), bool(r["station_code"])
    if on_edge == on_node:
        fail("%s: must sit on exactly one of block_section_id / station_code" % tid)
    if r["location_kind"] == "edge" and not on_edge:
        fail("%s: edge task with no block_section_id" % tid)
    if r["location_kind"] == "node" and not on_node:
        fail("%s: node task with no station_code" % tid)
    if on_edge and r["block_section_id"] not in sections:
        fail("%s: unknown block_section_id %s" % (tid, r["block_section_id"]))
    if on_node and r["station_code"] not in stations:
        fail("%s: unknown station_code %s" % (tid, r["station_code"]))

    try:
        start_km, end_km = float(r["start_km"]), float(r["end_km"])
    except ValueError:
        fail("%s: start_km/end_km not numeric" % tid)
        continue
    if start_km > end_km:
        fail("%s: start_km %.2f is beyond end_km %.2f" % (tid, start_km, end_km))
    if on_edge and r["block_section_id"] in sections:
        section = sections[r["block_section_id"]]
        lo, hi = float(section["start_km"]), float(section["end_km"])
        if not (lo <= start_km <= hi and lo <= end_km <= hi):
            if tid in SAMPLE_IDS:
                # Data Spec 9.1 gives TRD-2026-01188 as km 40.00-44.00 on
                # TRL-AJJ-UP, while 8.2 starts that section at 42.0. The spec
                # contradicts itself. The record is kept verbatim because the
                # spec names these three as the first integration test; the
                # inconsistency is surfaced rather than clamped away.
                note("%s spans km %.2f-%.2f but %s starts at %s - a Data Spec "
                     "9.1 vs 8.2 contradiction, kept verbatim"
                     % (tid, start_km, end_km, r["block_section_id"],
                        section["start_km"]))
            else:
                fail("%s: km range %.2f-%.2f lies outside %s (%s-%s)"
                     % (tid, start_km, end_km, r["block_section_id"],
                        section["start_km"], section["end_km"]))
        # Section 9: line_id is present for edge work, and must be the line the
        # section actually is.
        if r["line_id"] != section["line_id"]:
            fail("%s: line_id=%r but %s is line %s"
                 % (tid, r["line_id"], r["block_section_id"], section["line_id"]))
    if r["location_kind"] == "node" and r["line_id"]:
        fail("%s: node work carries line_id=%r; Section 9 says null"
             % (tid, r["line_id"]))

    # The asset, when there is one. Section 9 allows a null asset_id for
    # span-based work with no single asset.
    if r["asset_id"]:
        asset = assets.get(r["asset_id"])
        if asset is None:
            fail("%s: unknown asset_id %s" % (tid, r["asset_id"]))
        else:
            shares = task_type["applies_to_asset_type"] == asset["asset_type"]
            if asset["department"] != dept and not shares:
                fail("%s: %s task raised against a %s asset it does not act on"
                     % (tid, dept, asset["department"]))
            if task_type["applies_to_asset_type"] and \
                    asset["asset_type"] != task_type["applies_to_asset_type"]:
                fail("%s: %s cannot be done on a %s"
                     % (tid, r["task_type_id"], asset["asset_type"]))
            if asset["block_section_id"] and \
                    asset["block_section_id"] != r["block_section_id"]:
                fail("%s: sited on %s but its asset is on %s"
                     % (tid, r["block_section_id"], asset["block_section_id"]))
            if asset["station_code"] and asset["station_code"] != r["station_code"]:
                fail("%s: sited at %s but its asset is at %s"
                     % (tid, r["station_code"], asset["station_code"]))
    elif task_type["applies_to_asset_type"]:
        fail("%s: %s acts on %s but no asset_id is given"
             % (tid, r["task_type_id"], task_type["applies_to_asset_type"]))

    if r["origin"] not in ORIGIN:
        fail("%s: bad origin %r" % (tid, r["origin"]))
    if r["status"] not in STATUS:
        fail("%s: bad status %r" % (tid, r["status"]))

    # Severity is on the rail-flaw scale only for rail assets (12.1 lists two
    # scales and the asset decides which applies).
    on_rail = bool(r["asset_id"]) and assets.get(r["asset_id"], {}).get("asset_type") == "rail"
    scale = RAIL_FLAW_SEVERITY if on_rail else GENERAL_SEVERITY
    if r["severity"] not in scale:
        fail("%s: severity %r is not on the %s scale"
             % (tid, r["severity"], "rail flaw" if on_rail else "general"))

    # safety_critical drives the hard deadline constraint, so the two must agree.
    if r["safety_critical"] not in BOOL:
        fail("%s: bad safety_critical %r" % (tid, r["safety_critical"]))
    else:
        critical = r["safety_critical"] == "true"
        if critical != (r["severity"] in SAFETY_CRITICAL):
            fail("%s: safety_critical=%s against severity %r"
                 % (tid, r["safety_critical"], r["severity"]))
        # Blueprint 7.3: a safety-critical task carries a hard deadline and is a
        # constraint, not a cost. Without a deadline there is nothing to enforce.
        if critical and not r["deadline"]:
            fail("%s: safety-critical with no deadline" % tid)

    for field in ("raised_date", "deadline"):
        if r[field]:
            try:
                dt.date(*map(int, r[field].split("-")))
            except (ValueError, TypeError):
                fail("%s: %s=%r is not an ISO date" % (tid, field, r[field]))
    if r["deadline"] and r["raised_date"] and r["deadline"] < r["raised_date"]:
        fail("%s: deadline falls before raised_date" % tid)

    if not r["days_pending"].lstrip("-").isdigit() or int(r["days_pending"]) < 0:
        fail("%s: days_pending must be a non-negative integer" % tid)
    if not r["requested_duration_min"].isdigit() or int(r["requested_duration_min"]) <= 0:
        fail("%s: requested_duration_min must be positive" % tid)
    # A task may ask for more men than the catalogue floor, never fewer.
    if not r["crew_required"].isdigit():
        fail("%s: crew_required not an integer" % tid)
    elif int(r["crew_required"]) < int(task_type["min_crew"]):
        fail("%s: crew_required %s is below the type's min_crew %s"
             % (tid, r["crew_required"], task_type["min_crew"]))
    if r["materials_ready"] not in BOOL:
        fail("%s: bad materials_ready %r" % (tid, r["materials_ready"]))

# --------------------------------------------------- Section 9.1 sample records
by_id = {r["task_id"]: r for r in tasks}
for tid in SAMPLE_IDS:
    if tid not in by_id:
        fail("Section 9.1 sample record %s is missing" % tid)
if all(tid in by_id for tid in SAMPLE_IDS):
    trio = [by_id[tid] for tid in SAMPLE_IDS]
    if {t["department"] for t in trio} != DEPARTMENT:
        fail("the 9.1 records no longer span all three departments")
    if not all(t["status"] == "pending" for t in trio):
        fail("the 9.1 records must all be pending to be a merge candidate")
    # All three sit at Tiruvallur - the whole point of the scenario.
    where = {t["block_section_id"] or ("@" + t["station_code"]) for t in trio}
    if where != {"TRL-AJJ-UP", "@TRL"}:
        fail("the 9.1 records are no longer co-located at Tiruvallur: %s"
             % sorted(where))

# ----------------------------------------------------------- pool shape (notes)
pending = [r for r in tasks if r["status"] == "pending"]
if not 200 <= len(pending) <= 420:
    note("%d tasks pending; 12.4 expects roughly 300 in any week" % len(pending))

pool = defaultdict(list)
for r in pending:
    pool[r["block_section_id"] or ("@" + r["station_code"])].append(r)
if pool:
    sizes = sorted((len(v) for v in pool.values()), reverse=True)
    median = sizes[len(sizes) // 2]
    if median < 3:
        note("median %d pending per location; Blueprint 6.2 assumes five to "
             "twenty, so merges will be rare" % median)
    multi = sum(1 for v in pool.values() if len({x["department"] for x in v}) >= 2)
    if multi < 10:
        note("only %d locations have two or more departments pending - the "
             "corpus offers little to merge" % multi)

# ---------------------------------------------------------------------- report
print("tasks               %5d rows  %s"
      % (len(tasks), dict(Counter(r["department"] for r in tasks))))
print("status                    %s" % dict(Counter(r["status"] for r in tasks)))
print("origin                    %s" % dict(Counter(r["origin"] for r in tasks)))
print("access                    %s"
      % dict(Counter(r["access_required"] for r in tasks)))
print("safety-critical           %d of %d"
      % (sum(1 for r in tasks if r["safety_critical"] == "true"), len(tasks)))
if pool:
    sizes = sorted((len(v) for v in pool.values()), reverse=True)
    print("pending pool              %d tasks over %d locations, max %d, median %d"
          % (len(pending), len(pool), sizes[0], sizes[len(sizes) // 2]))
    print("mergeable locations       %d with 2+ departments, %d with all 3"
          % (sum(1 for v in pool.values() if len({x["department"] for x in v}) >= 2),
             sum(1 for v in pool.values() if len({x["department"] for x in v}) == 3)))

if notes:
    print("\n%d NOTE(S)" % len(notes))
    for n in notes:
        print("  - %s" % n)

if errors:
    print("\n%d ERROR(S)" % len(errors))
    for e in errors[:40]:
        print("  - %s" % e)
    if len(errors) > 40:
        print("  ... and %d more" % (len(errors) - 40))
    sys.exit(1)
print("\nOK")
