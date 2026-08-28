# -*- coding: utf-8 -*-
"""The detention estimator (Blueprint 7.3, 2.5, 8.3).

    predicted_detention = analytical_estimate + residual_model(features)

This module is the analytical core, and it does the heavy lifting: overlapping
trains, held or divertible, reroute penalties, adjacent-line caution, one-hop
cascade, single-line working. It is transparent, explainable and needs no
training data, so the optimiser can cost a block from day one. The learned
residual is layered on later through ``set_residual_model``; with no model the
residual is zero and the analytical estimate stands unchanged (the graceful
degradation Blueprint 8.3 requires).

Every cost is in weighted train-delay minutes - the unit of the objective
function, which is what turns "maximise asset availability" into arithmetic.
The five components, each computed rather than assumed:

  held           a train that cannot be diverted waits for the block to end
  reroute        a divertible train takes a parallel line, at a fixed penalty -
                 but only where a parallel line can actually take it
  cancellation   a train that can be neither held nor diverted
  caution        parallel lines run under a caution order while men are on the
                 adjacent line, charged over the WORKSITE length, not the whole
                 section (Blueprint 2.5 - the mistake that swamps the objective)
  cascade        a held train delays the trains behind it, first order only
  single_line    working the surviving edge of a double-line span is not free

Every estimate carries its decomposition, so an officer is shown named factors
with signed contributions rather than one opaque number (FR-09, NFR-04).
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict, namedtuple

from . import config

DetentionEstimate = namedtuple(
    "DetentionEstimate",
    ["weighted_minutes", "components", "trains_affected", "held", "rerouted",
     "cancelled", "cautioned", "analytical_minutes", "residual_minutes"])


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class AnalyticalDetention:
    def __init__(self, net, supply_dir=None, priority_profile=None):
        self.net = net
        self.weights = config.PRIORITY_WEIGHT_PROFILES[
            priority_profile or config.TRAIN_PRIORITY_PROFILE]
        self._residual_model = None

        supply = supply_dir or config.SUPPLY
        self._by_edge = defaultdict(list)
        with open(os.path.join(supply, "train_paths.csv"), encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                self._by_edge[r["block_section_id"]].append({
                    "entry": _to_min(r["entry_time"]),
                    "exit": _to_min(r["exit_time"]),
                    "prio": int(r["priority_class"]),
                    "divertible": r["divertible"] == "true",
                    "days": r["days_of_week"],
                    "train_no": r["train_no"],
                })
        for paths in self._by_edge.values():
            paths.sort(key=lambda p: p["entry"])

    # ---- residual hook (Blueprint 8.3) --------------------------------------
    def set_residual_model(self, fn):
        """Attach the learned residual. `fn(features) -> minutes`. Until one is
        attached the residual is zero and the analytical estimate stands."""
        self._residual_model = fn

    # ---- helpers ------------------------------------------------------------
    def _running(self, bsid, dow):
        for p in self._by_edge.get(bsid, []):
            if dow is None or p["days"][dow] == "1":
                yield p

    def _weight(self, prio):
        return self.weights.get(prio, 1.0)

    @staticmethod
    def _overlaps(entry, start, end):
        """Does a train wanting the edge at `entry` meet a block [start, end)?
        Handles the block running past midnight."""
        e = entry if entry >= start else entry + 1440
        return start <= e < end, e

    def _reroute_capacity(self, bsid, start, end, dow):
        """How many trains the parallel lines can actually absorb during this
        block. A parallel line already running its own traffic has only its free
        minutes to offer, and under single-line working it offers even less. This
        is why a night block diverts everything and a daytime one on a saturated
        section cannot - the trains it cannot divert are held, and that is where
        the cost comes from (Blueprint 7.3)."""
        duration = end - start
        slots = 0
        for adj in self.net.reroute_options(bsid):
            occupied = 0
            for p in self._running(adj, dow):
                hit, e = self._overlaps(p["entry"], start, end)
                if hit:
                    occupied += min(p["exit"] - p["entry"] if p["exit"] > p["entry"] else 1,
                                    end - e)
            free = max(0, duration - occupied)
            slots += int(free * config.SINGLE_LINE_CAPACITY_FACTOR
                         / float(config.REROUTE_HEADWAY_MIN))
        return slots

    def _caution_min_per_train(self, sectional_speed, worksite_km):
        """Minutes lost per train on a parallel line under a caution order. Roughly
        1 km at 30 km/h instead of 110 gives about 1.4 minutes (Blueprint 2.5)."""
        if sectional_speed <= 0 or worksite_km <= 0:
            return 0.0
        slow = worksite_km / float(config.CAUTION_SPEED_KMPH) * 60.0
        normal = worksite_km / float(sectional_speed) * 60.0
        return max(0.0, slow - normal)

    # ---- the estimate -------------------------------------------------------
    def estimate(self, bsid, start_min, duration_min, dow=None, worksite_km=None):
        """Weighted detention minutes for blocking `bsid` for `duration_min` from
        `start_min` (minutes past midnight). `dow` 0=Mon..6=Sun filters to trains
        that run that day; None counts every path on the edge."""
        sec = self.net.edge(bsid)
        worksite_km = config.CAUTION_WORKSITE_KM if worksite_km is None else worksite_km
        start, end = start_min, start_min + duration_min

        can_hold = self.net.line_count(bsid) > 1 or sec["line_id"] != "SINGLE"
        reroute_slots = self._reroute_capacity(bsid, start, end, dow)

        comp = defaultdict(float)
        held_trains = []
        held = rerouted = cancelled = 0

        for p in self._running(bsid, dow):
            hit, e = self._overlaps(p["entry"], start, end)
            if not hit:
                continue
            w = self._weight(p["prio"])
            if p["divertible"] and reroute_slots > 0:
                reroute_slots -= 1
                rerouted += 1
                comp["reroute"] += config.REROUTE_PENALTY_MIN * w
            elif can_hold:
                held += 1
                wait = end - e
                comp["held"] += wait * w
                held_trains.append((e, wait, w))
            else:
                cancelled += 1
                comp["cancellation"] += config.CANCELLATION_PENALTY_MIN * w

        # First-order cascade: each held train delays the train behind it, once.
        # Only the follower that would have entered while the queue is still
        # clearing is charged, and only at the decay share (Blueprint 7.3).
        if held_trains:
            for p in self._running(bsid, dow):
                hit, e = self._overlaps(p["entry"], end, end + config.CASCADE_HORIZON_MIN)
                if not hit:
                    continue
                behind = [(t_e, wait, w) for t_e, wait, w in held_trains if t_e < e]
                if behind:
                    _, wait, _ = max(behind, key=lambda t: t[0])
                    comp["cascade"] += (wait * config.CASCADE_DECAY
                                        * self._weight(p["prio"])
                                        * max(0.0, 1 - (e - end) / float(config.CASCADE_HORIZON_MIN)))

        # Adjacent-line caution: the parallel lines run under caution while men
        # and plant are on this one, charged over the worksite length only.
        cautioned = 0
        per_train = self._caution_min_per_train(sec["sectional_speed_kmph"], worksite_km)
        for adj in self.net.adjacent_lines(bsid):
            adj_sec = self.net.edge(adj)
            adj_cost = self._caution_min_per_train(adj_sec["sectional_speed_kmph"], worksite_km) \
                or per_train
            for p in self._running(adj, dow):
                hit, _ = self._overlaps(p["entry"], start, end)
                if hit:
                    cautioned += 1
                    comp["caution"] += adj_cost * self._weight(p["prio"])

        # Single-line working: on a double-line span the surviving edge carries
        # both directions at reduced capacity, so its trains lose time too.
        if self.net.line_count(bsid) == 2:
            surviving = self.net.parallel(bsid)
            loss = (1.0 - config.SINGLE_LINE_CAPACITY_FACTOR)
            for adj in surviving:
                for p in self._running(adj, dow):
                    hit, e = self._overlaps(p["entry"], start, end)
                    if hit:
                        # Time lost queueing for a single-line token, scaled by
                        # how much of the block still remains.
                        remaining = end - e
                        comp["single_line"] += remaining * loss * 0.25 * self._weight(p["prio"])

        analytical = sum(comp.values())
        residual = 0.0
        if self._residual_model is not None:
            residual = float(self._residual_model({
                "block_section_id": bsid, "start_min": start_min,
                "duration_min": duration_min, "analytical_estimate_min": analytical,
                "trains_affected": held + rerouted + cancelled,
                "daily_train_count": sec["daily_train_count"],
                "traffic_type": sec["traffic_type"], "line_count": self.net.line_count(bsid),
            }))
        return DetentionEstimate(
            weighted_minutes=round(analytical + residual, 2),
            components={k: round(v, 2) for k, v in sorted(comp.items())},
            trains_affected=held + rerouted + cancelled,
            held=held, rerouted=rerouted, cancelled=cancelled, cautioned=cautioned,
            analytical_minutes=round(analytical, 2), residual_minutes=round(residual, 2))

    def explain(self, est, top=5):
        """Named factor contributions in plain language (FR-09). At most `top`
        factors, largest first - not a statistical plot."""
        label = {
            "held": "trains held to the end of the block",
            "reroute": "trains diverted to a parallel line",
            "cancellation": "trains that could be neither held nor diverted",
            "caution": "caution order on the adjacent lines over the worksite",
            "cascade": "knock-on delay to the trains behind",
            "single_line": "reduced capacity under single-line working",
        }
        items = sorted(est.components.items(), key=lambda kv: -abs(kv[1]))[:top]
        return [(label.get(k, k), v) for k, v in items]


def _selfcheck():
    from .network import Network
    net = Network()
    det = AnalyticalDetention(net)

    print("Detention estimator - analytical core (Blueprint 7.3, 2.5)\n")
    print("Blueprint 7.3 worked comparison - a 3-hour block at Tiruvallur (TRL-AJJ-UP),")
    print("night versus day. Night should be far cheaper; that is the whole argument.\n")
    for label, start in (("night 01:30", 90), ("day 10:00", 600)):
        e = det.estimate("TRL-AJJ-UP", start, 180, dow=2)
        print("  %-12s total %7.1f weighted min | %2d trains (%d held, %d rerouted, %d cancelled), %d cautioned"
              % (label, e.weighted_minutes, e.trains_affected, e.held, e.rerouted,
                 e.cancelled, e.cautioned))
        for name, val in det.explain(e):
            print("        %-52s %8.1f" % (name, val))

    print("\nsingle line - a block on CGL-WJ-SINGLE cannot divert or hold:")
    e = det.estimate("CGL-WJ-SINGLE", 600, 180, dow=2)
    print("  total %.1f | held %d, rerouted %d, cancelled %d  <- cancellation dominates"
          % (e.weighted_minutes, e.held, e.rerouted, e.cancelled))

    print("\nsaturated suburban - MSB-MS-UP_SUB, 3h at 10:00 vs 00:30:")
    for label, start in (("00:30", 30), ("10:00", 600)):
        e = det.estimate("MSB-MS-UP_SUB", start, 180, dow=2)
        print("  %-6s total %8.1f | %d trains affected" % (label, e.weighted_minutes, e.trains_affected))

    print("\nresidual hook (Blueprint 8.3) - with no model the analytical estimate stands:")
    base = det.estimate("TRL-AJJ-UP", 90, 180, dow=2)
    det.set_residual_model(lambda f: 0.25 * f["analytical_estimate_min"])
    tuned = det.estimate("TRL-AJJ-UP", 90, 180, dow=2)
    print("  analytical %.1f -> with a +25%% residual %.1f (analytical %.1f + residual %.1f)"
          % (base.weighted_minutes, tuned.weighted_minutes,
             tuned.analytical_minutes, tuned.residual_minutes))


if __name__ == "__main__":
    _selfcheck()
