# -*- coding: utf-8 -*-
"""The network model (Blueprint section 2).

Loads stations.csv and block_sections.csv into a NetworkX MultiDiGraph - chosen
for its native support of parallel edges keyed by line - and wraps it in a
read-only ``Network`` accessor that every later stage queries. Built once.

Three levels (Blueprint 2.1): station = node, block section = edge, corridor =
named path. Two kinds of adjacency, deliberately kept as separate relations
(Blueprint 2.3), because conflating them either loses reroute options or
double-counts delay:

    longitudinal - the next block section along the route  -> cascade delay
    lateral      - the parallel edges of the same span     -> reroute, never-sever

The accessors here are the vocabulary the cost model and the optimiser speak in:
``line_count`` (decisive in the cost model), ``reroute_options`` (can traffic
actually go round?), ``downstream``/``upstream`` (cascade), ``severing_spans``
(the FR-21 line-union check) and ``capacity_after_block`` (single-line working is
not free, Blueprint 2.5).

The graph validates itself on construction. A reference layer that does not hold
together is a defect to surface at load, not a mystery to debug three stages
later.
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict

import networkx as nx

from . import config


def _load(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class NetworkError(ValueError):
    """The reference layer does not describe a usable railway."""


class Network:
    """Read-only view over the block-planning graph."""

    def __init__(self, reference_dir=None, strict=True):
        ref = reference_dir or config.REFERENCE
        self._stations = {r["station_code"]: r
                          for r in _load(os.path.join(ref, "stations.csv"))}
        rows = _load(os.path.join(ref, "block_sections.csv"))
        self._sections = {}

        g = nx.MultiDiGraph()
        for code, s in self._stations.items():
            g.add_node(code, **s)
        for r in rows:
            r["length_km"] = round(float(r["end_km"]) - float(r["start_km"]), 3)
            r["start_km"] = float(r["start_km"])
            r["end_km"] = float(r["end_km"])
            r["daily_train_count"] = int(r["daily_train_count"])
            r["sectional_speed_kmph"] = int(r["sectional_speed_kmph"])
            r["is_electrified"] = r["electrified"] == "true"
            r["is_bidirectional"] = r["bidirectional_capable"] == "true"
            r["is_monsoon_sensitive"] = r["monsoon_sensitive"] == "true"
            r["parallel_edges"] = [e for e in r["parallel_edges"].split(";") if e]
            r["next_sections"] = [e for e in r["next_sections"].split(";") if e]
            self._sections[r["block_section_id"]] = r
            g.add_edge(r["from_station"], r["to_station"], key=r["line_id"], **r)
        self.g = g

        # A span is a (from, to) pair; its edges are the parallel lines over it.
        self._span_edges = defaultdict(list)
        for bsid, s in self._sections.items():
            self._span_edges[(s["from_station"], s["to_station"])].append(bsid)
        self._span_edges = dict(self._span_edges)

        # Sections incident on each station, and reverse longitudinal adjacency.
        self._incident = defaultdict(list)
        self._predecessors = defaultdict(list)
        for bsid, s in self._sections.items():
            self._incident[s["from_station"]].append(bsid)
            self._incident[s["to_station"]].append(bsid)
            for nxt in s["next_sections"]:
                self._predecessors[nxt].append(bsid)

        self.warnings = self.validate()
        if strict and any(w.startswith("ERROR") for w in self.warnings):
            raise NetworkError("; ".join(w for w in self.warnings if w.startswith("ERROR")))

    # ---- validation ---------------------------------------------------------
    def validate(self):
        """Referential and structural checks, run at load. Returns a list of
        findings; ERROR-prefixed ones are fatal under strict loading."""
        out = []
        for bsid, s in self._sections.items():
            for field in ("from_station", "to_station"):
                if s[field] not in self._stations:
                    out.append("ERROR %s: %s references unknown station %s"
                               % (bsid, field, s[field]))
                elif self._stations[s[field]]["is_block_station"] != "true":
                    out.append("ERROR %s: %s=%s is not a block station"
                               % (bsid, field, s[field]))
            if s["length_km"] <= 0:
                out.append("ERROR %s: non-positive length %.2f km" % (bsid, s["length_km"]))
            for ref in s["parallel_edges"] + s["next_sections"]:
                if ref not in self._sections:
                    out.append("ERROR %s: dangling reference %s" % (bsid, ref))
            if s["line_id"] == "SINGLE" and s["parallel_edges"]:
                out.append("ERROR %s: a single line cannot have parallel edges" % bsid)
        # Lateral adjacency is an equivalence relation over a span.
        for bsid, s in self._sections.items():
            for ref in s["parallel_edges"]:
                if ref in self._sections and bsid not in self._sections[ref]["parallel_edges"]:
                    out.append("ERROR %s: parallel_edges not symmetric with %s" % (bsid, ref))
        # Every edge of a span must agree on its geography.
        for span, edges in self._span_edges.items():
            for field in ("start_km", "end_km", "corridor_id"):
                if len({self._sections[e][field] for e in edges}) > 1:
                    out.append("ERROR %s-%s: edges disagree on %s" % (span[0], span[1], field))
        # A node of degree > 2 that is not flagged a junction is a modelling slip;
        # the reverse is expected at the pilot boundary and only noted.
        for code, station in self._stations.items():
            deg = len({self.span_of(b) for b in self._incident[code]})
            if deg > 2 and station["is_junction"] != "true":
                out.append("ERROR %s: modelled degree %d but is_junction=false" % (code, deg))
            elif deg <= 2 and station["is_junction"] == "true":
                out.append("note %s: is_junction=true, modelled degree %d - other arms "
                           "lie outside the pilot corridors" % (code, deg))
        if not nx.is_weakly_connected(self.g.subgraph(
                [n for n in self.g if self._incident[n]])):
            out.append("note the modelled graph is not weakly connected - expected "
                       "where a corridor joins only at a junction")
        return out

    # ---- lookups ------------------------------------------------------------
    def edge(self, bsid):
        return self._sections[bsid]

    def station(self, code):
        return self._stations[code]

    def all_sections(self):
        return list(self._sections.values())

    def section_ids(self):
        return list(self._sections)

    def span_of(self, bsid):
        s = self._sections[bsid]
        return (s["from_station"], s["to_station"])

    def edges_on_span(self, from_station, to_station):
        return list(self._span_edges.get((from_station, to_station))
                    or self._span_edges.get((to_station, from_station))
                    or [])

    def line_count(self, bsid):
        """How many separately blockable lines the span carries. Decisive in the
        cost model: blocking one of four costs little, blocking the only one
        severs the route."""
        return len(self.edges_on_span(*self.span_of(bsid)))

    def parallel(self, bsid):
        """Lateral group: the other lines of the same span."""
        return [e for e in self.edges_on_span(*self.span_of(bsid)) if e != bsid]

    def incident_sections(self, station_code):
        return list(self._incident[station_code])

    def sections_by_corridor(self, corridor_id):
        return [s for s in self._sections.values() if s["corridor_id"] == corridor_id]

    def corridors(self):
        return sorted({s["corridor_id"] for s in self._sections.values()})

    # ---- adjacency ----------------------------------------------------------
    def downstream(self, bsid, hops=1):
        """Longitudinal successors within `hops` - where a held train piles up."""
        seen, frontier = set(), [bsid]
        for _ in range(hops):
            nxt = []
            for b in frontier:
                for s in self._sections[b]["next_sections"]:
                    if s not in seen and s != bsid:
                        seen.add(s)
                        nxt.append(s)
            frontier = nxt
        return sorted(seen)

    def upstream(self, bsid, hops=1):
        """Longitudinal predecessors - where the trains behind are queued."""
        seen, frontier = set(), [bsid]
        for _ in range(hops):
            nxt = []
            for b in frontier:
                for s in self._predecessors.get(b, []):
                    if s not in seen and s != bsid:
                        seen.add(s)
                        nxt.append(s)
            frontier = nxt
        return sorted(seen)

    def reroute_options(self, bsid):
        """Parallel lines traffic could actually be diverted onto while `bsid` is
        blocked: same span, not itself blocked, and able to work bidirectionally.
        A dedicated unidirectional suburban pair is not a reroute option, which is
        why a divertible train is not automatically divertible here."""
        return [e for e in self.parallel(bsid) if self._sections[e]["is_bidirectional"]]

    def adjacent_lines(self, bsid):
        """Lines that receive a caution order while this one is worked
        (Blueprint 2.5) - the parallel lines of the same span."""
        return self.parallel(bsid)

    def capacity_after_block(self, bsid):
        """Fraction of the span's capacity surviving while `bsid` is blocked.
        Single-line working over the remaining edge is not costless."""
        n = self.line_count(bsid)
        if n <= 1:
            return 0.0                       # blocking the only line severs it
        surviving = (n - 1) / float(n)
        if n == 2:
            return surviving * config.SINGLE_LINE_CAPACITY_FACTOR
        return surviving

    # ---- feasibility --------------------------------------------------------
    def severing_spans(self, blocked_bsids):
        """Spans where blocking this set takes every line at once - the
        line-union infeasibility FR-21 forbids. Blocking a genuinely single-line
        section is not a sever: that is how the line is worked."""
        blocked = set(blocked_bsids)
        out = []
        for span, edges in self._span_edges.items():
            if len(edges) > 1 and set(edges) <= blocked:
                out.append(span)
        return out

    def would_sever(self, blocked_bsids):
        return bool(self.severing_spans(blocked_bsids))

    def path_between(self, from_station, to_station):
        """A station-to-station route as an ordered list of spans, or [] if the
        modelled graph does not connect them."""
        try:
            nodes = nx.shortest_path(self.g.to_undirected(as_view=True),
                                     from_station, to_station)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        return list(zip(nodes, nodes[1:]))

    def summary(self):
        spans = len(self._span_edges)
        by_lines = defaultdict(int)
        for span, edges in self._span_edges.items():
            by_lines[len(edges)] += 1
        return {
            "stations": len(self._stations),
            "sections": len(self._sections),
            "spans": spans,
            "corridors": len(self.corridors()),
            "spans_by_line_count": dict(sorted(by_lines.items())),
            "electrified_sections": sum(1 for s in self._sections.values() if s["is_electrified"]),
            "route_km": round(sum(self._sections[e[0]]["length_km"]
                                  for e in self._span_edges.values()), 1),
        }

    def __repr__(self):
        s = self.summary()
        return ("Network(%d stations, %d sections over %d spans, %d corridors, %.0f route-km)"
                % (s["stations"], s["sections"], s["spans"], s["corridors"], s["route_km"]))


def load(reference_dir=None, strict=True):
    return Network(reference_dir, strict=strict)


def _selfcheck():
    net = load()
    print(net)
    s = net.summary()
    print("spans by line count: %s | electrified sections: %d"
          % (s["spans_by_line_count"], s["electrified_sections"]))

    errs = [w for w in net.warnings if w.startswith("ERROR")]
    notes = [w for w in net.warnings if not w.startswith("ERROR")]
    print("validation: %s%s"
          % ("PASS - the reference layer holds together" if not errs
             else "%d ERROR(S): %s" % (len(errs), errs[:3]),
             "  (%d note(s))" % len(notes) if notes else ""))

    # The Blueprint 2.2 worked example: one span, four separately blockable lines.
    up = "TRL-AJJ-UP"
    print("\nBlueprint 2.2 worked example - %s" % up)
    print("  span carries %d lines; parallel: %s" % (net.line_count(up), sorted(net.parallel(up))))
    print("  reroute options (bidirectional only): %s" % sorted(net.reroute_options(up)))
    print("  capacity surviving a block here: %.2f" % net.capacity_after_block(up))
    print("  downstream 1 hop: %s | upstream 1 hop: %s"
          % (net.downstream(up), net.upstream(up)))
    print("  blocking UP alone severs? %s | blocking all four? %s"
          % (net.would_sever([up]), net.would_sever(net.edges_on_span("TRL", "AJJ"))))

    sub = "MSB-MS-UP_SUB"
    dropped = sorted(set(net.parallel(sub)) - set(net.reroute_options(sub)))
    print("\nsuburban pair - %s" % sub)
    print("  parallel: %d | genuine reroute options: %s"
          % (len(net.parallel(sub)), sorted(net.reroute_options(sub))))
    print("  ruled out as unidirectional: %s  <- a dedicated suburban line is not a reroute"
          % dropped)

    single = "CGL-WJ-SINGLE"
    print("\nsingle line - %s" % single)
    print("  line_count %d | capacity after a block %.2f | severs a multi-line span? %s"
          % (net.line_count(single), net.capacity_after_block(single), net.would_sever([single])))

    print("\ncorridors:")
    for cor in net.corridors():
        secs = net.sections_by_corridor(cor)
        spans = {(s["from_station"], s["to_station"]): s["length_km"] for s in secs}
        route_km = sum(spans.values())
        print("  %-8s %2d edges over %2d spans, %5.1f route-km, mean span %4.1f km"
              % (cor, len(secs), len(spans), route_km, route_km / max(1, len(spans))))
    print("\nroute MAS -> AJJ: %d spans" % len(net.path_between("MAS", "AJJ")))


if __name__ == "__main__":
    _selfcheck()
