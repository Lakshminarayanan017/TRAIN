# -*- coding: utf-8 -*-
"""Emit data/reference/assets.csv (Data Spec 8.3).

One row per maintainable asset. An asset here is a *maintenance unit*, not a
physical item: a "rail" row is a rail panel group a defect is raised against,
not a single rail. Modelling every mast at 60 m spacing would produce a hundred
thousand rows to no purpose - the spec's 8.3 volume of 2,000-5,000 is the tell
that the intended granularity is the unit work is booked against.

Assets are the feature source for the escalation-risk model (12.2), so the
fields that carry signal - cumulative_tonnage_gmt, age, failure_count_12m,
criticality_class - are correlated with the section's real traffic rather than
drawn independently. An escalation model trained on independently drawn features
would learn nothing, and would look like it worked.

Fixed seed per 12.5: the same CSV on every run, on every machine.
"""
from __future__ import print_function

import csv
import datetime as dt
import os
import random

SEED = 26027  # the problem statement number, so the provenance is obvious
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "reference")

# The corpus is dated against a fixed "today" so ages and tonnages do not drift
# between runs. This matches the scenario dates used in Data Spec 9.1.
TODAY = dt.date(2026, 9, 7)

# Edge-located assets, keyed by asset_type -> (units per line-km, department,
# requires_electrification). Densities are per line, so a quadruple section
# carries four times the plain-line assets of a single-line one, which is the
# behaviour the maintenance load should have.
EDGE_DENSITY = {
    "rail":          (0.65, "ENG", False),
    "sleeper":       (0.35, "ENG", False),
    "ballast":       (0.35, "ENG", False),
    "track_circuit": (0.40, "SNT", False),
    "axle_counter":  (0.20, "SNT", False),
    "signal":        (0.35, "SNT", False),
    "OHE_span":      (0.50, "TRD", True),
    "contact_wire":  (0.28, "TRD", True),
    "mast":          (0.40, "TRD", True),
    "insulator":     (0.22, "TRD", True),
}

# Structures sit on the span, not on each line, so they are counted once per
# span at a rate per span-km.
SPAN_STRUCTURES = {
    "bridge":         (0.06, "ENG"),
    "level_crossing": (0.08, "ENG"),
}

# Node-located assets at stations with a yard, scaled by route_capacity.
# asset_type -> (units per route, department, minimum)
NODE_DENSITY = {
    "turnout":       (1.5, "ENG", 2),
    "point_machine": (1.5, "SNT", 2),
    "interlocking":  (0.0, "SNT", 1),   # one interlocking per equipped station
    # Yard P.Way (ENG-YARD-PWAY) and yard OHE (TRD-OHE-YARD) are node tasks, so
    # the assets they act on must exist at the station or the task can never be
    # raised. OHE is sited only where the station touches an electrified section.
    "ballast":       (0.8, "ENG", 2),
    "OHE_span":      (0.5, "TRD", 1),
}

# Traction substations are sparse: roughly one per 25 route-km of electrified
# line, sited at the larger yards.
SUBSTATION_STATIONS = ["MAS", "AVD", "AJJ", "ENR", "MS", "TBM", "CGL"]

# Nominal service life in years, used to spread install dates and to decide
# whether an overhaul has happened yet.
SERVICE_LIFE = {
    "rail": 25, "sleeper": 40, "ballast": 12, "turnout": 20, "bridge": 80,
    "level_crossing": 15, "OHE_span": 35, "mast": 45, "insulator": 15,
    "contact_wire": 25, "substation": 30, "signal": 20, "point_machine": 18,
    "track_circuit": 15, "axle_counter": 15, "interlocking": 22,
}

# Assets whose condition is driven by tonnage passing over them. Everything else
# ages by time alone and leaves cumulative_tonnage_gmt empty.
TONNAGE_BEARING = {"rail", "sleeper", "ballast", "turnout", "bridge",
                   "level_crossing", "track_circuit", "axle_counter"}

# Gross tonnage per train, by the traffic the section carries. Freight rakes are
# far heavier than an EMU, which is why the northern line ages track faster than
# its modest train count suggests.
TONNES_PER_TRAIN = {"freight": 3400, "trunk": 1500, "mixed": 900,
                    "suburban": 420, "branch": 700}

# Asset id prefixes. The Data Spec's own examples fix three of these - PT-TRL-04
# (8.3), RL-TRLAJJ-0421 and OHE-TRLAJJ-0402 (9.1) - so the scheme is the spec's,
# not an invention. Derived prefixes would have produced PO- for point machines
# and clashed MS (mast) with the station code for Chennai Egmore.
PREFIX = {
    "rail": "RL", "sleeper": "SL", "ballast": "BL", "turnout": "TO",
    "bridge": "BR", "level_crossing": "LC", "OHE_span": "OHE", "mast": "MST",
    "insulator": "INS", "contact_wire": "CW", "substation": "SS", "signal": "SG",
    "point_machine": "PT", "track_circuit": "TC", "axle_counter": "AC",
    "interlocking": "IL",
}

# Assets named verbatim in the spec. They are injected so the Section 9.1 sample
# records - which the spec calls the project's first integration test - resolve
# against real rows rather than dangling.
ANCHORS = [
    {"asset_id": "RL-TRLAJJ-0421", "asset_type": "rail", "department": "ENG",
     "block_section_id": "TRL-AJJ-UP", "station_code": "", "km": "42.10",
     "criticality_class": "A", "install_date": "2009-06-14",
     "last_overhaul_date": "2021-02-08", "cumulative_tonnage_gmt": "318.4",
     "failure_count_12m": "2"},
    {"asset_id": "OHE-TRLAJJ-0402", "asset_type": "OHE_span", "department": "TRD",
     "block_section_id": "TRL-AJJ-UP", "station_code": "", "km": "42.00",
     "criticality_class": "B", "install_date": "2004-11-30",
     "last_overhaul_date": "", "cumulative_tonnage_gmt": "",
     "failure_count_12m": "1"},
    {"asset_id": "PT-TRL-04", "asset_type": "point_machine", "department": "SNT",
     "block_section_id": "", "station_code": "TRL", "km": "42.00",
     "criticality_class": "A", "install_date": "2012-08-19",
     "last_overhaul_date": "2022-05-11", "cumulative_tonnage_gmt": "",
     "failure_count_12m": "1"},
]

HEADER = ["asset_id", "asset_type", "department", "block_section_id", "station_code",
          "km", "criticality_class", "install_date", "last_overhaul_date",
          "cumulative_tonnage_gmt", "failure_count_12m"]


def load(name):
    with open(os.path.join(REF, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def criticality(rng, asset_type, trains_per_day):
    """A / B / C. Busy locations and structural assets skew critical."""
    score = trains_per_day / 200.0
    if asset_type in ("bridge", "turnout", "point_machine", "interlocking"):
        score += 0.45
    if asset_type in ("rail", "contact_wire", "signal"):
        score += 0.20
    score += rng.uniform(-0.25, 0.25)
    return "A" if score > 0.75 else ("B" if score > 0.40 else "C")


def dates(rng, asset_type, tonnage_gmt):
    """Install date spread over the service life; overhaul once past mid-life."""
    life = SERVICE_LIFE[asset_type]
    age_years = rng.uniform(0.5, life * 0.95)
    install = TODAY - dt.timedelta(days=int(age_years * 365.25))
    overhaul = ""
    # Heavily worked assets get pulled forward for overhaul sooner.
    threshold = life * (0.35 if tonnage_gmt and tonnage_gmt > 200 else 0.55)
    if age_years > threshold:
        since = rng.uniform(0.2, age_years - threshold + 0.3)
        overhaul = (TODAY - dt.timedelta(days=int(since * 365.25))).isoformat()
    return install.isoformat(), overhaul


def failures(rng, age_days, tonnage_gmt, crit):
    """Failures in the last 12 months. Rises with age and tonnage - this is the
    relationship the escalation model is meant to find, so it must actually be
    present in the data rather than assumed."""
    lam = 0.10
    lam += (age_days / 365.25) * 0.020
    lam += (tonnage_gmt or 0) / 900.0
    lam += {"A": 0.35, "B": 0.12, "C": 0.0}[crit]
    # Poisson draw without numpy.
    limit, k, p = 2.718281828459045 ** -lam, 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def build():
    rng = random.Random(SEED)
    stations = {r["station_code"]: r for r in load("stations.csv")}
    sections = load("block_sections.csv")

    rows = []
    counters = {}

    def next_id(asset_type, scope):
        prefix = PREFIX[asset_type]
        key = (prefix, scope)
        counters[key] = counters.get(key, 0) + 1
        return "%s-%s-%02d" % (prefix, scope, counters[key])

    # ---- edge-located assets, one pass per line ----------------------------
    for sec in sorted(sections, key=lambda r: r["block_section_id"]):
        length = float(sec["end_km"]) - float(sec["start_km"])
        lo = float(sec["start_km"])
        electrified = sec["electrified"] == "true"
        trains = int(sec["daily_train_count"])
        tonnes_year = trains * TONNES_PER_TRAIN[sec["traffic_type"]] * 365 / 1e6  # GMT/yr
        scope = "%s%s" % (sec["from_station"], sec["to_station"])

        for asset_type, (density, dept, needs_power) in sorted(EDGE_DENSITY.items()):
            if needs_power and not electrified:
                continue
            count = max(1, int(round(density * length)))
            for _ in range(count):
                km = round(lo + rng.uniform(0.02, 0.98) * length, 2)
                tonnage = ""
                age_guess = rng.uniform(0.5, SERVICE_LIFE[asset_type] * 0.95)
                if asset_type in TONNAGE_BEARING:
                    tonnage = round(tonnes_year * age_guess, 1)
                crit = criticality(rng, asset_type, trains)
                install, overhaul = dates(rng, asset_type,
                                          tonnage if tonnage != "" else 0)
                age_days = (TODAY - dt.date(*map(int, install.split("-")))).days
                rows.append({
                    "asset_id": next_id(asset_type, scope),
                    "asset_type": asset_type,
                    "department": dept,
                    "block_section_id": sec["block_section_id"],
                    "station_code": "",
                    "km": "%.2f" % km,
                    "criticality_class": crit,
                    "install_date": install,
                    "last_overhaul_date": overhaul,
                    "cumulative_tonnage_gmt": tonnage,
                    "failure_count_12m": failures(rng, age_days,
                                                  tonnage if tonnage != "" else 0, crit),
                })

    # ---- structures, counted once per span, placed on its first line --------
    seen_spans = {}
    for sec in sorted(sections, key=lambda r: r["block_section_id"]):
        span = (sec["from_station"], sec["to_station"])
        seen_spans.setdefault(span, sec)
    for span, sec in sorted(seen_spans.items()):
        length = float(sec["end_km"]) - float(sec["start_km"])
        lo = float(sec["start_km"])
        trains = int(sec["daily_train_count"])
        tonnes_year = trains * TONNES_PER_TRAIN[sec["traffic_type"]] * 365 / 1e6
        scope = "%s%s" % span
        for asset_type, (density, dept) in sorted(SPAN_STRUCTURES.items()):
            count = int(round(density * length))
            for _ in range(count):
                km = round(lo + rng.uniform(0.05, 0.95) * length, 2)
                age_guess = rng.uniform(0.5, SERVICE_LIFE[asset_type] * 0.95)
                tonnage = round(tonnes_year * age_guess, 1)
                crit = criticality(rng, asset_type, trains)
                install, overhaul = dates(rng, asset_type, tonnage)
                age_days = (TODAY - dt.date(*map(int, install.split("-")))).days
                rows.append({
                    "asset_id": next_id(asset_type, scope),
                    "asset_type": asset_type,
                    "department": dept,
                    "block_section_id": sec["block_section_id"],
                    "station_code": "",
                    "km": "%.2f" % km,
                    "criticality_class": crit,
                    "install_date": install,
                    "last_overhaul_date": overhaul,
                    "cumulative_tonnage_gmt": tonnage,
                    "failure_count_12m": failures(rng, age_days, tonnage, crit),
                })

    # ---- node-located assets at stations with a yard ------------------------
    # Station throughput drives criticality and tonnage the same way a section's
    # train count does, so derive it from the busiest edge touching the station.
    throughput = {}
    for sec in sections:
        for endpoint in (sec["from_station"], sec["to_station"]):
            trains = int(sec["daily_train_count"])
            if trains > throughput.get(endpoint, 0):
                throughput[endpoint] = trains

    # A station is under wire if any section touching it is electrified.
    under_wire = set()
    for sec in sections:
        if sec["electrified"] == "true":
            under_wire.add(sec["from_station"])
            under_wire.add(sec["to_station"])

    for code in sorted(stations):
        station = stations[code]
        if station["has_yard"] != "true":
            continue
        routes = int(station["route_capacity"] or 0)
        trains = throughput.get(code, 40)
        tonnes_year = trains * 900 * 365 / 1e6
        km = float(station["km_from_origin"])
        plan = dict(NODE_DENSITY)
        if code not in under_wire:
            plan.pop("OHE_span", None)
        if code in SUBSTATION_STATIONS:
            plan["substation"] = (0.0, "TRD", 1)
        for asset_type, (per_route, dept, minimum) in sorted(plan.items()):
            count = max(minimum, int(round(per_route * routes)))
            for _ in range(count):
                age_guess = rng.uniform(0.5, SERVICE_LIFE[asset_type] * 0.95)
                tonnage = (round(tonnes_year * age_guess, 1)
                           if asset_type in TONNAGE_BEARING else "")
                crit = criticality(rng, asset_type, trains)
                install, overhaul = dates(rng, asset_type,
                                          tonnage if tonnage != "" else 0)
                age_days = (TODAY - dt.date(*map(int, install.split("-")))).days
                rows.append({
                    "asset_id": next_id(asset_type, code),
                    "asset_type": asset_type,
                    "department": dept,
                    "block_section_id": "",
                    "station_code": code,
                    "km": "%.2f" % km,
                    "criticality_class": crit,
                    "install_date": install,
                    "last_overhaul_date": overhaul,
                    "cumulative_tonnage_gmt": tonnage,
                    "failure_count_12m": failures(rng, age_days,
                                                  tonnage if tonnage != "" else 0, crit),
                })
    # Reconcile the spec-named assets. PT-TRL-04 falls out of the generator on its
    # own - it is genuinely the fourth point machine at Tiruvallur - so the anchor
    # overwrites that row rather than duplicating it. The others are appended.
    # Either way the id, type and location must agree with the spec.
    by_asset_id = {r["asset_id"]: r for r in rows}
    for anchor in ANCHORS:
        existing = by_asset_id.get(anchor["asset_id"])
        if existing is None:
            rows.append(dict(anchor))
            continue
        for field in ("asset_type", "block_section_id", "station_code"):
            if existing[field] != anchor[field]:
                raise SystemExit("anchor %s: generated %s=%r, spec says %r"
                                 % (anchor["asset_id"], field,
                                    existing[field], anchor[field]))
        existing.update(anchor)
    return rows


def main():
    rows = build()
    out = os.path.join(REF, "assets.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print("assets.csv: %d rows" % len(rows))


if __name__ == "__main__":
    main()
