# -*- coding: utf-8 -*-
"""Referential and domain checks over data/history/ (Data Spec 11).

Run:  python data/checks/validate_history.py
Exit 0 clean, 1 on any error. Covers block_executions (11.1), defect_lifecycle
(11.2), detention_log (11.3) and emergency_events (11.4).

Beyond schema, it guards the properties the models depend on: every task lands in
exactly one block (no double-counting), actuals exist iff the block was availed,
escalation is recorded iff a defect escalated, and every cross-reference resolves.
It also prints the two relationships the history exists to teach - the positive
overrun bias and the escalation confounding - so a regression in the generators is
visible, not silent.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
REF, DEMAND = os.path.join(ROOT, "reference"), os.path.join(ROOT, "demand")
SUPPLY, HISTORY = os.path.join(ROOT, "supply"), os.path.join(ROOT, "history")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DTM_RE = re.compile(r"^\d{4}-\d{2}-\d{2} ([01]\d|2[0-3]):[0-5]\d$")
BOOL = {"true", "false"}
WEATHER, SEASON = {"clear", "rain", "heavy_rain"}, {"normal", "monsoon"}
OVERRUN_REASON = {"material_delay", "crew_short", "machine_late", "weather",
                  "unexpected_condition", "traffic_hold", "none", ""}
TIME_BAND = {"00-06", "06-12", "12-18", "18-24"}
ESC_TYPE = {"speed_restriction", "failure", "punctuality_incident"}
EVENT_TYPE = {"rail_fracture", "OHE_failure", "point_failure", "cattle_run_over",
              "weather", "signal_failure", "other"}
RAIL_SEV, GEN_SEV = {"IMDT", "1", "2", "3"}, {"critical", "major", "minor"}

errors, notes = [], []


def fail(m):
    errors.append(m)


def load(name, folder):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


sections = {s["block_section_id"]: s for s in load("block_sections.csv", REF)}
tasks = {t["task_id"]: t for t in load("tasks.csv", DEMAND)}
assets = {a["asset_id"]: a for a in load("assets.csv", REF)}
crew_ids = {c["crew_id"] for c in load("crews.csv", REF)}
machine_ids = {m["machine_id"] for m in load("machines.csv", REF)}


def parse_dtm(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")

# ------------------------------------------------------- 11.1 block executions
blocks = load("block_executions.csv", HISTORY)
block_ids, task_seen = set(), {}
overruns, merged_ratio, single_ratio = [], [], []
for b in blocks:
    bid = b["block_id"]
    if bid in block_ids:
        fail("block_executions: duplicate block_id %s" % bid)
    block_ids.add(bid)
    if b["block_section_id"] not in sections:
        fail("%s: unknown block_section_id %s" % (bid, b["block_section_id"]))
    included = [t for t in b["tasks_included"].split(";") if t]
    if not included:
        fail("%s: no tasks_included" % bid)
    for tid in included:
        if tid not in tasks:
            fail("%s: tasks_included has unknown task %s" % (bid, tid))
        if tid in task_seen:
            fail("%s: task %s already in block %s - double-counted"
                 % (bid, tid, task_seen[tid]))
        task_seen[tid] = bid
    depts_here = {tasks[t]["department"] for t in included if t in tasks}
    if depts_here and set(b["departments"].split(";")) != depts_here:
        fail("%s: departments %s do not match included tasks %s"
             % (bid, b["departments"], sorted(depts_here)))
    is_merged = len(included) > 1
    if (b["was_merged"] == "true") != is_merged:
        fail("%s: was_merged=%s but %d tasks" % (bid, b["was_merged"], len(included)))
    if is_merged and not b["merge_group_id"]:
        fail("%s: merged block without a merge_group_id" % bid)
    if not is_merged and b["merge_group_id"]:
        fail("%s: singleton block carries a merge_group_id" % bid)
    for f in ("requested_start", "sanctioned_start"):
        if not DTM_RE.match(b[f]):
            fail("%s: %s=%r not a datetime" % (bid, f, b[f]))
    if b["availed"] not in BOOL:
        fail("%s: availed not boolean" % bid)
    availed = b["availed"] == "true"
    has_actual = bool(b["actual_start"]) and bool(b["actual_end"])
    if availed != has_actual:
        fail("%s: availed=%s but actual times %s"
             % (bid, b["availed"], "present" if has_actual else "absent"))
    if b["weather"] not in WEATHER:
        fail("%s: weather %r not in enumeration" % (bid, b["weather"]))
    if b["season"] not in SEASON:
        fail("%s: season %r not in enumeration" % (bid, b["season"]))
    if b["overrun_reason"] not in OVERRUN_REASON:
        fail("%s: overrun_reason %r not in enumeration" % (bid, b["overrun_reason"]))
    if b["crew_id"] and b["crew_id"] not in crew_ids:
        fail("%s: unknown crew_id %s" % (bid, b["crew_id"]))
    if b["machine_id"] and b["machine_id"] not in machine_ids:
        fail("%s: unknown machine_id %s" % (bid, b["machine_id"]))
    for f in ("requested_duration_min", "sanctioned_duration_min"):
        if not b[f].isdigit() or int(b[f]) <= 0:
            fail("%s: %s must be a positive integer" % (bid, f))
    if availed:
        if not DTM_RE.match(b["actual_start"]) or not DTM_RE.match(b["actual_end"]):
            fail("%s: actual times not datetimes" % bid)
        else:
            actual_dur = (parse_dtm(b["actual_end"]) - parse_dtm(b["actual_start"])).total_seconds() / 60
            if actual_dur <= 0:
                fail("%s: actual_end is not after actual_start" % bid)
            if b["overrun_min"]:
                if int(b["overrun_min"]) != int(round(actual_dur - int(b["sanctioned_duration_min"]))):
                    fail("%s: overrun_min inconsistent with actual - sanctioned" % bid)
                overruns.append(int(b["overrun_min"]))
            req = int(b["requested_duration_min"])
            (merged_ratio if is_merged else single_ratio).append(actual_dur / req)

# ------------------------------------------------------------ 11.3 detention log
detent = load("detention_log.csv", HISTORY)
seen_bid, band_resid = set(), defaultdict(list)
for r in detent:
    bid = r["block_id"]
    if bid in seen_bid:
        fail("detention_log: duplicate block_id %s" % bid)
    seen_bid.add(bid)
    if bid not in block_ids:
        fail("detention_log: unknown block_id %s" % bid)
    for f in ("analytical_estimate_min", "trains_affected", "total_detention_min",
              "rerouted_count", "cancelled_count"):
        if not r[f].isdigit():
            fail("%s: %s must be a non-negative integer" % (bid, f))
    if r["time_band"] not in TIME_BAND:
        fail("%s: time_band %r not in enumeration" % (bid, r["time_band"]))
    if r["trains_affected"].isdigit() and r["rerouted_count"].isdigit():
        if int(r["rerouted_count"]) > int(r["trains_affected"]):
            fail("%s: rerouted_count exceeds trains_affected" % bid)
    a, t = int(r["analytical_estimate_min"]), int(r["total_detention_min"])
    if a > 0:
        band_resid[r["time_band"]].append((t - a) / a)

# --------------------------------------------------------- 11.2 defect lifecycle
defects = load("defect_lifecycle.csv", HISTORY)
defect_ids = set()
esc_by_sev = defaultdict(lambda: [0, 0])
for d in defects:
    did = d["defect_id"]
    if did in defect_ids:
        fail("defect_lifecycle: duplicate defect_id %s" % did)
    defect_ids.add(did)
    if d["asset_id"] not in assets:
        fail("%s: unknown asset_id %s" % (did, d["asset_id"]))
    else:
        atype = assets[d["asset_id"]]["asset_type"]
        scale = RAIL_SEV if atype == "rail" else GEN_SEV
        if d["severity_at_raise"] not in scale:
            fail("%s: severity %r wrong for asset type %s"
                 % (did, d["severity_at_raise"], atype))
    if not DATE_RE.match(d["raised_date"]):
        fail("%s: raised_date not ISO" % did)
    if d["attended_date"]:
        if not DATE_RE.match(d["attended_date"]):
            fail("%s: attended_date not ISO" % did)
        elif d["attended_date"] < d["raised_date"]:
            fail("%s: attended before it was raised" % did)
    if not d["days_open"].isdigit():
        fail("%s: days_open must be a non-negative integer" % did)
    if d["temporary_repair_applied"] not in BOOL:
        fail("%s: temporary_repair_applied not boolean" % did)
    if d["escalated"] not in BOOL:
        fail("%s: escalated not boolean" % did)
    escalated = d["escalated"] == "true"
    if escalated and (not d["escalation_type"] or not d["escalation_date"]):
        fail("%s: escalated but escalation_type/date missing" % did)
    if not escalated and (d["escalation_type"] or d["escalation_date"]):
        fail("%s: not escalated but carries escalation detail" % did)
    if d["escalation_type"] and d["escalation_type"] not in ESC_TYPE:
        fail("%s: escalation_type %r not in enumeration" % (did, d["escalation_type"]))
    if escalated and DATE_RE.match(d["escalation_date"] or ""):
        if d["escalation_date"] < d["raised_date"]:
            fail("%s: escalated before raised" % did)
    esc_by_sev[d["severity_at_raise"]][0] += 1
    esc_by_sev[d["severity_at_raise"]][1] += escalated

# --------------------------------------------------------- 11.4 emergency events
events = load("emergency_events.csv", HISTORY)
event_ids = set()
for e in events:
    eid = e["event_id"]
    if eid in event_ids:
        fail("emergency_events: duplicate event_id %s" % eid)
    event_ids.add(eid)
    if e["event_type"] not in EVENT_TYPE:
        fail("%s: event_type %r not in enumeration" % (eid, e["event_type"]))
    sec = sections.get(e["block_section_id"])
    if sec is None:
        fail("%s: unknown block_section_id %s" % (eid, e["block_section_id"]))
    else:
        km = float(e["km"])
        if not (float(sec["start_km"]) - 0.05 <= km <= float(sec["end_km"]) + 0.05):
            fail("%s: km %.2f outside its section" % (eid, km))
    if not DTM_RE.match(e["occurred_at"]):
        fail("%s: occurred_at not a datetime" % eid)
    if not e["duration_min"].isdigit() or int(e["duration_min"]) <= 0:
        fail("%s: duration_min must be positive" % eid)
    for ref in filter(None, e["resources_consumed"].split(";")):
        if ref not in crew_ids and ref not in machine_ids:
            fail("%s: resource %s is neither a crew nor a machine" % (eid, ref))
    for ref in filter(None, e["blocks_invalidated"].split(";")):
        if ref not in block_ids:
            fail("%s: blocks_invalidated has unknown block %s" % (eid, ref))
    if e["followup_task_id"] and e["followup_task_id"] not in tasks:
        fail("%s: unknown followup_task_id %s" % (eid, e["followup_task_id"]))

# ---------------------------------------------------------------------- report
print("block_executions     %5d rows  %d merged  %d availed  %s"
      % (len(blocks), sum(1 for b in blocks if b["was_merged"] == "true"),
         sum(1 for b in blocks if b["availed"] == "true"),
         dict(Counter(b["season"] for b in blocks))))
if single_ratio and merged_ratio:
    print("  duration bias: actual/requested singleton %.2f, merged %.2f (merged slower)"
          % (sum(single_ratio) / len(single_ratio), sum(merged_ratio) / len(merged_ratio)))
if overruns:
    pos = sum(1 for x in overruns if x > 0)
    print("  overrun vs sanctioned: %.0f%% exceed (P80-consistent)" % (100.0 * pos / len(overruns)))
print("detention_log        %5d rows  residual by band %s"
      % (len(detent), {b: round(sum(v) / len(v), 2) for b, v in sorted(band_resid.items()) if v}))
print("defect_lifecycle     %5d defects  %d escalated"
      % (len(defects), sum(v[1] for v in esc_by_sev.values())))
print("  raw escalation by severity (the confounding): %s"
      % {s: "%.0f%%" % (100.0 * e / n) for s, (n, e) in
         sorted(esc_by_sev.items()) if n})
print("emergency_events     %5d events  %s"
      % (len(events), dict(Counter(e["event_type"] for e in events))))

if errors:
    print("\n%d ERROR(S)" % len(errors))
    for e in errors[:40]:
        print("  - %s" % e)
    sys.exit(1)
print("\nOK")
