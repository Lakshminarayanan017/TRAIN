# -*- coding: utf-8 -*-
"""Detention estimator - analytical core (Blueprint 8.3).

    predicted_detention = analytical_estimate + residual_model(features)

This is the analytical component: it does the heavy lifting and needs no training
data, so the optimiser can cost a block from day one (the cold-start of model 3).
The learned residual is layered on later; with no model the residual is zero and
this estimate stands (graceful degradation, Blueprint 8.3).

For a proposed block on one edge, it overlaps the block window against the actual
train paths on that edge and sums a real per-train cost (Blueprint 7.3): a
divertible train takes the fixed reroute penalty; a held train waits to the block
end with a one-hop cascade; a non-divertible train on a single line that cannot be
held is cancelled. Every minute is weighted by train priority (7.4).
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict

from . import config


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class AnalyticalDetention:
    def __init__(self, net, supply_dir=None):
        self.net = net
        supply = supply_dir or config.SUPPLY
        self._by_edge = defaultdict(list)
        path = os.path.join(supply, "train_paths.csv")
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                self._by_edge[r["block_section_id"]].append(
                    (_to_min(r["entry_time"]), int(r["priority_class"]),
                     r["divertible"] == "true", r["days_of_week"]))

    def estimate(self, bsid, start_min, duration_min, dow=None):
        """Weighted detention minutes for blocking `bsid` from start for duration.
        `dow` (0=Mon..6=Sun) filters to trains that run that day; None counts all.
        Returns (weighted_minutes, trains_affected, rerouted, held, cancelled)."""
        sec = self.net.edge(bsid)
        single = sec["line_id"] == "SINGLE"
        start = start_min
        end = start_min + duration_min

        weighted = 0.0
        affected = reroute = held = cancelled = 0
        for entry, prio, divertible, days in self._by_edge.get(bsid, []):
            if dow is not None and days[dow] != "1":
                continue
            e = entry if entry >= start else entry + 1440
            if not (start <= e <= end):
                continue
            affected += 1
            w = config.PRIORITY_WEIGHT[prio]
            if divertible:
                reroute += 1
                weighted += config.REROUTE_PENALTY_MIN * w
            else:
                wait = end - e
                if single and wait > duration_min * 0.9:
                    cancelled += 1
                    weighted += duration_min * config.CANCELLATION_FACTOR * w
                else:
                    held += 1
                    weighted += wait * config.CASCADE_FACTOR * w
        return weighted, affected, reroute, held, cancelled
