# -*- coding: utf-8 -*-
"""Emit data/history/detention_log.csv (Data Spec 11.3).

One row per executed *traffic* block: how many trains it held, the analytical
estimate of the detention it caused, and what the detention actually was. The gap
between the two is what the residual model learns (Blueprint 8.3):

    predicted_detention = analytical_estimate + residual_model(features)

total_detention_min is the target and the unit of the objective function, so the
analytical component must be a real calculation - overlapping trains, held vs
divertible, one-hop cascade - not a random number, or the residual it leaves has
no structure to learn. The analytical estimate here overlaps each block against
the actual train_paths on its edge; the residual is applied as a structured error
that grows at peak time bands and on congested sections, which is exactly where
Blueprint 8.3 says the arithmetic is systematically wrong.

Disconnection-only blocks (all-node work) never hold the running line, so they
raise no detention row - the log is one per *traffic* block, not per block.

Fixed seed per 12.5.
"""
from __future__ import print_function

import csv
import os
import random
from collections import defaultdict

SEED = 26027
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")
DEMAND = os.path.join(HERE, os.pardir, "demand")
HISTORY = os.path.join(HERE, os.pardir, "history")

REROUTE_PENALTY = 8          # spec 13 default, minutes
CASCADE = 1.2                # one-hop knock-on onto the train behind
# Balanced train-priority weights, by priority_class (Blueprint 7.4).
WEIGHT = {1: 1.8, 2: 1.5, 3: 1.3, 4: 1.1, 5: 1.3, 6: 0.7}
# Where the analytical arithmetic is systematically wrong (Blueprint 8.3): peak
# bands and congested holding points. This is the residual the model recovers.
BAND_RESIDUAL = {"00-06": 0.05, "06-12": 0.25, "12-18": 0.12, "18-24": 0.20}

HEADER = ["block_id", "analytical_estimate_min", "trains_affected",
          "total_detention_min", "rerouted_count", "cancelled_count", "time_band"]


def load(name, folder):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def band_of(minute):
    h = (minute // 60) % 24
    return "00-06" if h < 6 else "06-12" if h < 12 else "12-18" if h < 18 else "18-24"


def build():
    rng = random.Random(SEED)
    blocks = load("block_executions.csv", HISTORY)
    tasks = {t["task_id"]: t for t in load("tasks.csv", DEMAND)}
    sections = {s["block_section_id"]: s for s in load("block_sections.csv", REF)}
    paths = load("train_paths.csv", HISTORY.replace("history", "supply"))

    on_edge = defaultdict(list)
    for p in paths:
        on_edge[p["block_section_id"]].append(p)

    rows = []
    for b in blocks:
        if b["availed"] != "true" or not b["actual_start"]:
            continue
        # A traffic block holds the running line; an all-node disconnection does
        # not. Decide from the tasks that made up the block.
        included = [tasks[t] for t in b["tasks_included"].split(";") if t in tasks]
        if included and all(t["location_kind"] == "node" for t in included):
            continue

        bsid = b["block_section_id"]
        sec = sections.get(bsid)
        start = to_min(b["actual_start"][11:16])
        dur = int(b["sanctioned_duration_min"])
        end = start + dur

        held = reroute = cancelled = 0
        analytical = 0.0
        for p in on_edge.get(bsid, []):
            entry = to_min(p["entry_time"])
            # Does the train try to enter while the line is blocked? (midnight wrap)
            e = entry if entry >= start else entry + 1440
            if not (start <= e <= end):
                continue
            w = WEIGHT[int(p["priority_class"])]
            if p["divertible"] == "true":
                reroute += 1
                analytical += REROUTE_PENALTY * w
            else:
                held += 1
                wait = (end - e)                       # held until the block ends
                if sec and sec["line_id"] == "SINGLE" and wait > dur * 0.9:
                    cancelled += 1                     # nowhere to hold on a single line
                    analytical += dur * 1.5 * w        # cancellation is expensive
                else:
                    analytical += wait * CASCADE * w

        affected = held + reroute
        tb = band_of(start)
        # The residual: structured error the analytical model makes, larger at
        # peak and on congested sections, plus a little irreducible noise.
        congestion = (int(sec["daily_train_count"]) / 300.0) if sec else 0.0
        resid_frac = BAND_RESIDUAL[tb] + 0.20 * congestion + rng.uniform(-0.05, 0.05)
        total = max(0, analytical * (1 + resid_frac) + rng.uniform(-3, 3) * affected)

        rows.append({
            "block_id": b["block_id"],
            "analytical_estimate_min": int(round(analytical)),
            "trains_affected": affected,
            "total_detention_min": int(round(total)),
            "rerouted_count": reroute,
            "cancelled_count": cancelled,
            "time_band": tb,
        })
    return rows


def main():
    rows = build()
    if not os.path.isdir(HISTORY):
        os.makedirs(HISTORY)
    out = os.path.join(HISTORY, "detention_log.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    nz = sum(1 for r in rows if r["trains_affected"] > 0)
    print("detention_log.csv: %d rows, %d held at least one train" % (len(rows), nz))


if __name__ == "__main__":
    main()
