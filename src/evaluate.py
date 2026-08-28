# -*- coding: utf-8 -*-
"""The evaluation harness (Blueprint section 12, FR-33, FR-34).

Chennai Division cannot be run for a month with the system and a month without
it, so the claim comes from a counterfactual: both planners receive **identical**
scenarios and the difference between them is the measurement.

    python -m src.evaluate                 # full run, 30 seeds
    python -m src.evaluate --seeds 5       # quick run
    python -m src.evaluate --ablations     # add the component ablations

The assertion this produces is deliberately not "Chennai Division will save N
hours". It is: under identical conditions, with identical constraints, identical
crews and identical windows, coordinated planning dominates independent planning
- and here is by how much, with what spread, and why.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict

from . import config, metrics
from .baseline import BaselinePlanner
from .detention import AnalyticalDetention
from .network import Network
from .optimizer import WeeklyOptimizer
from .scenario import ScenarioGenerator
from .windows import WindowEnumerator


class Harness:
    def __init__(self, seeds=None, time_limit=None, tasks_per_week=None, quiet=False):
        self.net = Network()
        self.detention = AnalyticalDetention(self.net)
        self.gen = ScenarioGenerator(tasks_per_week=tasks_per_week)
        self.seeds = seeds or config.EVAL_SEEDS
        self.time_limit = time_limit or config.EVAL_SOLVE_TIME_LIMIT_S
        self.quiet = quiet
        # Windows depend only on the timetable and the week, not on the backlog,
        # so they are enumerated once and handed to both planners - another way
        # of guaranteeing the two see the same world.
        self.windows = WindowEnumerator(self.net, week_start=config.WEEK_START).enumerate()

    def _log(self, msg):
        if not self.quiet:
            print(msg)
            sys.stdout.flush()

    def run_baseline(self, scenario):
        planner = BaselinePlanner(self.net, week_start=scenario.week_start,
                                  windows=self.windows, seed=scenario.seed)
        return planner.plan(scenario)

    def run_coordinated(self, scenario, **flags):
        opt = WeeklyOptimizer(self.net, scenario=scenario, windows=self.windows, **flags)
        res = opt.solve(time_limit_s=self.time_limit)
        violations = opt.validate(res)
        return res["blocks"], res, violations

    def run(self, ablations=False):
        scenarios = [self.gen.generate(config.RANDOM_SEED + i) for i in range(self.seeds)]
        arms = {"baseline": {}, "coordinated": {}}
        if ablations:
            arms["no_merging"] = {"enable_merging": False}
            arms["no_detention_weighting"] = {"enable_detention": False}
            arms["no_window_waste"] = {"enable_waste": False}

        results = {name: [] for name in arms}
        all_violations = []
        started = time.time()

        for i, scen in enumerate(scenarios, 1):
            self._log("  week %2d/%d (seed %d)..." % (i, len(scenarios), scen.seed))
            blocks = self.run_baseline(scen)
            results["baseline"].append(
                metrics.compute(blocks, scen, self.net, self.detention))

            for name, flags in arms.items():
                if name == "baseline":
                    continue
                blocks, res, viol = self.run_coordinated(scen, **flags)
                if viol:
                    all_violations.append((scen.seed, name, viol))
                results[name].append(
                    metrics.compute(blocks, scen, self.net, self.detention))

        self.elapsed = time.time() - started
        self.violations = all_violations
        self.results = results
        self.scenarios = scenarios
        return results


# --------------------------------------------------------------------- report
LOWER_IS_BETTER = {"line_occupation_hours", "weighted_detention_min",
                   "backlog_remaining", "safety_deadline_breaches",
                   "safety_unfitted_in_horizon", "occupation_per_task_min",
                   "new_access_requested"}


def _fmt_delta(key, cmp_row):
    better = cmp_row["delta"] < 0 if key in LOWER_IS_BETTER else cmp_row["delta"] > 0
    mark = "better" if better else ("same" if abs(cmp_row["delta"]) < 1e-9 else "worse")
    return "%+8.1f (%+6.1f%%)  %s" % (cmp_row["delta"], cmp_row["pct"] or 0.0, mark)


def report(harness):
    res = harness.results
    n = len(res["baseline"])
    cmp = metrics.compare(res["baseline"], res["coordinated"])
    base = metrics.aggregate(res["baseline"])
    coord = metrics.aggregate(res["coordinated"])

    print("\n" + "=" * 78)
    print("EVALUATION - coordinated planning against current practice")
    print("=" * 78)
    print("%d independent weeks, identical scenarios to both planners, %ds solve "
          "ceiling\nsolved in %.0fs" % (n, harness.time_limit, harness.elapsed))

    print("\nPRIMARY")
    for key, label in (("line_occupation_hours", "line occupation (hours)"),
                       ("weighted_detention_min", "weighted detention (min)"),
                       ("merge_rate_pct", "merge rate (%)")):
        c = cmp[key]
        print("  %-26s baseline %8.1f  coordinated %8.1f   %s"
              % (label, c["baseline"], c["coordinated"], _fmt_delta(key, c)))
        print("  %-26s   spread sd %.1f / %.1f, coordinated better in %d of %d weeks"
              % ("", base[key]["sd"], coord[key]["sd"],
                 c["weeks_better"] if key in LOWER_IS_BETTER else c["weeks_worse"], n))

    print("\nSECONDARY - guards against gaming")
    for key, label in (("tasks_scheduled", "tasks completed"),
                       ("backlog_remaining", "backlog at horizon end"),
                       ("safety_deadline_breaches", "safety deadline breaches"),
                       ("safety_unfitted_in_horizon", "safety unfitted in horizon"),
                       ("blocks", "blocks issued")):
        c = cmp[key]
        print("  %-26s baseline %8.1f  coordinated %8.1f   %s"
              % (label, c["baseline"], c["coordinated"], _fmt_delta(key, c)))

    print("\nTERTIARY")
    for key, label in (("work_per_line_minute_pct", "work per line-minute (%)"),
                       ("occupation_per_task_min", "line-minutes per task done"),
                       ("new_access_requested", "new access requested")):
        c = cmp[key]
        print("  %-26s baseline %8.1f  coordinated %8.1f   %s"
              % (label, c["baseline"], c["coordinated"], _fmt_delta(key, c)))

    breaches = coord["safety_deadline_breaches"]["max"]
    print("\nHARD CONSTRAINT CHECK")
    print("  safety deadline breaches, coordinated: max %g across all weeks - %s"
          % (breaches, "PASS, zero always" if breaches == 0 else "FAIL"))
    print("  solution validation: %s"
          % ("PASS - no plan violated a hard constraint" if not harness.violations
             else "%d VIOLATION(S) %s" % (len(harness.violations), harness.violations[:2])))

    others = [k for k in res if k not in ("baseline", "coordinated")]
    if others:
        print("\nABLATIONS - each component disabled in turn (FR-34)")
        for name in others:
            a = metrics.compare(res["coordinated"], res[name])
            print("  %-24s occupation %+7.1f h   detention %+9.1f min   tasks %+6.1f   merge %+5.1f%%"
                  % (name,
                     a["line_occupation_hours"]["delta"],
                     a["weighted_detention_min"]["delta"],
                     a["tasks_scheduled"]["delta"],
                     a["merge_rate_pct"]["delta"]))
        print("  (deltas are the ablated arm relative to the full coordinated planner:")
        print("   a positive occupation or detention means removing that component made it worse)")

    print("\nHONESTY STATEMENT (Blueprint 12.5)")
    print("  Results are on synthetic data with parameters chosen by the team. The")
    print("  baseline is a model of current practice, not measured current practice,")
    print("  and the compatibility matrix is unvalidated by railway officers. Absolute")
    print("  numbers are illustrative; the relative comparison is the claim.")
    occ = cmp["line_occupation_hours"]
    det = cmp["weighted_detention_min"]
    print("\n  Under identical conditions, coordinated planning changed line occupation")
    print("  by %.1f hours per week (%.1f%%) and weighted detention by %.0f minutes"
          % (occ["delta"], occ["pct"] or 0, det["delta"]))
    print("  (%.0f%%), while completing %+.1f tasks, across %d seeded weeks."
          % (det["pct"] or 0, cmp["tasks_scheduled"]["delta"], n))
    print("=" * 78)


def write_results(harness, path=None):
    path = path or os.path.join(config.DERIVED, "evaluation.json")
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    payload = {
        "seeds": len(harness.results["baseline"]),
        "solve_time_limit_s": harness.time_limit,
        "elapsed_s": round(harness.elapsed, 1),
        "per_arm_aggregate": {k: metrics.aggregate(v) for k, v in harness.results.items()},
        "comparison_baseline_vs_coordinated":
            metrics.compare(harness.results["baseline"], harness.results["coordinated"]),
        "violations": harness.violations,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)

    csv_path = os.path.join(os.path.dirname(path), "evaluation_runs.csv")
    rows = []
    for arm, runs in harness.results.items():
        for scen, r in zip(harness.scenarios, runs):
            row = {"arm": arm, "seed": scen.seed}
            row.update({k: v for k, v in r.items() if isinstance(v, (int, float))})
            rows.append(row)
    if rows:
        cols = ["arm", "seed"] + [k for k in rows[0] if k not in ("arm", "seed")]
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return path, csv_path


def main():
    ap = argparse.ArgumentParser(description="Coordinated vs independent planning")
    ap.add_argument("--seeds", type=int, default=config.EVAL_SEEDS)
    ap.add_argument("--time-limit", type=int, default=config.EVAL_SOLVE_TIME_LIMIT_S)
    ap.add_argument("--tasks", type=int, default=config.EVAL_TASKS_PER_WEEK)
    ap.add_argument("--ablations", action="store_true")
    args = ap.parse_args()

    print("Evaluation harness - %d seeded weeks, %ds per solve%s"
          % (args.seeds, args.time_limit, ", with ablations" if args.ablations else ""))
    h = Harness(seeds=args.seeds, time_limit=args.time_limit, tasks_per_week=args.tasks)
    h.run(ablations=args.ablations)
    report(h)
    j, c = write_results(h)
    print("\nwritten -> %s\n            %s"
          % (os.path.relpath(j, config.ROOT), os.path.relpath(c, config.ROOT)))


if __name__ == "__main__":
    main()
