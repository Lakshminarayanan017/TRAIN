# -*- coding: utf-8 -*-
"""Emit data/reference/block_sections.csv (Data Spec 8.2).

One row per (from_station, to_station, line_id). Spans run between consecutive
BLOCK stations only; intermediate halts are spanned over. Endpoints are ordered
by increasing km on the section's home corridor, so line_id is the only thing
separating parallel edges.

Station codes, chainage, corridor membership and block-station status are read
from stations.csv rather than restated here, so the two files cannot drift. Only
the per-section attributes the station master does not carry are held below.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")

MAIN4 = ["UP", "DN", "UP_SUB", "DN_SUB"]
MAIN2 = ["UP", "DN"]
SINGLE = ["SINGLE"]

# Data Spec 8.2 mandates electrified = false on the AJJ-Kanchipuram stretch. The
# network itself is electrified there. False follows the spec; True follows
# reality. Kept as one switch so the choice is visible and reversible.
BRANCH_ELECTRIFIED = False

# The ordered run of stations along each corridor, and the line set that corridor
# carries. Spans are cut between consecutive *block* stations in this sequence.
CORRIDORS = [
    ("MAS-AJJ", MAIN4, ["MAS", "BBQ", "VJM", "PER", "VLK", "ABU", "AVD", "TI",
                        "VEU", "TRL", "MAF", "AJJ"]),
    ("BBQ-GPD", MAIN2, ["BBQ", "TNP", "TVT", "WCN", "ENR", "MJR", "PON", "GPD"]),
    ("MSB-TBM", MAIN4, ["MSB", "MS", "MBM", "GI", "STM", "PV", "TBM"]),
    ("AJJ-CGL", SINGLE, ["CGL", "WJ", "CJ", "TMLP", "TKO", "AJJ"]),
]

# AJJ is measured on its primary corridor (the trunk, MAS = 0) in the station
# master. On corridor 4, measured from Chennai Beach, it sits at 127.82 (CGL at
# 59.84 + the 68.0 km branch run from IndiaRailInfo point distances: CGL-WJ 21.94,
# WJ-CJ 14.1, CJ-TMLP 12, TMLP-TKO 7, TKO-AJJ 13). The station master cannot hold
# both, so the off-corridor chainage lives here.
OFF_CORRIDOR_KM = {("AJJ-CGL", "AJJ"): 127.82}

# The spec's 8.2 anchor puts the end of TRL-AJJ at 68.5 against AJJ's 69.0 post.
SPAN_KM_OVERRIDE = {("TRL", "AJJ"): (42.0, 68.5)}

# Per-span attributes the station master does not carry.
# key -> (electrified, {main/sub: kmph}, {main/sub: trains per day}, monsoon_sensitive)
SPANS = {
    # Corridor 1 - Chennai Central to Arakkonam, quadruple trunk.
    ("MAS", "BBQ"): (True,  {"main": 75,  "sub": 60},  {"main": 95, "sub": 175}, True),
    ("BBQ", "PER"): (True,  {"main": 100, "sub": 80},  {"main": 88, "sub": 170}, True),
    ("PER", "ABU"): (True,  {"main": 110, "sub": 100}, {"main": 82, "sub": 160}, True),
    ("ABU", "AVD"): (True,  {"main": 110, "sub": 100}, {"main": 80, "sub": 150}, False),
    ("AVD", "TI"):  (True,  {"main": 110, "sub": 100}, {"main": 76, "sub": 70},  False),
    ("TI",  "TRL"): (True,  {"main": 110, "sub": 100}, {"main": 74, "sub": 55},  False),
    # The four TRL-AJJ edges sum to the spec's 210 anchor for the section.
    ("TRL", "AJJ"): (True,  {"main": 110, "sub": 100}, {"main": 70, "sub": 35},  False),
    # Corridor 2 - Basin Bridge to Gummidipoondi, double, port-bound freight.
    ("BBQ", "TNP"): (True,  {"main": 60},  {"main": 55}, True),
    ("TNP", "ENR"): (True,  {"main": 80},  {"main": 48}, True),
    ("ENR", "MJR"): (True,  {"main": 100}, {"main": 40}, True),
    ("MJR", "PON"): (True,  {"main": 100}, {"main": 34}, True),
    ("PON", "GPD"): (True,  {"main": 100}, {"main": 34}, True),
    # Corridor 3 - Chennai Beach to Tambaram, quadruple, saturated suburban.
    ("MSB", "MS"):  (True,  {"main": 60,  "sub": 50}, {"main": 70, "sub": 200}, True),
    ("MS",  "MBM"): (True,  {"main": 90,  "sub": 75}, {"main": 66, "sub": 195}, True),
    ("MBM", "GI"):  (True,  {"main": 90,  "sub": 75}, {"main": 66, "sub": 195}, True),
    ("GI",  "STM"): (True,  {"main": 100, "sub": 80}, {"main": 64, "sub": 190}, True),
    ("STM", "PV"):  (True,  {"main": 100, "sub": 80}, {"main": 60, "sub": 180}, True),
    ("PV",  "TBM"): (True,  {"main": 100, "sub": 80}, {"main": 60, "sub": 180}, True),
    # Corridor 4 - Chengalpattu to Arakkonam via Kanchipuram, single line.
    # Data Spec 8.2 states electrified is false only for the AJJ-Kanchipuram
    # stretch. The real line was electrified and the route now runs EMUs end to
    # end (see stations.README.md, "Where the spec and the network disagree").
    # The spec value is kept because it is the written build contract; flip
    # BRANCH_ELECTRIFIED to True to follow the network instead. One line.
    ("CGL", "WJ"):   (True,  {"main": 100}, {"main": 18}, False),
    ("WJ",  "CJ"):   (True,  {"main": 100}, {"main": 18}, False),
    ("CJ",  "TMLP"): (BRANCH_ELECTRIFIED, {"main": 90}, {"main": 14}, False),
    ("TMLP", "TKO"): (BRANCH_ELECTRIFIED, {"main": 90}, {"main": 14}, False),
    ("TKO", "AJJ"):  (BRANCH_ELECTRIFIED, {"main": 90}, {"main": 14}, False),
}

TRAFFIC = {
    "MAS-AJJ": {"main": "trunk",   "sub": "suburban"},
    "BBQ-GPD": {"main": "freight"},
    "MSB-TBM": {"main": "mixed",   "sub": "suburban"},
    "AJJ-CGL": {"main": "branch"},
}

# Single-line working can be instituted on the main pair and on the already-single
# branch; the suburban pair runs unidirectional automatic block signalling.
BIDIR = {"UP": True, "DN": True, "UP_SUB": False, "DN_SUB": False, "SINGLE": True}

# Where a corridor meets another one, the running connection is not simply "the
# next span along". These are the exceptions to same-line continuation; every
# other successor is derived.
JUNCTION_LINKS = {
    # Basin Bridge is where the northern freight line diverges from the trunk.
    # EMU services do not continue onto the Ennore road, so only the main pair
    # gains the second successor.
    ("MAS-AJJ", "BBQ", "UP"): ["BBQ-TNP-UP"],
    ("MAS-AJJ", "BBQ", "DN"): ["BBQ-TNP-DN"],
    # Traffic off the single-line branch joins the trunk main pair at Arakkonam,
    # not the suburban pair.
    ("AJJ-CGL", "AJJ", "SINGLE"): ["TRL-AJJ-UP", "TRL-AJJ-DN"],
    # The trunk's far end continues onto the branch at Arakkonam.
    ("MAS-AJJ", "AJJ", "UP"): ["TKO-AJJ-SINGLE"],
    ("MAS-AJJ", "AJJ", "DN"): ["TKO-AJJ-SINGLE"],
    ("MAS-AJJ", "AJJ", "UP_SUB"): ["TKO-AJJ-SINGLE"],
    ("MAS-AJJ", "AJJ", "DN_SUB"): ["TKO-AJJ-SINGLE"],
}

HEADER = ["block_section_id", "from_station", "to_station", "line_id",
          "start_km", "end_km", "corridor_id", "parallel_edges", "next_sections",
          "electrified", "sectional_speed_kmph", "daily_train_count",
          "traffic_type", "bidirectional_capable", "monsoon_sensitive",
          "division_id"]


def kind(line):
    return "sub" if line.endswith("_SUB") else "main"


def load_stations():
    with open(os.path.join(REF, "stations.csv"), encoding="utf-8", newline="") as fh:
        return {r["station_code"]: r for r in csv.DictReader(fh)}


def build():
    stations = load_stations()

    def km(corridor, code):
        override = OFF_CORRIDOR_KM.get((corridor, code))
        if override is not None:
            return override
        return float(stations[code]["km_from_origin"])

    # Cut each corridor into spans between consecutive block stations.
    spans = []          # (corridor, lines, from, to)
    span_index = {}     # (corridor, from_station) -> position in that corridor
    for corridor, lines, sequence in CORRIDORS:
        blocks = [c for c in sequence if stations[c]["is_block_station"] == "true"]
        for pos, (frm, to) in enumerate(zip(blocks, blocks[1:])):
            spans.append((corridor, lines, frm, to))
            span_index[(corridor, frm)] = pos

    # Longitudinal adjacency: the next span along the same corridor keeps the
    # line where the adjoining span carries it, plus any junction link.
    by_corridor = {}
    for corridor, lines, frm, to in spans:
        by_corridor.setdefault(corridor, []).append((frm, to, lines))

    rows = []
    for corridor, lines, frm, to in spans:
        start, end = SPAN_KM_OVERRIDE.get((frm, to), (km(corridor, frm), km(corridor, to)))
        elec, speed, trains, monsoon = SPANS[(frm, to)]
        group = ["%s-%s-%s" % (frm, to, l) for l in lines]

        seq = by_corridor[corridor]
        pos = [i for i, s in enumerate(seq) if s[0] == frm and s[1] == to][0]
        onward = seq[pos + 1] if pos + 1 < len(seq) else None

        for line in lines:
            bsid = "%s-%s-%s" % (frm, to, line)
            successors = []
            if onward and line in onward[2]:
                successors.append("%s-%s-%s" % (onward[0], onward[1], line))
            successors += JUNCTION_LINKS.get((corridor, to, line), [])
            k = kind(line)
            rows.append({
                "block_section_id": bsid,
                "from_station": frm,
                "to_station": to,
                "line_id": line,
                "start_km": "%.1f" % start,
                "end_km": "%.1f" % end,
                "corridor_id": corridor,
                "parallel_edges": ";".join(e for e in group if e != bsid),
                "next_sections": ";".join(successors),
                "electrified": str(elec).lower(),
                "sectional_speed_kmph": speed[k],
                "daily_train_count": trains[k],
                "traffic_type": TRAFFIC[corridor][k],
                "bidirectional_capable": str(BIDIR[line]).lower(),
                "monsoon_sensitive": str(monsoon).lower(),
                "division_id": "SR-MAS",
            })
    return rows


def main():
    rows = build()
    out = os.path.join(REF, "block_sections.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    spans = len({(r["from_station"], r["to_station"]) for r in rows})
    print("block_sections.csv: %d edges over %d spans" % (len(rows), spans))


if __name__ == "__main__":
    main()
