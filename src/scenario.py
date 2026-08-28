# -*- coding: utf-8 -*-
"""Scenario generation for the evaluation harness (Blueprint 12.1, 12.4).

Chennai Division cannot be run for a month with the system and a month without
it, so the claim has to come from a counterfactual: simulate current practice and
the coordinated planner **on identical inputs** and measure the difference. This
module produces those inputs.

One scenario is one plannable week: a backlog of pending tasks, re-based so their
urgency is live against that week. Re-basing matters. The corpus in tasks.csv is
a year of history whose deadlines mostly fall in the past; presented raw, most
safety-critical work would be unschedulable for both planners and the experiment
would measure nothing. Re-basing preserves each task's urgency *structure* - how
long it has been pending, how much runway remains to its deadline - while making
the week live.

Thirty seeds give thirty independent weeks. Both planners receive the identical
object, which is the whole point: the difference between them is then the
measured claim and nothing else.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import random
from collections import Counter

from . import config


def _load(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Scenario:
    """One plannable week, identical for every planner that receives it."""

    def __init__(self, seed, week_start, tasks):
        self.seed = seed
        self.week_start = week_start
        self.tasks = tasks

    def summary(self):
        dep = Counter(t["department"] for t in self.tasks)
        return {
            "seed": self.seed,
            "week_start": self.week_start.isoformat(),
            "tasks": len(self.tasks),
            "by_department": dict(sorted(dep.items())),
            "safety_critical": sum(1 for t in self.tasks if t["safety_critical"] == "true"),
            "with_deadline_in_week": sum(
                1 for t in self.tasks if t["deadline"]
                and self.week_start <= dt.date(*map(int, t["deadline"].split("-")))
                <= self.week_start + dt.timedelta(days=6)),
            "locations": len({t["block_section_id"] or t["station_code"] for t in self.tasks}),
        }

    def __repr__(self):
        s = self.summary()
        return ("Scenario(seed=%d, week=%s, %d tasks, %d safety-critical, %d locations)"
                % (s["seed"], s["week_start"], s["tasks"], s["safety_critical"], s["locations"]))


class ScenarioGenerator:
    def __init__(self, demand_dir=None, week_start=None, tasks_per_week=None):
        demand = demand_dir or config.DEMAND
        self.corpus = _load(os.path.join(demand, "tasks.csv"))
        self.week_start = week_start or config.WEEK_START
        self.n = tasks_per_week or config.EVAL_TASKS_PER_WEEK
        # Cancelled work is gone and in-progress work is already committed to a
        # block; neither belongs in a backlog waiting to be planned.
        self.pool = [t for t in self.corpus if t["status"] not in ("cancelled", "in_progress")]

    def generate(self, seed):
        rng = random.Random(seed)
        chosen = rng.sample(self.pool, min(self.n, len(self.pool)))
        tasks = []
        for src in chosen:
            t = dict(src)
            raised_orig = dt.date(*map(int, t["raised_date"].split("-")))
            days_pending = int(t["days_pending"])
            lead = None
            if t["deadline"]:
                lead = max(1, (dt.date(*map(int, t["deadline"].split("-"))) - raised_orig).days)

            # A backlog is mostly live work. Drawing days_pending straight from
            # the corpus leaves most safety-critical tasks already past their
            # deadline, which would make the constraint they drive inert and the
            # experiment measure nothing. So where a task has run out of runway,
            # it is usually re-drawn to a point where runway remains - and
            # sometimes not, because a genuinely overdue minority is real and the
            # escalation path (US-10) has to be exercised too.
            if lead is not None and days_pending >= lead and rng.random() < 0.85:
                days_pending = rng.randint(0, lead - 1)
                t["days_pending"] = str(days_pending)

            raised = self.week_start - dt.timedelta(days=days_pending)
            t["raised_date"] = raised.isoformat()
            if lead is not None:
                t["deadline"] = (raised + dt.timedelta(days=lead)).isoformat()
            t["status"] = "pending"
            tasks.append(t)
        return Scenario(seed, self.week_start, tasks)

    def generate_many(self, seeds=None):
        n = seeds or config.EVAL_SEEDS
        return [self.generate(config.RANDOM_SEED + i) for i in range(n)]


def _selfcheck():
    gen = ScenarioGenerator()
    print("Scenario generation - independent weeks on identical inputs\n")
    print("corpus %d tasks; plannable pool %d (cancelled and in-progress excluded)"
          % (len(gen.corpus), len(gen.pool)))
    scenarios = gen.generate_many(5)
    for s in scenarios:
        d = s.summary()
        print("  seed %-6d %3d tasks  %s  safety %2d (%d due inside the week)  %d locations"
              % (d["seed"], d["tasks"], d["by_department"], d["safety_critical"],
                 d["with_deadline_in_week"], d["locations"]))

    a = gen.generate(config.RANDOM_SEED)
    b = gen.generate(config.RANDOM_SEED)
    same = [t["task_id"] for t in a.tasks] == [t["task_id"] for t in b.tasks]
    c = gen.generate(config.RANDOM_SEED + 1)
    differ = {t["task_id"] for t in a.tasks} != {t["task_id"] for t in c.tasks}
    print("\nreproducible: same seed gives the identical week - %s" % same)
    print("independent:  a different seed gives a different week - %s" % differ)

    overdue = sum(1 for t in a.tasks if t["safety_critical"] == "true" and t["deadline"]
                  and dt.date(*map(int, t["deadline"].split("-"))) < a.week_start)
    print("\nre-basing check on seed %d: %d safety-critical tasks already overdue "
          "before the week starts" % (a.seed, overdue))
    print("  (the raw corpus had 19 of 28 overdue - re-basing makes the week live "
          "so the deadline constraint is genuinely exercised)")


if __name__ == "__main__":
    _selfcheck()
