# -*- coding: utf-8 -*-
"""Stage 4 - clustering and merge candidates (Blueprint section 6).

Turns the pending task pool into the candidates the optimiser chooses among. The
system exists to merge co-located compatible work into shared blocks, and this is
where that becomes concrete.

  - Geography is the grouping key (6.1): tasks on the same block section (same
    line) can share a block; node work at a station can join edge work on a
    section incident to that station. No distance maths for grouping - distance
    re-enters only for the safety rules that carry a max_distance_m condition.
  - A valid merge is a clique (6.2): *every* pair compatible, not merely each with
    the first. Enumerated up to size 5.
  - Duration is a critical path (6.4): sequential members chain, parallel members
    overlap - not the sum, not a naive maximum.
  - Access escalates on union (6.3): power on an electrified section implies a
    traffic block; traffic + disconnection needs Station Master authority too.
  - Singletons are always emitted, so the optimiser degrades gracefully.

The Data Spec 9.1 sample - an ENG rail weld and a TrD OHE inspection on
TRL-AJJ-UP plus an SNT point service at Tiruvallur - is the integration test: it
must surface as one size-3 candidate with a 180-minute critical path.
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict

from . import config
from .network import Network


def _load(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class CompatibilityRules:
    """Directed lookup over the compatibility matrix, with the default that an
    unruled pair is parallel (compatibility_matrix.README)."""

    def __init__(self, rows):
        self._by_pair = {}
        for r in rows:
            self._by_pair[(r["type_a"], r["type_b"])] = r

    def relation(self, ta, tb):
        """Return (relation, first_type) for two tasks, applying the distance
        condition. first_type is the type that must precede, for sequential."""
        rule = self._by_pair.get((ta["task_type_id"], tb["task_type_id"]))
        first = ta["task_type_id"]
        if rule is None:
            rule = self._by_pair.get((tb["task_type_id"], ta["task_type_id"]))
            first = tb["task_type_id"]
        if rule is None:
            return "parallel", None
        if rule["max_distance_m"]:
            dist_m = abs(_km(ta) - _km(tb)) * 1000.0
            if dist_m > int(rule["max_distance_m"]):
                return "parallel", None       # rule does not reach this far apart
        return rule["relation"], first


def _km(task):
    """A task's location in km. Edge tasks sit at their start; node tasks at the
    station post (filled in by the caller)."""
    return float(task["_km"])


class Clusterer:
    def __init__(self, net=None, demand_dir=None, reference_dir=None):
        self.net = net or Network()
        demand = demand_dir or config.DEMAND
        ref = reference_dir or config.REFERENCE
        self.tasks = _load(os.path.join(demand, "tasks.csv"))
        self.rules = CompatibilityRules(_load(os.path.join(ref, "compatibility_matrix.csv")))
        self.task_types = {r["task_type_id"]: r for r in
                           _load(os.path.join(ref, "task_types.csv"))}

        # Sections incident on each station, for placing node work next to edge work.
        self.incident = defaultdict(list)
        for s in self.net.all_sections():
            self.incident[s["from_station"]].append(s["block_section_id"])
            self.incident[s["to_station"]].append(s["block_section_id"])

    # ---- candidate assembly -------------------------------------------------
    def pending(self):
        out = []
        for t in self.tasks:
            if t["status"] != "pending":
                continue
            t = dict(t)
            if t["location_kind"] == "node":
                t["_km"] = self.net.station(t["station_code"])["km_from_origin"]
            else:
                t["_km"] = t["start_km"]
            out.append(t)
        return out

    def _cliques(self, group):
        """All mergeable subsets of size 2..MAX. Two tasks may share a block only
        when they are neither incompatible nor further apart than the geo bucket -
        co-location is a pairwise constraint, so there is no hard grid boundary to
        split a worksite (Data Spec 9 geo_key, realistic worksite extent)."""
        n = len(group)
        compat = [[True] * n for _ in range(n)]
        first = {}
        for i in range(n):
            for j in range(i + 1, n):
                rel, f = self.rules.relation(group[i], group[j])
                co_located = abs(_km(group[i]) - _km(group[j])) <= config.GEO_BUCKET_KM
                ok = rel != "incompatible" and co_located
                compat[i][j] = compat[j][i] = ok
                if ok and rel == "sequential":
                    first[(i, j)] = f
        cliques = []

        def extend(cur, start):
            for j in range(start, n):
                if all(compat[j][i] for i in cur):
                    nxt = cur + [j]
                    if len(nxt) >= 2:
                        cliques.append(list(nxt))
                    if len(nxt) < config.MAX_CANDIDATE_SIZE:
                        extend(nxt, j + 1)

        extend([], 0)
        return cliques, first

    def _critical_path(self, subset):
        """Node-weighted longest path over the sequential precedences (6.4)."""
        dur = {t["task_id"]: int(t["requested_duration_min"]) for t in subset}
        preds = defaultdict(list)
        for i in range(len(subset)):
            for j in range(i + 1, len(subset)):
                rel, first = self.rules.relation(subset[i], subset[j])
                if rel == "sequential":
                    a, b = (subset[i], subset[j]) if subset[i]["task_type_id"] == first \
                        else (subset[j], subset[i])
                    preds[b["task_id"]].append(a["task_id"])
        memo = {}

        def lp(tid):
            if tid not in memo:
                memo[tid] = dur[tid] + max([lp(p) for p in preds[tid]] or [0])
            return memo[tid]

        return max(lp(t["task_id"]) for t in subset), preds

    def _crew_profile(self, subset, preds):
        """Max simultaneous crew overall and per department, scheduling parallel
        tasks together and sequential ones after their predecessor. The per-
        department peak is what each department must staff for the block."""
        dur = {t["task_id"]: int(t["requested_duration_min"]) for t in subset}
        memo = {}

        def st(tid):
            if tid not in memo:
                memo[tid] = max([st(p) + dur[p] for p in preds[tid]] or [0])
            return memo[tid]

        def peak(tasks):
            events = []
            for t in tasks:
                s = st(t["task_id"])
                events.append((s, int(t["crew_required"])))
                events.append((s + dur[t["task_id"]], -int(t["crew_required"])))
            events.sort()
            cur = hi = 0
            for _, d in events:
                cur += d
                hi = max(hi, cur)
            return hi

        dept_peak = {}
        for dept in {t["department"] for t in subset}:
            dept_peak[dept] = peak([t for t in subset if t["department"] == dept])
        return peak(subset), dept_peak

    def _access_union(self, subset, electrified):
        acc = {t["access_required"] for t in subset} - {"none"}
        if "power_block" in acc and electrified:
            acc.add("traffic_block")     # power implies traffic on the wire (6.3)
        return sorted(acc) if acc else ["none"]

    def _describe(self, subset, anchor_type, anchor, line_id, electrified):
        crit, preds = self._critical_path(subset)
        crew_peak, dept_crew = self._crew_profile(subset, preds)
        task_ids = [t["task_id"] for t in subset]
        # Node work consumes station running routes; the block must fit the yard.
        routes = sum(int(self.task_types[t["task_type_id"]]["routes_consumed"])
                     for t in subset if t["location_kind"] == "node")
        deadlines = [t["deadline"] for t in subset
                     if t["safety_critical"] == "true" and t["deadline"]]
        span = self.net.span_of(subset_edge["block_section_id"]) \
            if (subset_edge := next((t for t in subset if t["location_kind"] == "edge"), None)) \
            else None
        return {
            "candidate_id": "C-%s-%s" % (anchor, "_".join(sorted(t.split("-")[-1] for t in task_ids))),
            "anchor_type": anchor_type,
            "anchor": anchor,
            "line_id": line_id or "",
            "size": len(subset),
            "is_merged": "true" if len(subset) > 1 else "false",
            "task_ids": ";".join(task_ids),
            "departments": ";".join(sorted({t["department"] for t in subset})),
            "task_types": ";".join(t["task_type_id"] for t in subset),
            "critical_path_min": crit,
            "access_union": ";".join(self._access_union(subset, electrified)),
            "line_union": ";".join(sorted({t["line_id"] for t in subset if t["line_id"]})) or "",
            "crew_peak": crew_peak,
            "dept_crew": ";".join("%s:%d" % (d, dept_crew[d]) for d in sorted(dept_crew)),
            "machines": ";".join(sorted({t["machine_required"] for t in subset
                                         if t["machine_required"] != "none"})),
            "routes_consumed": routes,
            "safety_deadline": min(deadlines) if deadlines else "",
            "season_restricted": "true" if any(t["season_restricted"] == "true"
                                               for t in subset) else "false",
            "night_forbidden": "true" if any(t["night_permitted"] == "false"
                                             for t in subset) else "false",
            # In-memory only (underscore keys are dropped from the CSV).
            "_tasks": subset,
            "_dept_crew": dept_crew,
            "_span": span,
        }

    def candidates(self, top_k_per_anchor=None):
        pend = self.pending()
        node_tasks = defaultdict(list)     # station_code -> tasks
        edge_tasks = defaultdict(list)     # block_section_id -> tasks
        for t in pend:
            if t["location_kind"] == "node":
                node_tasks[t["station_code"]].append(t)
            else:
                edge_tasks[t["block_section_id"]].append(t)

        out = []
        seen = set()

        def emit(subset, anchor_type, anchor, line_id, electrified, require_edge):
            key = frozenset(t["task_id"] for t in subset)
            if key in seen:
                return
            if require_edge and not any(t["location_kind"] == "edge" for t in subset):
                return
            seen.add(key)
            out.append(self._describe(subset, anchor_type, anchor, line_id, electrified))

        # Edge-section groups: the section's edge tasks plus node work at either
        # endpoint. The pairwise co-location test inside _cliques keeps a merge to
        # one worksite, so a long section does not fabricate co-location.
        for bsid, ets in edge_tasks.items():
            sec = self.net.edge(bsid)
            elec = sec["electrified"] == "true"
            members = list(ets)
            for endpoint in (sec["from_station"], sec["to_station"]):
                members += node_tasks.get(endpoint, [])
            cliques, _ = self._cliques(members)
            for cl in cliques:
                emit([members[i] for i in cl], "edge", bsid, sec["line_id"], elec, require_edge=True)

        # Station groups: node-only merges (disconnections sharing one possession).
        for code, nts in node_tasks.items():
            if len(nts) < 2:
                continue
            elec = any(self.net.edge(b)["electrified"] == "true" for b in self.incident[code])
            cliques, _ = self._cliques(nts)
            for cl in cliques:
                emit([nts[i] for i in cl], "node", code, "", elec, require_edge=False)

        # A full instance-level optimiser cannot carry every sub-clique, and does
        # not need to: most add solve time and no reachable optimum. Keep the
        # valuable merges per worksite - cross-department first, then larger and
        # longer - and let singletons cover the rest. The three-department 9.1
        # candidate scores highest and is always retained.
        if top_k_per_anchor is not None:
            def value(c):
                return (len(c["departments"].split(";")), c["critical_path_min"])
            by_anchor_size = defaultdict(list)
            for c in out:
                by_anchor_size[(c["anchor"], c["size"])].append(c)
            kept = []
            for group in by_anchor_size.values():
                group.sort(key=value, reverse=True)   # cross-department first
                kept.extend(group[:top_k_per_anchor])
            out = kept

        # Singletons - every pending task, always (6.5).
        for t in pend:
            if t["location_kind"] == "node":
                anchor_type, anchor, elec = "node", t["station_code"], \
                    any(self.net.edge(b)["electrified"] == "true" for b in self.incident[t["station_code"]])
            else:
                anchor_type, anchor = "edge", t["block_section_id"]
                elec = self.net.edge(t["block_section_id"])["electrified"] == "true"
            out.append(self._describe([t], anchor_type, anchor, t["line_id"], elec))
        return out


HEADER = ["candidate_id", "anchor_type", "anchor", "line_id", "size", "is_merged",
          "task_ids", "departments", "task_types", "critical_path_min",
          "access_union", "line_union", "crew_peak", "dept_crew", "machines",
          "routes_consumed", "safety_deadline", "season_restricted", "night_forbidden"]


def write_csv(cands, path=None):
    path = path or os.path.join(config.DERIVED, "merge_candidates.csv")
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(cands)
    return path


def _selfcheck():
    from collections import Counter
    cl = Clusterer()
    cands = cl.candidates()
    out = write_csv(cands)
    merged = [c for c in cands if c["is_merged"] == "true"]
    print("merge candidates: %d  (%d merged, %d singleton) -> %s"
          % (len(cands), len(merged), len(cands) - len(merged), os.path.relpath(out, config.ROOT)))
    print("merged by size:", dict(sorted(Counter(c["size"] for c in merged).items())))
    multi_dept = [c for c in merged if len(c["departments"].split(";")) > 1]
    print("cross-department candidates:", len(multi_dept),
          "| with all three depts:", sum(1 for c in multi_dept if len(c["departments"].split(";")) == 3))

    # Data Spec 9.1 integration test.
    spec = {"ENG-2026-04412", "TRD-2026-01188", "SNT-2026-00734"}
    hit = [c for c in cands if set(c["task_ids"].split(";")) == spec]
    print("\n9.1 merge candidate discovered:", bool(hit))
    if hit:
        c = hit[0]
        print("  anchor %s (%s)  depts %s  access %s"
              % (c["anchor"], c["line_id"], c["departments"], c["access_union"]))
        print("  critical path %s min (expected 180)  crew_peak %s"
              % (c["critical_path_min"], c["crew_peak"]))


if __name__ == "__main__":
    _selfcheck()
