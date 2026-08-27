# -*- coding: utf-8 -*-
"""The network model (Blueprint section 2).

Loads stations.csv and block_sections.csv into a NetworkX MultiDiGraph - chosen
for its native support of parallel edges keyed by line - and wraps it in a
read-only ``Network`` accessor the rest of the pipeline queries. Built once.

Three levels (Blueprint 2.1): station = node, block section = edge, corridor =
named path. Two kinds of adjacency, kept separate (Blueprint 2.3):

    longitudinal - the next block section along the route -> cascade delay
    lateral      - the parallel edges of the same span    -> reroute / never-sever

Conflating them either loses reroute options or double-counts delay, so they are
distinct relations here: ``successors`` for longitudinal, ``parallel`` for lateral.
"""
from __future__ import annotations

import csv
import os

import networkx as nx

from . import config


def _load(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Network:
    """Read-only view over the block-planning graph."""

    def __init__(self, reference_dir=None):
        ref = reference_dir or config.REFERENCE
        self._stations = {r["station_code"]: r for r in _load(os.path.join(ref, "stations.csv"))}
        rows = _load(os.path.join(ref, "block_sections.csv"))
        self._sections = {r["block_section_id"]: r for r in rows}

        g = nx.MultiDiGraph()
        for code, s in self._stations.items():
            g.add_node(code, **s)
        for r in rows:
            r["length_km"] = round(float(r["end_km"]) - float(r["start_km"]), 3)
            r["parallel_edges"] = [e for e in r["parallel_edges"].split(";") if e]
            r["next_sections"] = [e for e in r["next_sections"].split(";") if e]
            g.add_edge(r["from_station"], r["to_station"], key=r["line_id"], **r)
        self.g = g

        # A span is a (from, to) pair; its edges are the parallel lines over it.
        self._span_edges = {}
        for bsid, s in self._sections.items():
            self._span_edges.setdefault((s["from_station"], s["to_station"]), []).append(bsid)

    # --- lookups -------------------------------------------------------------
    def edge(self, bsid):
        """The full attribute dict for one block section."""
        return self._sections[bsid]

    def station(self, code):
        return self._stations[code]

    def all_sections(self):
        return list(self._sections.values())

    def span_of(self, bsid):
        s = self._sections[bsid]
        return (s["from_station"], s["to_station"])

    def edges_on_span(self, from_station, to_station):
        """Every line over the span, in either key orientation."""
        return list(self._span_edges.get((from_station, to_station), [])
                    or self._span_edges.get((to_station, from_station), []))

    def parallel(self, bsid):
        """Lateral group: the other lines of the same span (reroute options)."""
        return [e for e in self.edges_on_span(*self.span_of(bsid)) if e != bsid]

    def successors(self, bsid):
        """Longitudinal group: the next sections along the route (cascade)."""
        return list(self._sections[bsid]["next_sections"])

    def sections_by_corridor(self, corridor_id):
        return [s for s in self._sections.values() if s["corridor_id"] == corridor_id]

    def corridors(self):
        return sorted({s["corridor_id"] for s in self._sections.values()})

    # --- feasibility ---------------------------------------------------------
    def would_sever(self, blocked_bsids):
        """True if blocking this set takes every line of some multi-line span at
        once - the line-union infeasibility FR-21 forbids. Blocking a genuinely
        single-line section is not a sever: it is how that line is worked."""
        blocked = set(blocked_bsids)
        for span, edges in self._span_edges.items():
            if len(edges) > 1 and set(edges) <= blocked:
                return True
        return False

    def __repr__(self):
        spans = len(self._span_edges)
        return ("Network(%d stations, %d block sections over %d spans, %d corridors)"
                % (len(self._stations), len(self._sections), spans, len(self.corridors())))


def load(reference_dir=None):
    return Network(reference_dir)


def _selfcheck():
    net = load()
    print(net)
    # A worked example from Blueprint 2.2: the TRL-AJJ span, four parallel lines.
    span = net.edges_on_span("TRL", "AJJ")
    print("\nTRL-AJJ span carries %d lines: %s" % (len(span), sorted(span)))
    up = "TRL-AJJ-UP"
    print("  parallel to %s : %s" % (up, sorted(net.parallel(up))))
    print("  successors of %s: %s" % (up, net.successors(up)))
    print("  blocking UP alone severs the span? %s" % net.would_sever([up]))
    print("  blocking all four lines severs it?  %s"
          % net.would_sever(net.edges_on_span("TRL", "AJJ")))
    # The single-line branch: one edge, blocking it is normal working not a sever.
    print("  blocking the single-line CGL-WJ severs a multi-line span? %s"
          % net.would_sever(["CGL-WJ-SINGLE"]))
    for cor in net.corridors():
        print("  corridor %-8s: %d edges" % (cor, len(net.sections_by_corridor(cor))))


if __name__ == "__main__":
    _selfcheck()
