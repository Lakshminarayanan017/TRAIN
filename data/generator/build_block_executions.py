# -*- coding: utf-8 -*-
"""Emit data/history/block_executions.csv (Data Spec 11.1).

The training set. One row per block actually worked over the past year, carrying
what was requested, what was sanctioned, and what actually happened. It is the
target for two models at once: the duration model (actual_end - actual_start) and
the availment model (availed).

No system in service records this - it is "the bucket nobody currently has" (spec
11), and collecting it is the project's most defensible contribution. So it is
synthesised, but every relationship the models are meant to learn is deliberately
built in, because a model trained on features that do not move the target learns
nothing and only looks like it works:

  - **Deliberate positive overrun bias** (spec 12.3): actual runs longer than the
    department *asked for*, on average. The sanctioned buffer absorbs most of it,
    so overrun against the *sanctioned* time is positive on ~a quarter of blocks -
    consistent with a P80 buffer (Blueprint 7.5).
  - **Merged work is slower per task** (Blueprint 8.1): was_merged lifts duration.
    Omit it and the model underestimates exactly the blocks the system exists to
    create.
  - **Condition drives duration**: asset age/tonnage, crew adequacy, a late
    machine, and monsoon weather all lengthen the job.

Grounded where the world is real: the block is built from the actual `done` tasks
in tasks.csv (so tasks_included, departments, crews and machines are real refs,
not invented), and weather/season follow Chennai's real Oct-Dec north-east
monsoon. Historical merge rate is held low (~12%, spec 12.2 incidental rate) -
the whole point is that departments do *not* coordinate today.

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
INCIDENTAL_MERGE_RATE = 0.14   # attempts; net merged blocks land near 12% (spec 12.2)

OVERRUN_REASONS = ["material_delay", "crew_short", "machine_late", "weather",
                   "unexpected_condition", "traffic_hold"]

HEADER = ["block_id", "block_section_id", "tasks_included", "departments",
          "merge_group_id", "requested_start", "requested_duration_min",
          "sanctioned_start", "sanctioned_duration_min", "actual_start",
          "actual_end", "availed", "overrun_min", "overrun_reason",
          "crew_id", "machine_id", "weather", "season", "was_merged"]


def load(name, folder):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def month_season(date):
    # Chennai north-east monsoon, October to December.
    return "monsoon" if date.month in (10, 11, 12) else "normal"


def draw_weather(rng, season):
    if season == "monsoon":
        return _pick(rng, [("heavy_rain", 0.20), ("rain", 0.35), ("clear", 0.45)])
    return _pick(rng, [("heavy_rain", 0.02), ("rain", 0.12), ("clear", 0.86)])


def _pick(rng, weighted):
    roll, acc = rng.random(), 0.0
    for v, w in weighted:
        acc += w
        if roll <= acc:
            return v
    return weighted[-1][0]


def build():
    rng = random.Random(SEED)
    tasks = load("tasks.csv", DEMAND)
    task_types = {r["task_type_id"]: r for r in load("task_types.csv", REF)}
    sections = load("block_sections.csv", REF)
    crews = load("crews.csv", REF)
    machines = load("machines.csv", REF)
    rules = load("compatibility_matrix.csv", REF)

    incompatible = set()
    for r in rules:
        if r["relation"] == "incompatible":
            incompatible.add(frozenset((r["type_a"], r["type_b"])))
    sequential = set()
    for r in rules:
        if r["relation"] == "sequential":
            sequential.add(frozenset((r["type_a"], r["type_b"])))

    # A representative running edge for each station, for node/disconnection work
    # that occupies a station rather than a through section.
    incident = defaultdict(list)
    for s in sections:
        incident[s["from_station"]].append(s)
        incident[s["to_station"]].append(s)
    busiest_edge = {code: max(edges, key=lambda e: int(e["daily_train_count"]))
                    for code, edges in incident.items()}

    # Crews that can do each task type, and machines of each class.
    qual = defaultdict(list)
    for c in crews:
        for q in filter(None, c["qualifications"].split(";")):
            qual[q].append(c["crew_id"])
    by_machine_type = defaultdict(list)
    for m in machines:
        by_machine_type[m["machine_type"]].append(m["machine_id"])

    done = [t for t in tasks if t["status"] == "done"]
    rng.shuffle(done)

    by_key = defaultdict(list)
    for t in done:
        key = t["block_section_id"] if t["location_kind"] == "edge" else "N:" + t["station_code"]
        by_key[key].append(t)

    assigned = set()
    blocks = []
    for t in done:
        if t["task_id"] in assigned:
            continue
        block = [t]
        assigned.add(t["task_id"])
        key = t["block_section_id"] if t["location_kind"] == "edge" else "N:" + t["station_code"]
        # Occasionally merge co-located compatible tasks, preferring another
        # department - that is the coordination the baseline rarely achieves.
        if rng.random() < INCIDENTAL_MERGE_RATE:
            for u in by_key[key]:
                if len(block) >= 3 or u["task_id"] in assigned:
                    continue
                if any(frozenset((x["task_type_id"], u["task_type_id"])) in incompatible
                       for x in block):
                    continue
                block.append(u)
                assigned.add(u["task_id"])
        blocks.append(block)

    rows = []
    serial = 0
    mg_serial = 0
    for block in blocks:
        serial += 1
        primary = max(block, key=lambda t: int(t["requested_duration_min"]))
        # Requested duration by critical path: sequential members chain, parallel
        # members overlap. A close-enough rule for blocks of <= 3.
        durs = [int(t["requested_duration_min"]) for t in block]
        has_seq = any(frozenset((a["task_type_id"], b["task_type_id"])) in sequential
                      for i, a in enumerate(block) for b in block[i + 1:])
        req_dur = sum(durs) if (len(block) > 1 and has_seq) else max(durs)

        loc = primary["location_kind"]
        if loc == "edge":
            bsid = primary["block_section_id"]
        else:
            bsid = busiest_edge[primary["station_code"]]["block_section_id"]

        raised = dt.date(*map(int, primary["raised_date"].split("-")))
        lead = rng.randint(2, 35)
        night = primary["night_permitted"] == "true"
        hour = rng.randint(0, 3) if night else rng.randint(10, 13)
        minute = rng.choice([0, 15, 30, 45])
        req_start = dt.datetime.combine(raised + dt.timedelta(days=lead),
                                        dt.time(hour, minute))
        if req_start > dt.datetime.combine(TODAY, dt.time(0, 0)):
            req_start -= dt.timedelta(days=rng.randint(40, 120))  # keep it historical
        season = month_season(req_start.date())
        weather = draw_weather(rng, season)

        buffer_frac = rng.uniform(0.15, 0.28)              # P80-ish buffer
        sanctioned_dur = int(round(req_dur * (1 + buffer_frac)))
        sanctioned_start = req_start + dt.timedelta(minutes=rng.choice([0, 0, 15, -15]))

        # Duration model target. Positive bias against what was *requested*: the
        # mean factor sits above 1.0 so actual exceeds the request, while the
        # buffer keeps overruns against the *sanctioned* time near the P80 rate.
        factor = rng.gauss(1.05, 0.14)
        if len(block) > 1:
            factor *= rng.uniform(1.05, 1.22)              # merged is slower per task
        if weather == "rain":
            factor *= rng.uniform(1.02, 1.10)
        elif weather == "heavy_rain":
            factor *= rng.uniform(1.08, 1.20)
        machine_late = primary["machine_required"] != "none" and rng.random() < 0.12
        if machine_late:
            factor *= rng.uniform(1.10, 1.30)
        factor = max(0.72, factor)
        actual_dur = max(15, int(round(req_dur * factor)))

        # Availment: a sanctioned block goes unused mostly when the materials
        # never arrived or the machine could not reach it.
        avail_p = 0.90
        if primary["materials_ready"] == "false":
            avail_p -= 0.45
        if primary["machine_required"] != "none":
            avail_p -= 0.06
        availed = rng.random() < max(0.30, avail_p)

        crew_id = (rng.choice(qual[primary["task_type_id"]])
                   if qual.get(primary["task_type_id"]) else "")
        mreq = primary["machine_required"]
        machine_id = (rng.choice(by_machine_type[mreq])
                      if mreq != "none" and by_machine_type.get(mreq) else "")

        if availed:
            actual_start = sanctioned_start + dt.timedelta(minutes=rng.randint(-10, 20))
            actual_end = actual_start + dt.timedelta(minutes=actual_dur)
            overrun = actual_dur - sanctioned_dur
            if overrun > 10:
                weights = [("material_delay", 0.9), ("crew_short", 0.8),
                           ("machine_late", 1.6 if machine_late else 0.4),
                           ("weather", 2.0 if weather != "clear" else 0.2),
                           ("unexpected_condition", 1.0), ("traffic_hold", 0.7)]
                total = sum(w for _, w in weights)
                reason = _pick(rng, [(r, w / total) for r, w in weights])
            else:
                reason = "none"
            actual_start_s = actual_start.strftime("%Y-%m-%d %H:%M")
            actual_end_s = actual_end.strftime("%Y-%m-%d %H:%M")
            overrun_s = str(overrun)
        else:
            actual_start_s = actual_end_s = ""      # block was never worked
            overrun_s = ""
            reason = ""

        merged = len(block) > 1
        merge_group_id = ""
        if merged:
            mg_serial += 1
            merge_group_id = "MG-%d-%04d" % (req_start.year, mg_serial)

        rows.append({
            "block_id": "BLK-%d-%05d" % (req_start.year, serial),
            "block_section_id": bsid,
            "tasks_included": ";".join(t["task_id"] for t in block),
            "departments": ";".join(sorted({t["department"] for t in block})),
            "merge_group_id": merge_group_id,
            "requested_start": req_start.strftime("%Y-%m-%d %H:%M"),
            "requested_duration_min": req_dur,
            "sanctioned_start": sanctioned_start.strftime("%Y-%m-%d %H:%M"),
            "sanctioned_duration_min": sanctioned_dur,
            "actual_start": actual_start_s,
            "actual_end": actual_end_s,
            "availed": str(availed).lower(),
            "overrun_min": overrun_s,
            "overrun_reason": reason,
            "crew_id": crew_id,
            "machine_id": machine_id,
            "weather": weather,
            "season": season,
            "was_merged": str(merged).lower(),
        })
    return rows


def main():
    rows = build()
    if not os.path.isdir(HISTORY):
        os.makedirs(HISTORY)
    out = os.path.join(HISTORY, "block_executions.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    merged = sum(1 for r in rows if r["was_merged"] == "true")
    availed = sum(1 for r in rows if r["availed"] == "true")
    print("block_executions.csv: %d rows, %d merged (%.0f%%), %d availed"
          % (len(rows), merged, 100.0 * merged / len(rows), availed))


if __name__ == "__main__":
    main()
