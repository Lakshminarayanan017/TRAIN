# -*- coding: utf-8 -*-
"""The baseline planner - current practice, modelled honestly (FR-32, Blueprint 12.2).

The claim this project makes is comparative, so the baseline decides whether the
claim is worth anything. Current practice is modelled as it actually works:

    1. each department independently sorts its own backlog by urgency
    2. it requests corridor blocks for its top items, first come first served
       against what is still available
    3. it has no visibility into the other departments' requests
    4. operations grants what fits and rejects what clashes
    5. rejected work rolls into the following week

Note what this baseline is **not**: random, or stupid. Each department behaves
sensibly within its own information, and it is credited with the informal
coordination that really happens through phone calls and corridor meetings - an
incidental merge rate of 10-15%. That shrinks the headline number and is exactly
what makes it credible. The gap being measured is the cost of missing
information, not the cost of incompetence.

Fairness is enforced structurally: the baseline books through the same
``ResourceLedger`` the coordinated planner's constraints describe, so both obey
identical crew rest, machine transit, never-sever, corridor-ceiling and deadline
semantics. If the baseline were allowed to cheat on constraints the comparison
would be worthless - and the corridor ceiling is the case that proves it. It was
enforced on the optimiser alone at first, which let current practice book 64
blocks on the trunk against the optimiser's 40 and then counted the shortfall
against the optimiser as tasks it had failed to complete.
"""
from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict

from . import config
from .clustering import CompatibilityRules, _load as _load_csv
from .network import Network
import os


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


class ResourceLedger:
    """Books blocks against the shared hard constraints, and refuses anything
    that would breach one. The same semantics the CP-SAT model enforces
    declaratively, applied here incrementally so a greedy planner cannot drift
    into an infeasible plan."""

    def __init__(self, net, crews, machines, week_start):
        self.net = net
        self.week_start = week_start
        self.crew = {c["crew_id"]: c for c in crews}
        self.crew_bookings = defaultdict(list)      # crew_id -> [(start, end, day, night)]
        self.machine_bookings = defaultdict(list)   # machine_id -> [(start, end)]
        self.section_bookings = defaultdict(list)   # bsid -> [(start, end)]
        self.span_bookings = defaultdict(list)      # span -> [(start, end, bsid)]
        self.station_bookings = defaultdict(list)   # station -> [(start, end, routes)]
        self.corridor_blocks = defaultdict(int)     # corridor_id -> blocks booked this week

        self.machine_avail = defaultdict(list)      # machine_id -> [(start, end)]
        self.machine_type = {}
        self.machine_transit = {}
        base = dt.datetime.combine(week_start, dt.time(0, 0))
        for m in machines:
            mid = m["machine_id"]
            self.machine_type[mid] = m["machine_type"]
            self.machine_transit[mid] = int(round(float(m["transit_time_h"]) * 60))
            a0 = int((dt.datetime.strptime(m["available_from"], "%Y-%m-%d %H:%M") - base)
                     .total_seconds() // 60)
            a1 = int((dt.datetime.strptime(m["available_to"], "%Y-%m-%d %H:%M") - base)
                     .total_seconds() // 60)
            self.machine_avail[mid].append((a0, a1))

    # ---- feasibility --------------------------------------------------------
    def section_free(self, bsid, start, end):
        if any(_overlap(start, end, s, e) for s, e in self.section_bookings[bsid]):
            return False
        # Never sever: the span must keep at least one line open (FR-21).
        span = self.net.span_of(bsid)
        lines = self.net.edges_on_span(*span)
        if len(lines) > 1:
            busy = {b for s, e, b in self.span_bookings[span] if _overlap(start, end, s, e)}
            busy.add(bsid)
            if len(busy) >= len(lines):
                return False
        return True

    def corridor_free(self, bsid):
        """The weekly ceiling on how much of one corridor may be taken for
        maintenance. It is a policy on the railway, not a property of the
        optimiser, so current practice is held to it too - the coordinated
        planner carries the same constraint at instance level. Applying it to
        only one side would let the baseline take 60-plus blocks on the trunk
        against the optimiser's 40 and call the difference a planning result."""
        cor = self.net.edge(bsid)["corridor_id"]
        if not cor:
            return True
        return self.corridor_blocks[cor] < config.MAX_BLOCKS_PER_CORRIDOR_WEEK

    def station_free(self, station, start, end, routes):
        if routes <= 0:
            return True
        cap = int(self.net.station(station)["route_capacity"] or 0)
        used = sum(r for s, e, r in self.station_bookings[station] if _overlap(start, end, s, e))
        return used + routes <= cap

    def find_crew(self, department, size_needed, task_types, start, end, day, night):
        """A qualified crew that is free, rested, and inside its duty limits."""
        for cid, c in self.crew.items():
            if c["department"] != department or int(c["size"]) < size_needed:
                continue
            if not set(task_types) <= set(c["qualifications"].split(";")):
                continue
            rest = int(c["min_rest_hours"]) * 60
            books = self.crew_bookings[cid]
            if any(_overlap(start - rest, end + rest, s, e) for s, e, _, _ in books):
                continue
            worked = sum(e - s for s, e, _, _ in books) + (end - start)
            if worked > int(c["max_weekly_duty_hours"]) * 60:
                continue
            if night:
                nights = sorted({d for _, _, d, n in books if n} | {day})
                run = best = 1
                for a, b in zip(nights, nights[1:]):
                    run = run + 1 if b == a + 1 else 1
                    best = max(best, run)
                if best > int(c["max_consecutive_nights"]):
                    continue
            return cid
        return None

    def find_machine(self, machine_type, start, end):
        for mid, mt in self.machine_type.items():
            if mt != machine_type:
                continue
            if not any(a0 <= start and end <= a1 for a0, a1 in self.machine_avail[mid]):
                continue
            tr = self.machine_transit[mid]
            if any(_overlap(start - tr, end + tr, s, e) for s, e in self.machine_bookings[mid]):
                continue
            return mid
        return None

    # ---- booking ------------------------------------------------------------
    def book(self, bsid, start, end, day, night, crews, machines, station=None, routes=0):
        self.section_bookings[bsid].append((start, end))
        self.span_bookings[self.net.span_of(bsid)].append((start, end, bsid))
        cor = self.net.edge(bsid)["corridor_id"]
        if cor:
            self.corridor_blocks[cor] += 1
        for cid in crews:
            self.crew_bookings[cid].append((start, end, day, night))
        for mid in machines:
            self.machine_bookings[mid].append((start, end))
        if station and routes:
            self.station_bookings[station].append((start, end, routes))


SEV_RANK = {"IMDT": 0, "critical": 0, "1": 1, "major": 2, "2": 2, "3": 3, "minor": 3}


class BaselinePlanner:
    """Independent per-department planning, first come first served."""

    def __init__(self, net=None, week_start=None, windows=None, seed=None,
                 incidental_merge_rate=None):
        self.net = net or Network()
        self.week_start = week_start or config.WEEK_START
        self.seed = config.RANDOM_SEED if seed is None else seed
        self.merge_rate = (config.BASELINE_INCIDENTAL_MERGE_RATE
                           if incidental_merge_rate is None else incidental_merge_rate)
        ref = config.REFERENCE
        self.crews = _load_csv(os.path.join(ref, "crews.csv"))
        self.machines = _load_csv(os.path.join(ref, "machines.csv"))
        self.task_types = {r["task_type_id"]: r for r in
                           _load_csv(os.path.join(ref, "task_types.csv"))}
        self.rules = CompatibilityRules(_load_csv(os.path.join(ref, "compatibility_matrix.csv")))
        if windows is None:
            from .windows import WindowEnumerator
            windows = WindowEnumerator(self.net, week_start=self.week_start).enumerate()
        self.windows = windows

    def _urgency(self, t):
        deadline = (dt.date(*map(int, t["deadline"].split("-")))
                    if t["deadline"] else dt.date(2099, 1, 1))
        return (0 if t["safety_critical"] == "true" else 1,
                deadline, SEV_RANK.get(t["severity"], 3), -int(t["days_pending"]))

    def _duration(self, tasks):
        base = max(int(t["requested_duration_min"]) for t in tasks)
        if len(tasks) > 1:
            seq = any(self.rules.relation(a, b)[0] == "sequential"
                      for i, a in enumerate(tasks) for b in tasks[i + 1:])
            if seq:
                base = sum(int(t["requested_duration_min"]) for t in tasks)
        return int(round(base * (1 + config.COLD_START_BUFFER_FRAC)))

    def _km(self, t):
        return (float(self.net.station(t["station_code"])["km_from_origin"])
                if t["location_kind"] == "node" else float(t["start_km"]))

    def plan(self, scenario):
        rng = random.Random(self.seed)
        ledger = ResourceLedger(self.net, self.crews, self.machines, self.week_start)
        for t in scenario.tasks:
            t["_km"] = self._km(t)      # the compatibility rules need a location

        # Windows a department can ask for. Departments request corridor blocks
        # first - that is what the pattern exists for - then anything else.
        wins = []
        for w in self.windows:
            d = dt.date(*map(int, w["date"].split("-")))
            wins.append({
                "bsid": w["block_section_id"], "day": (d - self.week_start).days,
                "abs": (d - self.week_start).days * 1440 + w["start_min"],
                "dur": w["duration_min"], "type": w["window_type"], "date": d,
                "night": w["is_night"] == "true",
                "maxdep": int(w["max_departments"]) if w["max_departments"] else 3,
            })
        order = {"corridor_block": 0, "traffic_gap": 1, "requested": 2}
        wins.sort(key=lambda w: (order[w["type"]], w["abs"]))
        win_by_section = defaultdict(list)
        for w in wins:
            win_by_section[w["bsid"]].append(w)
        taken_windows = set()

        by_dept = defaultdict(list)
        for t in scenario.tasks:
            by_dept[t["department"]].append(t)
        for d in by_dept:
            by_dept[d].sort(key=self._urgency)

        # Index the backlog by where the work is. Informal coordination happens
        # when someone already going to a site mentions it to another department,
        # so the lookup has to be by location, not by scanning a priority list.
        self._at_location = defaultdict(list)
        for t in scenario.tasks:
            key = t["station_code"] if t["location_kind"] == "node" else t["block_section_id"]
            self._at_location[key].append(t)

        # Departments take turns at the head of the queue; the rotation is by
        # seed so no department is structurally advantaged across the experiment.
        depts = list(config.DEPARTMENT_ORDER)
        shift = self.seed % len(depts)
        depts = depts[shift:] + depts[:shift]

        scheduled = set()
        blocks = []
        for dept in depts:
            for task in by_dept[dept]:
                if task["task_id"] in scheduled:
                    continue
                placed = self._try_place(task, dept, wins, win_by_section, taken_windows,
                                         ledger, scenario, scheduled, rng, by_dept)
                if placed:
                    blocks.append(placed)
        return blocks

    def _try_place(self, task, dept, wins, win_by_section, taken, ledger, scenario,
                   scheduled, rng, by_dept):
        node_station = task["station_code"] if task["location_kind"] == "node" else None
        if node_station:
            sections = self.net.incident_sections(node_station)
        else:
            sections = [task["block_section_id"]]
        # Only a safety-critical deadline is a hard bar on a window. Ordinary
        # work that runs past its target date is late, not forbidden, and it
        # stays in the plan as backlog cost - which is how the coordinated
        # planner treats it too. Barring it here instead would hold current
        # practice to a stricter rule than the system it is measured against.
        deadline = (dt.date(*map(int, task["deadline"].split("-")))
                    if task["safety_critical"] == "true" and task["deadline"] else None)

        candidates = []
        for bsid in sections:
            candidates.extend(win_by_section.get(bsid, []))
        candidates.sort(key=lambda w: (order_of(w), w["abs"]))

        for w in candidates:
            if w["abs"] in taken and (w["bsid"], w["abs"]) in taken:
                continue
            if (w["bsid"], w["abs"]) in taken:
                continue
            if deadline and w["date"] > deadline:
                continue
            if task["season_restricted"] == "true" and w["date"].month in (10, 11, 12):
                continue
            if task["night_permitted"] == "false" and w["night"]:
                continue

            group = [task]
            # Informal coordination - the phone call and the corridor meeting.
            # It is a property of *opportunities*, not of blocks: the dice are
            # rolled at the moment a co-located compatible job that fits the slot
            # actually exists to be picked up. Blocks are far more numerous than
            # such opportunities, which is why the configured rate and the
            # achieved merge rate are different numbers.
            nearby = list(self._at_location.get(w["bsid"], []))
            for endpoint in self.net.span_of(w["bsid"]):
                nearby.extend(self._at_location.get(endpoint, []))
            for cand in sorted(nearby, key=self._urgency):
                if cand["task_id"] in scheduled or cand["department"] == dept:
                    continue
                if any(cand is g for g in group):
                    continue
                if not self._co_located(task, cand, w["bsid"]):
                    continue
                if any(self.rules.relation(g, cand)[0] == "incompatible" for g in group):
                    continue
                # Whoever is already going to the site takes on work that fits
                # the slot they have; they do not overrun it to be helpful, so a
                # partner that would not fit is simply never asked.
                if self._duration(group + [cand]) > w["dur"]:
                    continue
                if len({g["department"] for g in group} | {cand["department"]}) > w["maxdep"]:
                    continue
                if rng.random() < self.merge_rate:
                    group.append(cand)
                break

            dur = self._duration(group)
            if dur > w["dur"]:
                group = [task]
                dur = self._duration(group)
                if dur > w["dur"]:
                    continue
            if len({g["department"] for g in group}) > w["maxdep"]:
                group = [task]
                dur = self._duration(group)

            start, end = w["abs"], w["abs"] + dur
            if not ledger.section_free(w["bsid"], start, end):
                continue
            if not ledger.corridor_free(w["bsid"]):
                continue
            routes = sum(int(self.task_types[g["task_type_id"]]["routes_consumed"])
                         for g in group if g["location_kind"] == "node")
            station = next((g["station_code"] for g in group if g["location_kind"] == "node"), None)
            if station and not ledger.station_free(station, start, end, routes):
                continue

            crews, machines, ok = [], [], True
            for gdept in sorted({g["department"] for g in group}):
                members = [g for g in group if g["department"] == gdept]
                cid = ledger.find_crew(gdept, max(int(g["crew_required"]) for g in members),
                                       {g["task_type_id"] for g in members},
                                       start, end, w["day"], w["night"])
                if cid is None:
                    ok = False
                    break
                crews.append(cid)
            if not ok:
                continue
            for mt in sorted({g["machine_required"] for g in group if g["machine_required"] != "none"}):
                mid = ledger.find_machine(mt, start, end)
                if mid is None:
                    ok = False
                    break
                machines.append(mid)
            if not ok:
                continue

            ledger.book(w["bsid"], start, end, w["day"], w["night"], crews, machines,
                        station, routes)
            taken.add((w["bsid"], w["abs"]))
            for g in group:
                scheduled.add(g["task_id"])
            return {
                "candidate_id": "B-%s" % task["task_id"],
                "block_section_id": w["bsid"], "day": w["day"], "start_abs": start,
                "duration_min": dur, "window_type": w["type"], "size": len(group),
                "is_merged": "true" if len(group) > 1 else "false",
                "departments": ";".join(sorted({g["department"] for g in group})),
                "task_ids": ";".join(g["task_id"] for g in group),
                "access": ";".join(sorted({g["access_required"] for g in group})),
                "crews": ";".join(crews), "machines": ";".join(machines),
            }
        return None

    def _co_located(self, a, b, bsid):
        if b["location_kind"] == "edge" and b["block_section_id"] != bsid:
            return False
        if b["location_kind"] == "node":
            if b["station_code"] not in self.net.span_of(bsid):
                return False
        return abs(self._km(a) - self._km(b)) <= config.GEO_BUCKET_KM


def order_of(w):
    return {"corridor_block": 0, "traffic_gap": 1, "requested": 2}[w["type"]]


def _selfcheck():
    from .scenario import ScenarioGenerator
    net = Network()
    scen = ScenarioGenerator().generate(config.RANDOM_SEED)
    planner = BaselinePlanner(net, seed=config.RANDOM_SEED)
    blocks = planner.plan(scen)

    tasks_done = {t for b in blocks for t in b["task_ids"].split(";")}
    merged = [b for b in blocks if b["is_merged"] == "true"]
    print("Baseline planner - current practice, modelled honestly\n")
    print("scenario: %s" % scen)
    print("blocks:   %d  (%d merged, %.0f%% incidental merge rate)"
          % (len(blocks), len(merged), 100.0 * len(merged) / max(1, len(blocks))))
    print("tasks scheduled: %d of %d" % (len(tasks_done), len(scen.tasks)))
    print("line occupation: %.1f hours" % (sum(b["duration_min"] for b in blocks) / 60.0))
    by_type = defaultdict(int)
    for b in blocks:
        by_type[b["window_type"]] += 1
    print("windows used: %s  <- corridor blocks are requested first" % dict(by_type))
    print("\nthe baseline is credited with informal coordination, so its merge rate is")
    print("not zero - that is what makes the comparison credible (Blueprint 12.2).")


if __name__ == "__main__":
    _selfcheck()
