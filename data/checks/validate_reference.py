# -*- coding: utf-8 -*-
"""Referential and domain checks over data/reference/.

Run from anywhere:  python data/checks/validate_reference.py
Exit code 0 when clean, 1 when any check fails.

Covers the reference tables that exist so far (Data Spec 8.1, 8.2, 8.4, 8.5).
Extend as 8.3 and 8.6 land. The last block re-runs the Data Spec 9.1 merge
candidate through the compatibility matrix, which the spec names as the
project's first integration test.

Findings are split into errors, which fail the build, and notes, which record
places where the modelled pilot deliberately departs from the real network and
should stay visible rather than be silently suppressed.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import sys
from collections import Counter, defaultdict

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "reference")

# Data Spec 12.1 enumerations.
DEPARTMENT = {"ENG", "TRD", "SNT"}
LOCATION_KIND = {"edge", "node"}
ACCESS = {"traffic_block", "power_block", "disconnection", "none"}
LINE_ID = {"UP", "DN", "UP_SUB", "DN_SUB", "THIRD", "FOURTH", "SINGLE"}
TRAFFIC_TYPE = {"suburban", "trunk", "freight", "mixed", "branch"}
MACHINE = {"none", "tamper", "BCM", "USFD_car", "OHE_tower_car",
           "ballast_regulator", "rail_grinder"}
RELATION = {"parallel", "sequential", "incompatible"}
ASSET_TYPE = {"rail", "sleeper", "ballast", "turnout", "bridge", "level_crossing",
              "OHE_span", "mast", "insulator", "contact_wire", "substation", "signal",
              "point_machine", "track_circuit", "axle_counter", "interlocking"}
BOOL = {"true", "false"}

# Blueprint 5.4 names four modelled corridors; each measures chainage from one
# origin, which is why km_from_origin alone is not self-describing.
# Verified against the published Chennai Suburban line articles: the North Line
# route map is chainaged from Chennai Central MMC, not from Beach.
CORRIDOR_ORIGIN = {"MAS-AJJ": "MAS", "BBQ-GPD": "MAS",
                   "MSB-TBM": "MSB", "AJJ-CGL": "MSB"}
DIVISION = "SR-MAS"

# A block section longer than this is worth a second look: it means a crossing
# station was treated as a halt. 30 km clears the spec-anchored TRL-AJJ span.
LONG_SPAN_KM = 30.0

errors = []
notes = []


def fail(msg):
    errors.append(msg)


def note(msg):
    notes.append(msg)


def load(name):
    with open(os.path.join(REF, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def check_enum(row_id, row, field, allowed):
    if row[field] not in allowed:
        fail("%s: %s=%r not in enumeration" % (row_id, field, row[field]))


# ---------------------------------------------------------------- 8.1 stations
stations = load("stations.csv")
by_code = {}
for r in stations:
    code = r["station_code"]
    if code in by_code:
        fail("stations: duplicate station_code %s" % code)
    by_code[code] = r
    for f in ("is_block_station", "has_yard", "is_junction"):
        check_enum(code, r, f, BOOL)
    check_enum(code, r, "corridor_id", set(CORRIDOR_ORIGIN))
    if r["division_id"] != DIVISION:
        fail("%s: division_id=%r, expected %s" % (code, r["division_id"], DIVISION))
    try:
        float(r["km_from_origin"])
    except ValueError:
        fail("%s: km_from_origin not numeric" % code)
    # km_origin_ref must agree with the corridor it belongs to, or the chainage
    # convention has drifted between the two columns.
    if r["corridor_id"] in CORRIDOR_ORIGIN:
        want = CORRIDOR_ORIGIN[r["corridor_id"]]
        if r["km_origin_ref"] != want:
            fail("%s: km_origin_ref=%s but corridor %s measures from %s"
                 % (code, r["km_origin_ref"], r["corridor_id"], want))
    if r["km_origin_ref"] not in by_code and r["km_origin_ref"] not in ("MAS", "MSB"):
        fail("%s: km_origin_ref=%r is not a station code" % (code, r["km_origin_ref"]))
    if r["route_capacity"] and not r["route_capacity"].isdigit():
        fail("%s: route_capacity not an integer" % code)
    # A block station must be able to hold a train clear of the running line.
    if r["is_block_station"] == "true" and int(r["route_capacity"] or 0) < 2:
        fail("%s: block station with route_capacity < 2 cannot hold a crossing" % code)

# The origin of each corridor must actually sit at km 0 on that corridor.
for corridor, origin in CORRIDOR_ORIGIN.items():
    home = [r for r in stations if r["corridor_id"] == corridor]
    if home and origin in by_code and by_code[origin]["corridor_id"] == corridor:
        if float(by_code[origin]["km_from_origin"]) != 0.0:
            fail("%s: corridor origin %s is not at km 0" % (corridor, origin))

# --------------------------------------------------------- 8.2 block sections
sections = load("block_sections.csv")
sec_ids = set()
for r in sections:
    bsid = r["block_section_id"]
    if bsid in sec_ids:
        fail("block_sections: duplicate block_section_id %s" % bsid)
    sec_ids.add(bsid)

for r in sections:
    bsid = r["block_section_id"]
    if bsid != "%s-%s-%s" % (r["from_station"], r["to_station"], r["line_id"]):
        fail("%s: id does not match from/to/line" % bsid)
    for f in ("from_station", "to_station"):
        code = r[f]
        if code not in by_code:
            fail("%s: %s references unknown station %s" % (bsid, f, code))
        elif by_code[code]["is_block_station"] != "true":
            fail("%s: %s=%s is not a block station" % (bsid, f, code))
    if float(r["start_km"]) >= float(r["end_km"]):
        fail("%s: km does not increase from_station -> to_station" % bsid)
    check_enum(bsid, r, "line_id", LINE_ID)
    check_enum(bsid, r, "traffic_type", TRAFFIC_TYPE)
    check_enum(bsid, r, "corridor_id", set(CORRIDOR_ORIGIN))
    for f in ("electrified", "bidirectional_capable", "monsoon_sensitive"):
        check_enum(bsid, r, f, BOOL)
    if r["division_id"] != DIVISION:
        fail("%s: division_id=%r, expected %s" % (bsid, r["division_id"], DIVISION))
    for f in ("parallel_edges", "next_sections"):
        for ref in filter(None, r[f].split(";")):
            if ref not in sec_ids:
                fail("%s: %s has dangling ref %s" % (bsid, f, ref))
            if f == "parallel_edges" and ref == bsid:
                fail("%s: lists itself in parallel_edges" % bsid)

# parallel_edges is an equivalence relation over a span, so it must be symmetric.
by_id = {r["block_section_id"]: r for r in sections}
for r in sections:
    bsid = r["block_section_id"]
    for ref in filter(None, r["parallel_edges"].split(";")):
        if ref in by_id and bsid not in by_id[ref]["parallel_edges"].split(";"):
            fail("%s: parallel_edges not symmetric with %s" % (bsid, ref))
    if r["line_id"] == "SINGLE" and r["parallel_edges"]:
        fail("%s: a SINGLE line cannot have parallel edges" % bsid)

# Every edge of a span must agree on geography, and the span must belong to a
# corridor at least one of its endpoints calls home. A junction endpoint may sit
# on a different corridor - that is what makes it a junction.
spans = defaultdict(list)
for r in sections:
    spans[(r["from_station"], r["to_station"])].append(r)
for (frm, to), edges in spans.items():
    for field in ("start_km", "end_km", "corridor_id", "electrified", "monsoon_sensitive"):
        values = {e[field] for e in edges}
        if len(values) > 1:
            fail("%s-%s: edges disagree on %s: %s" % (frm, to, field, sorted(values)))
    corridor = edges[0]["corridor_id"]
    homes = {by_code[c]["corridor_id"] for c in (frm, to) if c in by_code}
    if corridor not in homes:
        fail("%s-%s: corridor %s matches neither endpoint's home corridor %s"
             % (frm, to, corridor, sorted(homes)))

# Endpoint chainage must agree with the station master, but only where the
# station is on its home corridor. A junction shared between corridors carries
# its primary-corridor chainage on the node and its own on the off-corridor
# edge - AJJ is 69.0 on the trunk and 122.7 on corridor 4. This replaces the
# hardcoded exception the earlier revision of this script carried.
for r in sections:
    bsid = r["block_section_id"]
    for field, endpoint in (("start_km", "from_station"), ("end_km", "to_station")):
        station = by_code.get(r[endpoint])
        if station is None:
            continue
        if station["corridor_id"] != r["corridor_id"]:
            continue  # off-corridor endpoint; the edge carries the true chainage
        want = float(station["km_from_origin"])
        if abs(want - float(r[field])) > 0.6:
            fail("%s: %s=%s but station %s is at km %s on its home corridor"
                 % (bsid, field, r[field], r[endpoint], want))

# No block station may sit strictly inside a span on its own corridor. This is
# the check that catches a crossing station wrongly recorded as a halt.
for (frm, to), edges in spans.items():
    e = edges[0]
    corridor, lo, hi = e["corridor_id"], float(e["start_km"]), float(e["end_km"])
    for s in stations:
        code = s["station_code"]
        if code in (frm, to) or s["corridor_id"] != corridor:
            continue
        if s["is_block_station"] == "true" and lo < float(s["km_from_origin"]) < hi:
            fail("%s-%s: block station %s at km %s lies inside the span"
                 % (frm, to, code, s["km_from_origin"]))
    if hi - lo > LONG_SPAN_KM:
        note("%s-%s spans %.1f km with no intermediate block station"
             % (frm, to, hi - lo))

# Each corridor's spans must chain end to end, with no gap and no overlap.
for corridor in CORRIDOR_ORIGIN:
    runs = sorted({(float(e[0]["start_km"]), float(e[0]["end_km"]), k[0], k[1])
                   for k, e in spans.items() if e[0]["corridor_id"] == corridor})
    for (a_lo, a_hi, _, a_to), (b_lo, b_hi, b_frm, _) in zip(runs, runs[1:]):
        if a_to != b_frm:
            fail("%s: %s ends at %s but the next span starts at %s"
                 % (corridor, a_to, a_hi, b_frm))
        elif abs(a_hi - b_lo) > 0.6:
            fail("%s: gap or overlap at %s between km %s and %s"
                 % (corridor, a_to, a_hi, b_lo))

# Blueprint 2.4 defines a junction as a node of degree greater than two. Where a
# station is flagged is_junction but the modelled graph gives it a lower degree,
# the arms that make it a junction lie outside the pilot's four corridors. That
# is expected at the pilot boundary and is reported, not failed.
degree = defaultdict(set)
for r in sections:
    span = (r["from_station"], r["to_station"])
    degree[r["from_station"]].add(span)
    degree[r["to_station"]].add(span)
for s in stations:
    code = s["station_code"]
    d = len(degree[code])
    if s["is_junction"] == "true" and d <= 2:
        note("%s is_junction=true but modelled degree %d - its other arms lie "
             "outside the pilot corridors" % (code, d))
    if s["is_junction"] == "false" and d > 2:
        fail("%s has modelled degree %d but is_junction=false" % (code, d))

# ------------------------------------------------------------------ 8.3 assets
assets = load("assets.csv")
asset_ids = set()
CRITICALITY = {"A", "B", "C"}
for r in assets:
    aid = r["asset_id"]
    if aid in asset_ids:
        fail("assets: duplicate asset_id %s" % aid)
    asset_ids.add(aid)
    check_enum(aid, r, "asset_type", ASSET_TYPE)
    check_enum(aid, r, "department", DEPARTMENT)
    check_enum(aid, r, "criticality_class", CRITICALITY)
    # 8.3: block_section_id is null for node-located assets, station_code is null
    # for edge-located ones. Exactly one must be present, or the asset has no
    # place in the graph and no task can be raised against it.
    on_edge, on_node = bool(r["block_section_id"]), bool(r["station_code"])
    if on_edge == on_node:
        fail("%s: must sit on exactly one of block_section_id / station_code" % aid)
    if on_edge and r["block_section_id"] not in sec_ids:
        fail("%s: unknown block_section_id %s" % (aid, r["block_section_id"]))
    if on_node and r["station_code"] not in by_code:
        fail("%s: unknown station_code %s" % (aid, r["station_code"]))
    try:
        km = float(r["km"])
    except ValueError:
        fail("%s: km not numeric" % aid)
        continue
    # An edge asset must lie inside the section it claims; a node asset must sit
    # at its station's post.
    if on_edge and r["block_section_id"] in by_id:
        sec = by_id[r["block_section_id"]]
        if not (float(sec["start_km"]) <= km <= float(sec["end_km"])):
            fail("%s: km %.2f lies outside %s (%s-%s)"
                 % (aid, km, r["block_section_id"], sec["start_km"], sec["end_km"]))
    if on_node and r["station_code"] in by_code:
        if abs(km - float(by_code[r["station_code"]]["km_from_origin"])) > 1.0:
            fail("%s: km %.2f is not at station %s" % (aid, km, r["station_code"]))
    for f in ("install_date", "last_overhaul_date"):
        if r[f]:
            try:
                dt.date(*map(int, r[f].split("-")))
            except (ValueError, TypeError):
                fail("%s: %s=%r is not an ISO date" % (aid, f, r[f]))
    if r["install_date"] and r["last_overhaul_date"]:
        if r["last_overhaul_date"] < r["install_date"]:
            fail("%s: overhauled before it was installed" % aid)
    if r["cumulative_tonnage_gmt"]:
        try:
            if float(r["cumulative_tonnage_gmt"]) < 0:
                fail("%s: negative cumulative_tonnage_gmt" % aid)
        except ValueError:
            fail("%s: cumulative_tonnage_gmt not numeric" % aid)
    if not r["failure_count_12m"].isdigit():
        fail("%s: failure_count_12m must be a non-negative integer" % aid)

# ------------------------------------------------------------- 8.4 task types
task_types = load("task_types.csv")
tt = {}
for r in task_types:
    tid = r["task_type_id"]
    if tid in tt:
        fail("task_types: duplicate task_type_id %s" % tid)
    tt[tid] = r
    if not tid.startswith(r["department"] + "-"):
        fail("%s: id prefix does not match department %s" % (tid, r["department"]))
    check_enum(tid, r, "department", DEPARTMENT)
    check_enum(tid, r, "location_kind", LOCATION_KIND)
    check_enum(tid, r, "access_required", ACCESS)
    check_enum(tid, r, "machine_required", MACHINE)
    for f in ("night_permitted", "monsoon_restricted"):
        check_enum(tid, r, f, BOOL)
    for f in ("nominal_duration_min", "min_crew"):
        if not r[f].isdigit() or int(r[f]) <= 0:
            fail("%s: %s must be a positive integer" % (tid, f))
    for f in ("adjacent_line_speed_restriction_kmph", "worksite_length_km",
              "default_periodicity_days"):
        if r[f]:
            try:
                float(r[f])
            except ValueError:
                fail("%s: %s not numeric" % (tid, f))
    # A power block belongs to traction distribution and a disconnection to S&T;
    # anything else means the access mechanism was mis-assigned.
    if r["access_required"] == "power_block" and r["department"] != "TRD":
        fail("%s: power_block outside TRD" % tid)
    if r["access_required"] == "disconnection" and r["department"] != "SNT":
        fail("%s: disconnection outside SNT" % tid)
    # A caution is imposed only where men or plant stand in the danger zone of a
    # line still open to traffic, and it needs a length to apply over.
    caution = r["adjacent_line_speed_restriction_kmph"]
    if caution and r["access_required"] == "none":
        fail("%s: caution on a task needing no access" % tid)
    if caution and not r["worksite_length_km"]:
        fail("%s: caution without worksite_length_km" % tid)
    # Section 9 requires a task to carry both task_type_id and asset_id, and the two
    # must agree. An empty value means span-based work with no single asset, which
    # Section 9 permits by making asset_id nullable.
    if r["applies_to_asset_type"] and r["applies_to_asset_type"] not in ASSET_TYPE:
        fail("%s: applies_to_asset_type=%r not in the 12.1 enumeration"
             % (tid, r["applies_to_asset_type"]))
    # Blueprint 2.4: a station has a route count and a disconnection consumes some.
    if not r["routes_consumed"].isdigit():
        fail("%s: routes_consumed must be a non-negative integer" % tid)
    else:
        consumed = int(r["routes_consumed"])
        if r["location_kind"] == "edge" and consumed:
            fail("%s: an edge task cannot consume station route capacity" % tid)
        if (r["location_kind"] == "node" and r["access_required"] != "none"
                and not consumed):
            fail("%s: node task takes access but consumes no route" % tid)

# Every asset type in the 12.1 enumeration needs at least one task type acting on
# it, or assets.csv will carry rows no task can ever be raised against.
acting_on = {r["applies_to_asset_type"] for r in task_types if r["applies_to_asset_type"]}
for asset_type in sorted(ASSET_TYPE - acting_on):
    fail("asset_type %s has no task type acting on it" % asset_type)

# The reverse: every asset type present in assets.csv must be reachable by a task
# type of the same department, or the asset is owned by nobody who can work it.
owner = defaultdict(set)
for r in task_types:
    if r["applies_to_asset_type"]:
        owner[r["applies_to_asset_type"]].add(r["department"])
for r in assets:
    if r["asset_type"] in owner and r["department"] not in owner[r["asset_type"]]:
        fail("%s: department %s does not maintain %s (maintained by %s)"
             % (r["asset_id"], r["department"], r["asset_type"],
                "/".join(sorted(owner[r["asset_type"]]))))
        break

# A node task can only be raised where its asset actually exists.
node_types = {r["applies_to_asset_type"] for r in task_types
              if r["location_kind"] == "node" and r["applies_to_asset_type"]}
sited = {r["asset_type"] for r in assets if r["station_code"]}
for asset_type in sorted(node_types - sited):
    fail("node tasks act on %s but no %s asset is sited at any station"
         % (asset_type, asset_type))

# A node task must fit inside the smallest yard it could be scheduled at, or the
# node resource model can never satisfy it.
yards = [r for r in stations if r["has_yard"] == "true" and r["route_capacity"]]
if yards:
    smallest = min(yards, key=lambda r: int(r["route_capacity"]))
    cap = int(smallest["route_capacity"])
    for r in task_types:
        if r["routes_consumed"].isdigit() and int(r["routes_consumed"]) > cap:
            note("%s consumes %s routes; the smallest yard %s has only %d - it can "
                 "never run there" % (r["task_type_id"], r["routes_consumed"],
                                      smallest["station_code"], cap))

# --------------------------------------------------- 8.5 compatibility matrix
rules = load("compatibility_matrix.csv")
rule_ids = set()
pairs = {}
for r in rules:
    rid = r["rule_id"]
    if rid in rule_ids:
        fail("compatibility_matrix: duplicate rule_id %s" % rid)
    rule_ids.add(rid)
    for f in ("type_a", "type_b"):
        if r[f] not in tt:
            fail("%s: %s references unknown task type %s" % (rid, f, r[f]))
    if r["type_a"] == r["type_b"]:
        fail("%s: rule pairs a task type with itself" % rid)
    check_enum(rid, r, "relation", RELATION)
    if r["max_distance_m"] and not r["max_distance_m"].isdigit():
        fail("%s: max_distance_m not an integer" % rid)
    if not r["rule_basis"]:
        fail("%s: rule_basis is empty - the reason is the point of the row" % rid)
    if r["validated_by"]:
        fail("%s: validated_by is set; per Data Spec 8.5 it stays blank until an "
             "officer confirms the rule" % rid)
    key = frozenset((r["type_a"], r["type_b"]))
    if key in pairs:
        fail("%s: pair already ruled by %s" % (rid, pairs[key]))
    pairs[key] = rid

# ------------------------------------------------------- 8.6 machines and crews
machines = load("machines.csv")
crews = load("crews.csv")
SHIFT_PATTERN = {"rotating_3", "rotating_2", "day_only"}

# 8.6 calls available_from/available_to an availability calendar, so a machine
# appears once per window. The key is (machine_id, available_from).
machine_class = {}
seen_windows = set()
for r in machines:
    mid = r["machine_id"]
    key = (mid, r["available_from"])
    if key in seen_windows:
        fail("machines: duplicate window %s from %s" % key)
    seen_windows.add(key)
    check_enum(mid, r, "machine_type", MACHINE - {"none"})
    # A machine cannot change class between its own windows.
    if machine_class.setdefault(mid, r["machine_type"]) != r["machine_type"]:
        fail("%s: appears as both %s and %s"
             % (mid, machine_class[mid], r["machine_type"]))
    if r["home_base"] not in by_code:
        fail("%s: unknown home_base %s" % (mid, r["home_base"]))
    if r["current_section"] and r["current_section"] not in sec_ids:
        fail("%s: unknown current_section %s" % (mid, r["current_section"]))
    if r["available_from"] >= r["available_to"]:
        fail("%s: availability window ends before it starts" % mid)
    for f in ("output_rate", "transit_time_h"):
        try:
            if float(r[f]) <= 0:
                fail("%s: %s must be positive" % (mid, f))
        except ValueError:
            fail("%s: %s not numeric" % (mid, f))

# Every machine class a task type calls for must exist in the fleet, or that work
# can never be scheduled at all.
fleet_classes = set(machine_class.values())
for r in task_types:
    if r["machine_required"] != "none" and r["machine_required"] not in fleet_classes:
        fail("%s needs a %s but none is in the fleet"
             % (r["task_type_id"], r["machine_required"]))

crew_ids = set()
qualified = defaultdict(int)
for r in crews:
    cid = r["crew_id"]
    if cid in crew_ids:
        fail("crews: duplicate crew_id %s" % cid)
    crew_ids.add(cid)
    check_enum(cid, r, "department", DEPARTMENT)
    check_enum(cid, r, "shift_pattern", SHIFT_PATTERN)
    if r["base_section"] and r["base_section"] not in sec_ids:
        fail("%s: unknown base_section %s" % (cid, r["base_section"]))
    if not r["size"].isdigit() or int(r["size"]) <= 0:
        fail("%s: size must be a positive integer" % cid)
    for f in ("min_rest_hours", "max_consecutive_nights", "max_weekly_duty_hours"):
        if not r[f].isdigit():
            fail("%s: %s must be a non-negative integer" % (cid, f))
    # A day-only crew can never work a night, and a rotating crew must be able to.
    if r["shift_pattern"] == "day_only" and int(r["max_consecutive_nights"] or 0):
        fail("%s: day_only crew with a night allowance" % cid)
    if r["shift_pattern"].startswith("rotating") and not int(r["max_consecutive_nights"] or 0):
        fail("%s: rotating crew that can never work a night" % cid)
    for q in filter(None, r["qualifications"].split(";")):
        if q not in tt:
            fail("%s: qualification %s is not a task type" % (cid, q))
        elif tt[q]["department"] != r["department"]:
            fail("%s: %s crew qualified on a %s task type %s"
                 % (cid, r["department"], tt[q]["department"], q))
        else:
            qualified[q] += 1

# Work nobody is qualified to do can never be scheduled. This is the check that
# caught ten orphaned task types when the crew establishment was first generated.
for r in task_types:
    if not qualified.get(r["task_type_id"]):
        fail("%s: no crew is qualified to do it" % r["task_type_id"])

# A crew must be able to reach the work: every department needs crews based on
# every corridor, or a whole corridor is unserviceable by that department.
based_on = defaultdict(set)
for r in crews:
    if r["base_section"] in by_id:
        based_on[r["department"]].add(by_id[r["base_section"]]["corridor_id"])
for dept in sorted(DEPARTMENT):
    absent = sorted(set(CORRIDOR_ORIGIN) - based_on[dept])
    if absent:
        note("%s has no crew based on corridor %s" % (dept, ", ".join(absent)))

# ------------------------------- Data Spec 9.1 merge candidate (Blueprint 6.4)
# Absent pairs default to `parallel` - see compatibility_matrix.README.md.
relation = {}
for r in rules:
    relation[(r["type_a"], r["type_b"])] = r["relation"]
    if r["relation"] != "sequential":
        relation[(r["type_b"], r["type_a"])] = r["relation"]

CANDIDATE = ["ENG-RAIL-WELD", "TRD-OHE-INSP", "SNT-POINT-SERVICE"]
EXPECTED_CRITICAL_PATH = 180
critical = None

blocked = [(a, b) for a in CANDIDATE for b in CANDIDATE
           if a < b and relation.get((a, b)) == "incompatible"]
if blocked:
    fail("9.1 merge candidate blocked by an incompatible pair: %s" % blocked)

if all(t in tt for t in CANDIDATE):
    duration = {t: int(tt[t]["nominal_duration_min"]) for t in CANDIDATE}
    successors = {t: [u for u in CANDIDATE
                      if relation.get((t, u)) == "sequential"] for t in CANDIDATE}
    memo = {}

    def longest_path(t):
        if t not in memo:
            memo[t] = duration[t] + max([longest_path(u) for u in successors[t]] or [0])
        return memo[t]

    critical = max(longest_path(t) for t in CANDIDATE)
    if critical != EXPECTED_CRITICAL_PATH:
        fail("9.1 merge candidate: critical path %d min, expected %d"
             % (critical, EXPECTED_CRITICAL_PATH))

# The section named throughout the documents must exist on every trunk line, or
# the worked examples in Blueprint 2.2 and Data Spec 9.1 have nothing to sit on.
for line in ("UP", "DN", "UP_SUB", "DN_SUB"):
    if "TRL-AJJ-%s" % line not in sec_ids:
        fail("TRL-AJJ-%s is missing; the documents' worked example depends on it" % line)

# ---------------------------------------------------------------------- report
print("stations              %3d rows  %s"
      % (len(stations), dict(Counter(r["corridor_id"] for r in stations))))
print("block_sections        %3d rows over %d spans"
      % (len(sections), len(spans)))
print("assets              %5d rows  %s"
      % (len(assets), dict(Counter(r["criticality_class"] for r in assets))))
print("task_types            %3d rows  %s  %d/%d asset types covered"
      % (len(task_types), dict(Counter(r["department"] for r in task_types)),
         len(acting_on), len(ASSET_TYPE)))
print("machines              %3d windows over %d machines  %s"
      % (len(machines), len(machine_class), dict(Counter(machine_class.values()))))
print("crews                 %3d rows, %d men  %s"
      % (len(crews), sum(int(r["size"]) for r in crews),
         dict(Counter(r["department"] for r in crews))))
print("compatibility_matrix  %3d rows  %s"
      % (len(rules), dict(Counter(r["relation"] for r in rules))))
if critical is not None:
    print("9.1 merge candidate   critical path %d min (sum %d)"
          % (critical, sum(int(tt[t]["nominal_duration_min"]) for t in CANDIDATE)))

if notes:
    print("\n%d NOTE(S) - modelled departures from the real network" % len(notes))
    for n in notes:
        print("  - %s" % n)

if errors:
    print("\n%d ERROR(S)" % len(errors))
    for e in errors:
        print("  - %s" % e)
    sys.exit(1)
print("\nOK")
