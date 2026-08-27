# -*- coding: utf-8 -*-
"""Referential and domain checks over data/supply/ (Data Spec 10).

Run:  python data/checks/validate_supply.py
Exit 0 clean, 1 on any error. Covers train_paths.csv (10.1) so far; extend as
goods_forecast (10.2) and corridor_windows (10.3) land.

Errors fail the build. Notes record groundedness signals worth seeing - chiefly
how the generated per-edge train counts line up with block_sections'
daily_train_count anchor, which is the check that the supply layer and the
reference layer describe the same railway.
"""
from __future__ import print_function

import csv
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
REF = os.path.join(ROOT, "reference")
SUPPLY = os.path.join(ROOT, "supply")

TRAIN_TYPE = {"rajdhani_class", "superfast", "express", "passenger", "EMU",
              "MEMU", "goods", "special", "light_engine"}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DAYS_RE = re.compile(r"^[01]{7}$")

errors, notes = [], []


def fail(m):
    errors.append(m)


def note(m):
    notes.append(m)


def load(name, folder):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


sections = {r["block_section_id"]: r for r in load("block_sections.csv", REF)}
paths = load("train_paths.csv", SUPPLY)

seen = set()
train_meta = {}                 # train_no -> (type, priority, days)
per_edge = Counter()            # block_section_id -> path count
by_train = defaultdict(list)    # train_no -> rows

for r in paths:
    pid = r["path_id"]
    if pid in seen:
        fail("train_paths: duplicate path_id %s" % pid)
    seen.add(pid)

    if not r["train_no"].isdigit():
        fail("%s: train_no %r not numeric" % (pid, r["train_no"]))
    if r["train_type"] not in TRAIN_TYPE:
        fail("%s: train_type %r not in the 12.1 enumeration" % (pid, r["train_type"]))
    if r["block_section_id"] not in sections:
        fail("%s: unknown block_section_id %s" % (pid, r["block_section_id"]))
    for f in ("entry_time", "exit_time"):
        if not TIME_RE.match(r[f]):
            fail("%s: %s=%r is not HH:MM" % (pid, f, r[f]))
    if not DAYS_RE.match(r["days_of_week"]):
        fail("%s: days_of_week=%r must be 7 binary digits" % (pid, r["days_of_week"]))
    elif r["days_of_week"] == "0000000":
        fail("%s: a train that never runs" % pid)
    if not r["priority_class"].isdigit() or not (1 <= int(r["priority_class"]) <= 6):
        fail("%s: priority_class %r must be 1-6" % (pid, r["priority_class"]))
    if r["divertible"] not in ("true", "false"):
        fail("%s: divertible %r not boolean" % (pid, r["divertible"]))

    # path_id must name its own train and section, or a join on it goes wrong.
    if r["block_section_id"] in sections:
        s = sections[r["block_section_id"]]
        want = "P-%s-%s-%s" % (r["train_no"], s["from_station"] + s["to_station"], s["line_id"])
        if pid != want:
            fail("%s: path_id does not match train/section (expected %s)" % (pid, want))
        # A train may only occupy an edge whose line it can run on: a divertible
        # long-distance train has no business on a dedicated suburban pair, and a
        # single-line branch edge is never divertible.
        if s["line_id"] == "SINGLE" and r["divertible"] == "true":
            fail("%s: a single-line branch path cannot be divertible" % pid)

    meta = (r["train_type"], r["priority_class"], r["days_of_week"])
    if train_meta.setdefault(r["train_no"], meta) != meta:
        fail("%s: train %s changes type/priority/days between edges"
             % (pid, r["train_no"]))
    per_edge[r["block_section_id"]] += 1
    by_train[r["train_no"]].append(r)

# Every edge that the reference layer says carries traffic must have at least one
# path, or the window enumerator sees a permanently free line that is not.
for bsid, s in sorted(sections.items()):
    if int(s["daily_train_count"]) > 0 and per_edge[bsid] == 0:
        fail("%s: daily_train_count=%s but no train path traverses it"
             % (bsid, s["daily_train_count"]))

# Grounding signal: generated per-edge counts against the reference anchor. Both
# directions of a span share its daily_train_count, so compare the busier edge of
# each (span,line-kind) against it. Large gaps are worth seeing, not failing -
# the anchor is itself an approximation (block_sections.README).
def kindof(line):
    return "sub" if line.endswith("_SUB") else ("single" if line == "SINGLE" else "main")

anchor_hits = 0
for bsid, s in sorted(sections.items()):
    anchor = int(s["daily_train_count"])
    got = per_edge[bsid]
    if anchor and got:
        ratio = got / float(anchor)
        anchor_hits += 1
        if ratio > 2.5 or ratio < 0.3:
            note("%s carries %d paths vs daily_train_count %d (x%.1f)"
                 % (bsid, got, anchor, ratio))

# A train runs one way: all its edges must be UP-group, all DN-group, or the
# single line - never a mix. A number on both directions is two physical
# services sharing one identity, which is how a base-range collision shows up.
for tno, rs in by_train.items():
    groups = set()
    for r in rs:
        s = sections.get(r["block_section_id"])
        if s is None:
            continue
        lid = s["line_id"]
        groups.add("single" if lid == "SINGLE"
                   else ("up" if lid.startswith("UP") else "down"))
    if "up" in groups and "down" in groups:
        fail("train %s runs on both UP and DN lines - one number, two services" % tno)

# A train's successive edges must chain forward in time (allowing a midnight
# wrap), or the path is not a single physical run.
def mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

for tno, rs in by_train.items():
    for a, b in zip(rs, rs[1:]):
        gap = (mins(b["entry_time"]) - mins(a["exit_time"])) % 1440
        if gap > 30:  # more than a 30-min dwell between consecutive edges
            note("train %s: %s min gap between %s and %s"
                 % (tno, gap, a["block_section_id"], b["block_section_id"]))
            break

# ============================================================ 10.2 goods forecast
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_BAND = {"00-06", "06-12", "12-18", "18-24"}
goods = load("goods_forecast.csv", SUPPLY)
g_seen = set()
for r in goods:
    key = (r["forecast_date"], r["block_section_id"], r["time_band"])
    if key in g_seen:
        fail("goods_forecast: duplicate (%s, %s, %s)" % key)
    g_seen.add(key)
    if not DATE_RE.match(r["forecast_date"]):
        fail("goods_forecast %s: forecast_date not ISO" % (key,))
    if r["block_section_id"] not in sections:
        fail("goods_forecast: unknown block_section_id %s" % r["block_section_id"])
    elif sections[r["block_section_id"]]["traffic_type"] not in ("freight", "trunk"):
        note("goods_forecast sits on non-freight edge %s" % r["block_section_id"])
    if r["time_band"] not in TIME_BAND:
        fail("goods_forecast %s: time_band not in enumeration" % (key,))
    if not r["expected_rakes"].lstrip("-").isdigit() or int(r["expected_rakes"]) < 0:
        fail("goods_forecast %s: expected_rakes must be a non-negative integer" % (key,))
    if r["confidence"]:
        try:
            c = float(r["confidence"])
            if not (0.0 <= c <= 1.0):
                fail("goods_forecast %s: confidence %s out of [0,1]" % (key, c))
        except ValueError:
            fail("goods_forecast %s: confidence not numeric" % (key,))

# ========================================================= 10.3 corridor windows
DAY = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
WINDOW_TYPE = {"corridor_block", "traffic_gap", "requested"}
windows = load("corridor_windows.csv", SUPPLY)
w_seen = set()
blocked = defaultdict(set)          # (span, day) -> lines blocked by a corridor block
span_lines = defaultdict(set)
for s in sections.values():
    span_lines[(s["from_station"], s["to_station"])].add(s["line_id"])
for r in windows:
    wid = r["window_id"]
    if wid in w_seen:
        fail("corridor_windows: duplicate window_id %s" % wid)
    w_seen.add(wid)
    s = sections.get(r["block_section_id"])
    if s is None:
        fail("%s: unknown block_section_id %s" % (wid, r["block_section_id"]))
    if r["day_of_week"] not in DAY:
        fail("%s: day_of_week %r not a weekday code" % (wid, r["day_of_week"]))
    if not TIME_RE.match(r["start_time"]):
        fail("%s: start_time %r not HH:MM" % (wid, r["start_time"]))
    if not r["duration_min"].isdigit() or int(r["duration_min"]) <= 0:
        fail("%s: duration_min must be a positive integer" % wid)
    if r["window_type"] not in WINDOW_TYPE:
        fail("%s: window_type %r not in enumeration" % (wid, r["window_type"]))
    if r["max_departments"] and (not r["max_departments"].isdigit()
                                 or not (1 <= int(r["max_departments"]) <= 3)):
        fail("%s: max_departments must be 1-3 (only three departments exist)" % wid)
    if s is not None:
        want = "W-%s%s-%s-%s" % (s["from_station"], s["to_station"],
                                 s["line_id"], r["day_of_week"])
        if wid != want:
            fail("%s: window_id does not match section/day (expected %s)" % (wid, want))
        if r["window_type"] == "corridor_block":
            blocked[((s["from_station"], s["to_station"]), r["day_of_week"])].add(s["line_id"])

# A corridor block must never take every line of a multi-line span at once - that
# severs the section the block was meant to keep workable (Blueprint 2.2, FR-21).
for (span, day), lines in blocked.items():
    if len(span_lines[span]) > 1 and lines == span_lines[span]:
        fail("corridor block severs %s-%s on %s: all lines blocked at once"
             % (span[0], span[1], day))

# ---------------------------------------------------------------------- report
print("train_paths          %5d rows over %d trains  %s"
      % (len(paths), len(train_meta), dict(Counter(r["train_type"] for r in paths))))
print("priority mix              %s"
      % dict(sorted(Counter(int(r["priority_class"]) for r in paths).items())))
print("edges covered             %d / %d block sections  (anchor-compared %d)"
      % (len({r["block_section_id"] for r in paths}), len(sections), anchor_hits))
print("goods_forecast       %5d rows over %d freight edges  %d-day horizon"
      % (len(goods), len({r["block_section_id"] for r in goods}),
         len({r["forecast_date"] for r in goods})))
print("corridor_windows     %5d windows  %s"
      % (len(windows), dict(Counter(sections[r["block_section_id"]]["corridor_id"]
                                     for r in windows if r["block_section_id"] in sections))))

if notes:
    print("\n%d NOTE(S)" % len(notes))
    for n in notes[:20]:
        print("  - %s" % n)
    if len(notes) > 20:
        print("  ... %d more" % (len(notes) - 20))

if errors:
    print("\n%d ERROR(S)" % len(errors))
    for e in errors[:40]:
        print("  - %s" % e)
    sys.exit(1)
print("\nOK")
