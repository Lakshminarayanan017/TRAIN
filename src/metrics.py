# -*- coding: utf-8 -*-
"""Plan metrics (Blueprint 12.3).

Both planners emit the same block shape, so every metric here is computed the
same way for both. That is deliberate: a comparison is only worth something if
the measuring instrument does not know which planner it is looking at.

    Primary    line occupation hours   - the headline claim, aggregated
               weighted detention min  - the operational cost
               merge rate              - blocks carrying more than one department
    Secondary  tasks completed         - guards against gaming: a planner that
                                         schedules nothing has perfect detention
               backlog at horizon end  - is the queue shrinking?
               safety deadline breaches- must be zero, or no other number counts
               mean days to attend     - is urgent work genuinely going first?
    Tertiary   work per line-minute    - how much work each line-minute buys
               new access requested    - windows taken outside the corridor pattern
               night share, corridor mix

Nothing here rewards a planner for doing less. Line occupation falls when work is
merged, not when work is skipped, and tasks-completed is reported beside it so the
two cannot be traded against each other unnoticed.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from . import config

SEV_ORDER = ["IMDT", "critical", "1", "2", "major", "3", "minor"]


def compute(blocks, scenario, net, detention=None):
    """Every metric for one plan on one scenario."""
    tasks = {t["task_id"]: t for t in scenario.tasks}
    scheduled = set()
    for b in blocks:
        scheduled.update(t for t in b["task_ids"].split(";") if t)
    scheduled &= set(tasks)

    occupation_min = sum(int(b["duration_min"]) for b in blocks)
    merged = [b for b in blocks if b["is_merged"] == "true"]
    multi_dept = [b for b in blocks if ";" in b["departments"]]

    # Weighted detention, recomputed from the same analytical model for both
    # planners so neither is credited with its own optimism.
    detention_min = 0.0
    if detention is not None:
        for b in blocks:
            dow = (scenario.week_start + dt.timedelta(days=int(b["day"]))).weekday()
            detention_min += detention.estimate(
                b["block_section_id"], int(b["start_abs"]) % 1440,
                int(b["duration_min"]), dow).weighted_minutes

    # Safety: a breach is a safety-critical task scheduled past its deadline, or
    # one whose deadline falls inside the horizon and which was left unscheduled.
    horizon_end = scenario.week_start + dt.timedelta(days=6)
    placed_day = {}
    for b in blocks:
        day = scenario.week_start + dt.timedelta(days=int(b["day"]))
        for t in b["task_ids"].split(";"):
            placed_day[t] = day
    breaches, unfitted_safety, safety_total = 0, 0, 0
    for tid, t in tasks.items():
        if t["safety_critical"] != "true":
            continue
        safety_total += 1
        deadline = dt.date(*map(int, t["deadline"].split("-"))) if t["deadline"] else None
        if tid in scheduled:
            if deadline and placed_day.get(tid) and placed_day[tid] > deadline:
                breaches += 1
        elif deadline and deadline <= horizon_end:
            unfitted_safety += 1

    # Is urgent work genuinely going first?
    days_to_attend = defaultdict(list)
    for tid in scheduled:
        t = tasks[tid]
        if tid in placed_day:
            days_to_attend[t["severity"]].append((placed_day[tid] - scenario.week_start).days)
    mean_attend = {s: round(sum(v) / len(v), 1)
                   for s, v in days_to_attend.items() if v}

    worked_min = 0
    for b in blocks:
        for t in b["task_ids"].split(";"):
            if t in tasks:
                worked_min += int(tasks[t]["requested_duration_min"])

    by_type = Counter(b["window_type"] for b in blocks)
    by_corridor = Counter(net.edge(b["block_section_id"])["corridor_id"] for b in blocks)
    dept_tasks = Counter(tasks[t]["department"] for t in scheduled)

    return {
        # primary
        "line_occupation_hours": round(occupation_min / 60.0, 1),
        "weighted_detention_min": round(detention_min, 1),
        "merge_rate_pct": round(100.0 * len(multi_dept) / max(1, len(blocks)), 1),
        # secondary
        "blocks": len(blocks),
        "tasks_scheduled": len(scheduled),
        "tasks_offered": len(tasks),
        "backlog_remaining": len(tasks) - len(scheduled),
        "safety_total": safety_total,
        "safety_deadline_breaches": breaches,
        "safety_unfitted_in_horizon": unfitted_safety,
        "mean_days_to_attend": mean_attend,
        "tasks_by_department": dict(sorted(dept_tasks.items())),
        # tertiary
        # Work-minutes packed into each line-minute of occupation. It exceeds
        # 100% when parallel work shares one possession, which is exactly the
        # gain merging exists to produce - it is not a utilisation bug.
        "work_per_line_minute_pct": round(100.0 * worked_min / max(1, occupation_min), 1),
        "merged_blocks": len(merged),
        "new_access_requested": by_type.get("requested", 0),
        "windows_by_type": dict(by_type),
        "blocks_by_corridor": dict(sorted(by_corridor.items())),
        "occupation_per_task_min": round(occupation_min / max(1, len(scheduled)), 1),
    }


def aggregate(runs):
    """Mean and spread across seeds. A single simulated week proves nothing, so
    every headline figure is reported with its standard deviation."""
    if not runs:
        return {}
    numeric = [k for k, v in runs[0].items() if isinstance(v, (int, float))]
    out = {}
    for k in numeric:
        vals = [r[k] for r in runs]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
        out[k] = {"mean": round(mean, 2), "sd": round(var ** 0.5, 2),
                  "min": round(min(vals), 2), "max": round(max(vals), 2)}
    return out


def compare(baseline_runs, coordinated_runs):
    """Paired comparison: the same seed ran through both planners, so the
    difference is per-week and the spread is of the difference itself, not of two
    independent samples."""
    a, b = aggregate(baseline_runs), aggregate(coordinated_runs)
    out = {}
    for k in a:
        if k not in b:
            continue
        deltas = [c[k] - d[k] for c, d in zip(coordinated_runs, baseline_runs)]
        mean_d = sum(deltas) / len(deltas)
        var = sum((x - mean_d) ** 2 for x in deltas) / max(1, len(deltas) - 1)
        sd = var ** 0.5
        base = a[k]["mean"]
        out[k] = {
            "baseline": a[k]["mean"], "coordinated": b[k]["mean"],
            "delta": round(mean_d, 2), "delta_sd": round(sd, 2),
            "pct": round(100.0 * mean_d / base, 1) if base else None,
            # Wins counts the weeks in which the coordinated planner was better on
            # this metric; direction is applied by the reporter, not here.
            "weeks_better": sum(1 for x in deltas if x < 0),
            "weeks_worse": sum(1 for x in deltas if x > 0),
            "n": len(deltas),
        }
    return out
