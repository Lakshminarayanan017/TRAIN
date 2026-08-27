# -*- coding: utf-8 -*-
"""Emit data/history/emergency_events.csv (Data Spec 11.4).

The disruption record. An emergency is not an input to the planner, it is an input
to reality (Blueprint 10.1): by the time it is logged, the section is seized and
the crew is diverted. This log is what the emergency re-planner learns the shape
of - how often events happen, how long a section is held, and which resources they
pull away from planned work.

Grounded seasonality (spec 12.3 names the monsoon window and heat as real): rail
fractures cluster in the April-June heat when the rail buckles; OHE failures and
weather events cluster in the October-December north-east monsoon; cattle
run-overs and point/signal failures fall through the year. Events land on the real
network, weighted towards the traffic and asset type each failure mode belongs to,
and their follow-up permanent repairs reference the emergency_followup tasks that
already exist in the demand pool.

Fixed seed per 12.5.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import random
from collections import defaultdict

SEED = 26027
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")
DEMAND = os.path.join(HERE, os.pardir, "demand")
HISTORY = os.path.join(HERE, os.pardir, "history")

TODAY = dt.date(2026, 9, 7)
HORIZON_DAYS = 365
TARGET_EVENTS = 180

EVENT_MIX = [("rail_fracture", 0.18), ("OHE_failure", 0.16), ("point_failure", 0.16),
             ("signal_failure", 0.14), ("cattle_run_over", 0.14),
             ("weather", 0.12), ("other", 0.10)]

# Minutes the section is seized, by event type.
DURATION = {"rail_fracture": (120, 300), "OHE_failure": (90, 240),
            "point_failure": (60, 180), "signal_failure": (45, 150),
            "cattle_run_over": (30, 90), "weather": (180, 600), "other": (60, 240)}

# Which months an event favours - real Chennai seasonality.
SEASON_MONTHS = {
    "rail_fracture": {4: 3, 5: 4, 6: 3},               # pre-monsoon heat
    "OHE_failure": {10: 3, 11: 4, 12: 3},              # monsoon
    "weather": {10: 4, 11: 5, 12: 4},                  # north-east monsoon
}

# The department that attends each event, for resource diversion.
DEPT = {"rail_fracture": "ENG", "OHE_failure": "TRD", "point_failure": "SNT",
        "signal_failure": "SNT", "cattle_run_over": "ENG", "weather": "ENG",
        "other": "ENG"}
# Events whose permanent repair enters the pool as a fresh hard-deadline task.
GENERATES_FOLLOWUP = {"rail_fracture", "OHE_failure", "point_failure"}

HEADER = ["event_id", "event_type", "block_section_id", "km", "occurred_at",
          "duration_min", "resources_consumed", "blocks_invalidated",
          "followup_task_id"]


def load(name, folder):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
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
    sections = load("block_sections.csv", REF)
    crews = load("crews.csv", REF)
    machines = load("machines.csv", REF)
    tasks = load("tasks.csv", DEMAND)
    blocks = [b["block_id"] for b in load("block_executions.csv", HISTORY)]

    crews_by_dept = defaultdict(list)
    for c in crews:
        crews_by_dept[c["department"]].append(c["crew_id"])
    machines_by_type = defaultdict(list)
    for m in machines:
        machines_by_type[m["machine_type"]].append(m["machine_id"])
    followups_by_dept = defaultdict(list)
    for t in tasks:
        if t["origin"] == "emergency_followup":
            followups_by_dept[t["department"]].append(t["task_id"])

    electrified = [s for s in sections if s["electrified"] == "true"]
    trunkish = [s for s in sections if s["traffic_type"] in ("trunk", "freight")]
    outer = [s for s in sections if s["traffic_type"] in ("branch", "freight")]

    def section_for(etype):
        if etype == "OHE_failure":
            pool = electrified
        elif etype == "rail_fracture":
            pool = trunkish or sections           # heavy-tonnage lines fracture
        elif etype == "cattle_run_over":
            pool = outer or sections              # rural / outer stretches
        else:
            pool = sections
        # Weight by traffic so busy sections see more incidents.
        weights = [max(1, int(s["daily_train_count"])) for s in pool]
        target = rng.random() * sum(weights)
        run = 0.0
        for s, w in zip(pool, weights):
            run += w
            if run >= target:
                return s
        return pool[-1]

    def occurred(etype):
        months = SEASON_MONTHS.get(etype)
        for _ in range(40):
            d = TODAY - dt.timedelta(days=rng.randint(1, HORIZON_DAYS))
            if months is None or rng.random() < months.get(d.month, 1) / 5.0:
                return d
        return TODAY - dt.timedelta(days=rng.randint(1, HORIZON_DAYS))

    rows = []
    for i in range(TARGET_EVENTS):
        etype = pick(rng, EVENT_MIX)
        sec = section_for(etype)
        km = round(rng.uniform(float(sec["start_km"]), float(sec["end_km"])), 2)
        day = occurred(etype)
        hour = rng.randint(5, 8) if etype == "cattle_run_over" else rng.randint(0, 23)
        occurred_at = dt.datetime.combine(day, dt.time(hour, rng.choice([0, 15, 30, 45])))
        lo, hi = DURATION[etype]
        duration = rng.randint(lo, hi)

        dept = DEPT[etype]
        resources = [rng.choice(crews_by_dept[dept])]
        if etype == "rail_fracture" and rng.random() < 0.5:
            resources.append(rng.choice(machines_by_type["USFD_car"] or ["USFD-SR-01"]))
        if etype == "OHE_failure":
            resources.append(rng.choice(machines_by_type["OHE_tower_car"] or ["OHE-TC-01"]))

        invalid = []
        if rng.random() < 0.35 and blocks:
            invalid = rng.sample(blocks, rng.randint(1, 2))

        # The permanent repair enters the pool as a task owned by the same
        # department that attends the failure - OHE by TrD, rail by ENG, points
        # by S&T - so the follow-up reference matches the event, not a random dept.
        followup = ""
        pool_fu = followups_by_dept.get(dept, [])
        if etype in GENERATES_FOLLOWUP and pool_fu and rng.random() < 0.7:
            followup = rng.choice(pool_fu)

        rows.append({
            "event_id": "EMG-%d-%04d" % (day.year, i + 1),
            "event_type": etype,
            "block_section_id": sec["block_section_id"],
            "km": "%.2f" % km,
            "occurred_at": occurred_at.strftime("%Y-%m-%d %H:%M"),
            "duration_min": duration,
            "resources_consumed": ";".join(resources),
            "blocks_invalidated": ";".join(invalid),
            "followup_task_id": followup,
        })
    return rows


def main():
    rows = build()
    if not os.path.isdir(HISTORY):
        os.makedirs(HISTORY)
    out = os.path.join(HISTORY, "emergency_events.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    import collections
    print("emergency_events.csv: %d events  %s"
          % (len(rows), dict(collections.Counter(r["event_type"] for r in rows))))


if __name__ == "__main__":
    main()
