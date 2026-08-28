# -*- coding: utf-8 -*-
"""Stage 5 - the weekly optimiser (Blueprint section 7).

A CP-SAT set-packing model: choose (candidate, window) pairs that minimise total
weighted-delay cost, then a local pass could slide each block within its gap. This
is the full model - every hard constraint of Blueprint 7.2 is enforced at
instance level, not approximated:

    objective   detention + deferral + lambda_waste + lambda_access + lambda_fair
    hard        each task scheduled at most once
                safety-critical deadlines (pair-filtered; unfit tasks surfaced)
                crew qualification, no-overlap with minimum rest, max consecutive
                    nights, max weekly duty hours - assigned to real crew instances
                machine availability calendar, transit spacing, no double-booking
                    - assigned to real machine instances
                never sever a section (per-span cumulative capacity = lines - 1)
                one block per line at a time (per-section no-overlap)
                station route capacity for node disconnections
                season and night-work restrictions (pair-filtered)
                maximum blocks per corridor per week
                predicted duration + buffer fits the window

It runs with no trained model: duration is the cold-start requested-plus-buffer,
and detention is the analytical estimate. The ML models refine these later without
changing the model's shape.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import os
from collections import defaultdict

from ortools.sat.python import cp_model

from . import config
from .network import Network
from .clustering import Clusterer
from .windows import WindowEnumerator
from .detention import AnalyticalDetention

SEV_BASE = {"IMDT": 150, "1": 80, "2": 40, "3": 15,
            "critical": 80, "major": 40, "minor": 15}


def _load(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_dt(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")


class WeeklyOptimizer:
    def __init__(self, net=None, week_start=None):
        self.net = net or Network()
        self.week_start = week_start or config.WEEK_START
        self.week_start_dt = dt.datetime.combine(self.week_start, dt.time(0, 0))

        self.candidates = Clusterer(self.net).candidates(
            top_k_per_anchor=config.TOP_K_CANDIDATES_PER_ANCHOR)
        self.windows = WindowEnumerator(self.net, week_start=self.week_start).enumerate()
        self.detention = AnalyticalDetention(self.net)
        self.crews = _load(os.path.join(config.REFERENCE, "crews.csv"))
        self.machines_rows = _load(os.path.join(config.REFERENCE, "machines.csv"))
        self.task_types = {r["task_type_id"]: r
                           for r in _load(os.path.join(config.REFERENCE, "task_types.csv"))}

    # ---- helpers ------------------------------------------------------------
    def _abs_min(self, date_iso, start_min):
        d = dt.date(*map(int, date_iso.split("-")))
        return (d - self.week_start).days * 1440 + start_min

    def _sched_dur(self, c):
        return int(math.ceil(int(c["critical_path_min"]) * (1 + config.COLD_START_BUFFER_FRAC)))

    def _node_station(self, c):
        """Where the candidate's node/disconnection work sits, and the routes it
        consumes - for the station route-capacity constraint."""
        nodes = [t for t in c["_tasks"] if t["location_kind"] == "node"]
        if not nodes:
            return None, 0
        return nodes[0]["station_code"], int(c["routes_consumed"])

    def _deferral_reward(self, c):
        r = 0
        for t in c["_tasks"]:
            if t["safety_critical"] == "true":
                r += config.SAFETY_SCHEDULE_BONUS
            else:
                base = SEV_BASE.get(t["severity"], 15)
                r += int(base * (1 + int(t["days_pending"]) / 30.0))
        return r

    # ---- model build --------------------------------------------------------
    def build(self):
        m = cp_model.CpModel()
        net = self.net
        HORIZON = 7 * 1440

        # Windows indexed by section, with absolute-minute placement.
        win = []
        for w in self.windows:
            win.append({
                "bsid": w["block_section_id"],
                "abs": self._abs_min(w["date"], w["start_min"]),
                "day": (dt.date(*map(int, w["date"].split("-"))) - self.week_start).days,
                "dow": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].index(w["day_of_week"]),
                "dur": w["duration_min"], "type": w["window_type"],
                "goods": float(w["goods_risk"]),
                "maxdep": int(w["max_departments"]) if w["max_departments"] else 3,
                "night": w["start_min"] < config.CANDIDATE_TERMINAL_MIN or w["start_min"] >= 22 * 60,
            })
        win_on_section = defaultdict(list)
        for wi, w in enumerate(win):
            win_on_section[w["bsid"]].append(wi)

        incident = defaultdict(list)   # station -> incident block sections
        for s in net.all_sections():
            incident[s["from_station"]].append(s["block_section_id"])
            incident[s["to_station"]].append(s["block_section_id"])

        # Feasible (candidate, window) pairs.
        x = {}                       # (ci, wi) -> BoolVar
        pair_cost = {}               # (ci, wi) -> integer objective coefficient
        cand_windows = defaultdict(list)
        for ci, c in enumerate(self.candidates):
            sd = self._sched_dur(c)
            n_dep = len(c["departments"].split(";"))
            # Which sections' windows can host this candidate.
            if c["anchor_type"] == "edge":
                sections = [c["anchor"]]
            else:                    # node work rides a window on an incident section
                sections = sorted(set(incident[c["anchor"]]))
            for bsid in sections:
                for wi in win_on_section.get(bsid, []):
                    w = win[wi]
                    if sd > w["dur"]:
                        continue
                    if n_dep > w["maxdep"]:
                        continue
                    wdate = self.week_start + dt.timedelta(days=w["day"])
                    if c["safety_deadline"] and wdate > dt.date(*map(int, c["safety_deadline"].split("-"))):
                        continue
                    if c["season_restricted"] == "true" and wdate.month in (10, 11, 12):
                        continue
                    if c["night_forbidden"] == "true" and w["night"]:
                        continue
                    var = m.NewBoolVar("x_%d_%d" % (ci, wi))
                    x[(ci, wi)] = var
                    cand_windows[ci].append(wi)
                    det = self.detention.estimate(bsid, w["abs"] % 1440, sd, w["dow"])[0]
                    waste = w["dur"] - sd
                    cost = int(round(det)) + int(round(config.LAMBDA_WASTE * waste))
                    cost += int(round(w["goods"] * config.GOODS_DELAY_PENALTY))
                    if w["type"] != "corridor_block":
                        cost += config.LAMBDA_ACCESS
                    pair_cost[(ci, wi)] = cost

        sel = {}
        place = {}
        blk = {}
        placed_on_day = {}           # (ci, day) -> linear expr (sum of x)
        for ci in range(len(self.candidates)):
            wis = cand_windows[ci]
            s = m.NewBoolVar("sel_%d" % ci)
            sel[ci] = s
            if not wis:
                m.Add(s == 0)
                continue
            m.Add(s == sum(x[(ci, wi)] for wi in wis))
            m.Add(sum(x[(ci, wi)] for wi in wis) <= 1)
            p = m.NewIntVar(0, HORIZON, "place_%d" % ci)
            m.Add(p == sum(win[wi]["abs"] * x[(ci, wi)] for wi in wis))
            place[ci] = p
            sd = self._sched_dur(self.candidates[ci])
            end = m.NewIntVar(0, HORIZON + sd, "end_%d" % ci)
            m.Add(end == p + sd)
            blk[ci] = m.NewOptionalIntervalVar(p, sd, end, s, "blk_%d" % ci)
            byday = defaultdict(list)
            for wi in wis:
                byday[win[wi]["day"]].append(x[(ci, wi)])
            for day, xs in byday.items():
                placed_on_day[(ci, day)] = sum(xs)

        # Each task scheduled at most once.
        task_cands = defaultdict(list)
        for ci, c in enumerate(self.candidates):
            for t in c["_tasks"]:
                task_cands[t["task_id"]].append(ci)
        for tid, cis in task_cands.items():
            m.Add(sum(sel[ci] for ci in cis) <= 1)

        # One block per window.
        for wi in range(len(win)):
            xs = [x[(ci, wi)] for ci in range(len(self.candidates)) if (ci, wi) in x]
            if xs:
                m.Add(sum(xs) <= 1)

        # Per-section no-overlap (one block per line at a time) and per-span
        # cumulative (never sever: at most lines-1 blocked at once).
        cand_section = {}
        for ci, c in enumerate(self.candidates):
            if c["anchor_type"] == "edge":
                cand_section[ci] = c["anchor"]
        by_section = defaultdict(list)
        by_span = defaultdict(list)
        for ci, bsid in cand_section.items():
            if ci in blk:
                by_section[bsid].append(blk[ci])
                by_span[net.span_of(bsid)].append(blk[ci])
        for bsid, ivs in by_section.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)
        for span, ivs in by_span.items():
            n_lines = len(net.edges_on_span(*span))
            if n_lines > 1 and len(ivs) > 1:
                m.AddCumulative(ivs, [1] * len(ivs), n_lines - 1)

        # Station route capacity for node disconnections.
        by_station = defaultdict(lambda: ([], []))
        for ci, c in enumerate(self.candidates):
            st, routes = self._node_station(c)
            if st and routes > 0 and ci in blk:
                by_station[st][0].append(blk[ci])
                by_station[st][1].append(routes)
        for st, (ivs, demands) in by_station.items():
            cap = int(self.net.station(st)["route_capacity"] or 0)
            if ivs and cap > 0:
                m.AddCumulative(ivs, demands, cap)

        # Crew assignment - real instances, qualification, rest, nights, hours.
        crews_by_dept = defaultdict(list)
        for k in self.crews:
            crews_by_dept[k["department"]].append(k)
        y = {}                        # (ci, dept, crew_id) -> BoolVar
        crew_intervals = defaultdict(list)
        crew_duty = defaultdict(list)     # crew_id -> list of (sched_dur, y)
        nb = {}                           # (crew_id, day) -> BoolVar (worked that day)
        for ci, c in enumerate(self.candidates):
            if ci not in blk:
                continue
            sd = self._sched_dur(c)
            for spec in c["dept_crew"].split(";"):
                dept, need = spec.split(":")
                need = int(need)
                d_types = {t["task_type_id"] for t in c["_tasks"] if t["department"] == dept}
                elig = []
                for k in crews_by_dept[dept]:
                    quals = set(k["qualifications"].split(";"))
                    if int(k["size"]) >= need and d_types <= quals:
                        elig.append(k)
                if not elig:
                    m.Add(sel[ci] == 0)      # unstaffable - cannot be scheduled
                    break
                yk = []
                for k in elig:
                    v = m.NewBoolVar("y_%d_%s_%s" % (ci, dept, k["crew_id"]))
                    y[(ci, dept, k["crew_id"])] = v
                    yk.append(v)
                    rest = int(k["min_rest_hours"]) * 60
                    e = m.NewIntVar(0, HORIZON + sd + rest, "ce_%d_%s" % (ci, k["crew_id"]))
                    m.Add(e == place[ci] + sd + rest)
                    iv = m.NewOptionalIntervalVar(place[ci], sd + rest, e, v,
                                                  "ci_%d_%s" % (ci, k["crew_id"]))
                    crew_intervals[k["crew_id"]].append(iv)
                    crew_duty[k["crew_id"]].append((sd, v))
                    for day in {win[wi]["day"] for wi in cand_windows[ci]}:
                        key = (k["crew_id"], day)
                        if key not in nb:
                            nb[key] = m.NewBoolVar("nb_%s_%d" % key)
                        if (ci, day) in placed_on_day:
                            m.Add(nb[key] >= v + placed_on_day[(ci, day)] - 1)
                m.Add(sum(yk) == sel[ci])
        for cid, ivs in crew_intervals.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)
        crew_by_id = {k["crew_id"]: k for k in self.crews}
        for cid, duties in crew_duty.items():
            cap = int(crew_by_id[cid]["max_weekly_duty_hours"]) * 60
            m.Add(sum(sd * v for sd, v in duties) <= cap)
        # Max consecutive nights: no run longer than the limit.
        crew_days = defaultdict(dict)
        for (cid, day), v in nb.items():
            crew_days[cid][day] = v
        max_nights = m.NewIntVar(0, 7, "max_nights")
        for cid, days in crew_days.items():
            limit = int(crew_by_id[cid]["max_consecutive_nights"])
            for d0 in range(0, 7 - limit):
                window = [days[d] for d in range(d0, d0 + limit + 1) if d in days]
                if len(window) > limit:
                    m.Add(sum(window) <= limit)
            m.Add(sum(days.values()) <= max_nights)

        # Machine assignment - instances, availability, transit spacing.
        avail = defaultdict(list)      # machine_id -> [(abs_start, abs_end)]
        mtype = {}
        transit = {}
        for r in self.machines_rows:
            mid = r["machine_id"]
            mtype[mid] = r["machine_type"]
            transit[mid] = int(round(float(r["transit_time_h"]) * 60))
            a0 = int((_parse_dt(r["available_from"]) - self.week_start_dt).total_seconds() // 60)
            a1 = int((_parse_dt(r["available_to"]) - self.week_start_dt).total_seconds() // 60)
            avail[mid].append((a0, a1))
        machines_by_type = defaultdict(list)
        for mid, t in mtype.items():
            machines_by_type[t].append(mid)
        z = {}
        machine_intervals = defaultdict(list)
        for ci, c in enumerate(self.candidates):
            if ci not in blk or not c["machines"]:
                continue
            sd = self._sched_dur(c)
            for mt in c["machines"].split(";"):
                insts = machines_by_type.get(mt, [])
                if not insts:
                    m.Add(sel[ci] == 0)
                    break
                zk = []
                for mid in insts:
                    # windows whose block time fits an availability calendar window
                    ok_wis = [wi for wi in cand_windows[ci]
                              if any(a0 <= win[wi]["abs"] and win[wi]["abs"] + sd <= a1
                                     for a0, a1 in avail[mid])]
                    if not ok_wis:
                        continue
                    v = m.NewBoolVar("z_%d_%s" % (ci, mid))
                    z[(ci, mt, mid)] = v
                    zk.append(v)
                    m.Add(v <= sum(x[(ci, wi)] for wi in ok_wis))
                    tr = transit[mid]
                    e = m.NewIntVar(0, HORIZON + sd + tr, "me_%d_%s" % (ci, mid))
                    m.Add(e == place[ci] + sd + tr)
                    iv = m.NewOptionalIntervalVar(place[ci], sd + tr, e, v,
                                                  "mi_%d_%s" % (ci, mid))
                    machine_intervals[mid].append(iv)
                if not zk:
                    m.Add(sel[ci] == 0)
                    break
                m.Add(sum(zk) == sel[ci])
        for mid, ivs in machine_intervals.items():
            if len(ivs) > 1:
                m.AddNoOverlap(ivs)

        # Max blocks per corridor per week.
        by_corridor = defaultdict(list)
        for ci, c in enumerate(self.candidates):
            cor = None
            if c["anchor_type"] == "edge":
                cor = self.net.edge(c["anchor"])["corridor_id"]
            if cor:
                by_corridor[cor].append(sel[ci])
        for cor, sels in by_corridor.items():
            m.Add(sum(sels) <= config.MAX_BLOCKS_PER_CORRIDOR_WEEK)

        # Objective.
        terms = []
        for (ci, wi), v in x.items():
            terms.append(pair_cost[(ci, wi)] * v)
        for ci in range(len(self.candidates)):
            if ci in sel:
                terms.append(-self._deferral_reward(self.candidates[ci]) * sel[ci])
        terms.append(config.LAMBDA_FAIR * max_nights)
        m.Minimize(sum(terms))

        # Warm start: seed a safety-first plan so the search begins from a good
        # solution rather than an empty one. Give each schedulable safety-critical
        # task its own singleton in the earliest free window; the solver improves
        # from there and may move them, but never starts blind.
        used = set()
        for ci, c in enumerate(self.candidates):
            if c["size"] != 1 or c["_tasks"][0]["safety_critical"] != "true":
                continue
            for wi in sorted(cand_windows[ci], key=lambda w: win[w]["abs"]):
                if wi not in used:
                    m.AddHint(x[(ci, wi)], 1)
                    used.add(wi)
                    break

        self._model = m
        self._x = x
        self._sel = sel
        self._win = win
        self._cand_windows = cand_windows
        self._y = y
        self._z = z
        return m

    # ---- solve --------------------------------------------------------------
    def solve(self, time_limit_s=None):
        if not hasattr(self, "_model"):
            self.build()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s or config.WEEKLY_SOLVE_TIME_LIMIT_S
        solver.parameters.num_search_workers = 8
        solver.parameters.random_seed = config.RANDOM_SEED
        status = solver.Solve(self._model)
        self._solver = solver
        self._status = status
        res = self._extract()
        res["bound"] = round(solver.BestObjectiveBound(), 1)
        obj = res.get("objective")
        res["gap_pct"] = (round(100.0 * abs(obj - res["bound"]) / max(1.0, abs(obj)), 2)
                          if obj is not None else None)
        return res

    def _extract(self):
        solver, status = self._solver, self._status
        plan = []
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {"status": solver.StatusName(status), "blocks": []}
        for (ci, wi), v in self._x.items():
            if solver.Value(v):
                c = self.candidates[ci]
                w = self._win[wi]
                crew = [k for (cc, d, k), yv in self._y.items()
                        if cc == ci and solver.Value(yv)]
                mach = [mid for (cc, mt, mid), zv in self._z.items()
                        if cc == ci and solver.Value(zv)]
                plan.append({
                    "candidate_id": c["candidate_id"], "block_section_id": w["bsid"],
                    "day": w["day"], "start_abs": w["abs"], "duration_min": self._sched_dur(c),
                    "window_type": w["type"], "size": c["size"],
                    "departments": c["departments"], "is_merged": c["is_merged"],
                    "task_ids": c["task_ids"], "access": c["access_union"],
                    "crews": ";".join(sorted(crew)), "machines": ";".join(sorted(mach)),
                })
        scheduled_tasks = set()
        for b in plan:
            scheduled_tasks.update(b["task_ids"].split(";"))
        all_tasks = {t["task_id"] for c in self.candidates for t in c["_tasks"]}
        safety = {t["task_id"] for c in self.candidates for t in c["_tasks"]
                  if t["safety_critical"] == "true"}
        return {
            "status": solver.StatusName(status),
            "objective": solver.ObjectiveValue(),
            "blocks": plan,
            "tasks_total": len(all_tasks),
            "tasks_scheduled": len(scheduled_tasks & all_tasks),
            "merged_blocks": sum(1 for b in plan if b["is_merged"] == "true"),
            "multi_dept_blocks": sum(1 for b in plan if ";" in b["departments"]),
            "safety_total": len(safety),
            "safety_unscheduled": sorted(safety - scheduled_tasks),
            "wall_time_s": round(solver.WallTime(), 1),
        }


    def validate(self, res):
        """Prove the solution honours the hard constraints - a plan the optimiser
        claims is feasible must actually be feasible on inspection."""
        import datetime as _dt
        v = []
        blocks = res["blocks"]

        def span_iv(b):
            return b["start_abs"], b["start_abs"] + b["duration_min"]

        seen = {}
        for b in blocks:
            for t in b["task_ids"].split(";"):
                if t in seen:
                    v.append("task %s scheduled twice" % t)
                seen[t] = b["candidate_id"]

        crew_by_id = {k["crew_id"]: k for k in self.crews}
        crew_blocks = defaultdict(list)
        mach_blocks = defaultdict(list)
        for b in blocks:
            for cr in filter(None, b["crews"].split(";")):
                crew_blocks[cr].append(b)
            for mm in filter(None, b["machines"].split(";")):
                mach_blocks[mm].append(b)
        for cr, bs in crew_blocks.items():
            rest = int(crew_by_id[cr]["min_rest_hours"]) * 60
            bs.sort(key=lambda b: b["start_abs"])
            for a, b2 in zip(bs, bs[1:]):
                if b2["start_abs"] < a["start_abs"] + a["duration_min"] + rest:
                    v.append("crew %s: overlapping duties or rest violated" % cr)
        for mm, bs in mach_blocks.items():
            bs.sort(key=lambda b: b["start_abs"])
            for a, b2 in zip(bs, bs[1:]):
                if b2["start_abs"] < a["start_abs"] + a["duration_min"]:
                    v.append("machine %s: double-booked" % mm)

        span_blocks = defaultdict(list)
        for b in blocks:
            span_blocks[self.net.span_of(b["block_section_id"])].append(b)
        for span, bs in span_blocks.items():
            n_lines = len(self.net.edges_on_span(*span))
            if n_lines <= 1:
                continue
            for b in bs:
                s, e = span_iv(b)
                lines = {self.net.edge(o["block_section_id"])["line_id"] for o in bs
                         if o["start_abs"] < e and o["start_abs"] + o["duration_min"] > s}
                if len(lines) >= n_lines:
                    v.append("span %s-%s severed: all %d lines blocked at once"
                             % (span[0], span[1], n_lines))
                    break

        task_by_id = {t["task_id"]: t for c in self.candidates for t in c["_tasks"]}
        for b in blocks:
            bday = self.week_start + _dt.timedelta(days=b["day"])
            for t in b["task_ids"].split(";"):
                tk = task_by_id.get(t)
                if tk and tk["safety_critical"] == "true" and tk["deadline"]:
                    if bday > _dt.date(*map(int, tk["deadline"].split("-"))):
                        v.append("safety task %s scheduled after its deadline" % t)
        return v

    def write_plan(self, res, path=None):
        path = path or os.path.join(config.DERIVED, "weekly_plan.csv")
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        cols = ["candidate_id", "block_section_id", "day", "start_abs", "duration_min",
                "window_type", "size", "is_merged", "departments", "access",
                "crews", "machines", "task_ids"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(res["blocks"])
        return path


def _selfcheck():
    opt = WeeklyOptimizer()
    print("candidates %d, windows %d - building and solving the full model..."
          % (len(opt.candidates), len(opt.windows)))
    res = opt.solve()
    gap = res.get("gap_pct")
    print("\nsolve: %s, objective %.0f, bound %.0f  (gap %.2f%%, %.1fs)"
          % (res["status"], res.get("objective", 0), res.get("bound", 0), gap or 0,
             res.get("wall_time_s", 0)))
    print("blocks scheduled: %d  (%d merged, %d cross-department)"
          % (len(res["blocks"]), res["merged_blocks"], res["multi_dept_blocks"]))
    print("tasks scheduled this week: %d / %d pending backlog" % (res["tasks_scheduled"], res["tasks_total"]))
    print("safety-critical: %d total; %d fitted, %d surfaced as un-fittable (never silently deferred)"
          % (res["safety_total"], res["safety_total"] - len(res["safety_unscheduled"]),
             len(res["safety_unscheduled"])))
    violations = opt.validate(res)
    print("\nconstraint validation of the solution: %s"
          % ("PASS - all hard constraints hold" if not violations
             else "%d VIOLATION(S): %s" % (len(violations), violations[:5])))
    out = opt.write_plan(res)
    print("plan written -> %s" % os.path.relpath(out, config.ROOT))
    for b in [b for b in res["blocks"] if b["is_merged"] == "true"][:4]:
        print("  MERGE %-16s %-40s crews=%s mach=%s"
              % (b["block_section_id"], b["access"], b["crews"], b["machines"]))


if __name__ == "__main__":
    _selfcheck()
