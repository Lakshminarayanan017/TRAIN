# -*- coding: utf-8 -*-
"""Stage 3 - candidate window enumeration (Blueprint section 5).

A window is a slice of time on one edge that maintenance can be worked in. Two
sources (Blueprint 5.1):

    corridor_block - pre-planned, already negotiated into the timetable. Read
                     directly from corridor_windows.csv.
    traffic_gap    - a hole in the train pattern wide enough to work in. Detected,
                     not given, from train_paths.

A gap is not a window (Blueprint 5.2): a block cannot start the moment the last
train clears, nor run to the moment the next one is due. setup and clearance
margins come off each end, and anything left under the minimum is discarded.

Gaps are found cyclically over the 24h day, so the large hole that straddles
midnight - the one every suburban block lives in - is one window, not two halves
split at 00:00. The goods forecast then turns each gap probabilistic (Blueprint
5.3): an empty-looking slot on the northern line may be taken by a port rake.
"""
from __future__ import annotations

import csv
import math
import os

from . import config
from .network import Network

DAY_CODE = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fmt(minute):
    minute %= 1440
    return "%02d:%02d" % (minute // 60, minute % 60)


def band_of(minute):
    h = (minute // 60) % 24
    return "00-06" if h < 6 else "06-12" if h < 12 else "12-18" if h < 18 else "18-24"


def _merge(intervals):
    """Merge overlapping [s, e) intervals on [0, 1440)."""
    if not intervals:
        return []
    intervals = sorted(intervals)
    out = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _free_arcs(merged):
    """Complement of the merged occupations, cyclically. Returns (start, end)
    free arcs where end may exceed 1440 for an arc that wraps past midnight."""
    if not merged:
        return [(0, 1440)]
    free = []
    for (_, b), (c, _) in zip(merged, merged[1:]):
        if c > b:
            free.append((b, c))
    last_end, first_start = merged[-1][1], merged[0][0]
    wrap = (1440 - last_end) + first_start
    if wrap > 0:
        free.append((last_end, last_end + wrap))   # wraps through midnight
    return free


class WindowEnumerator:
    def __init__(self, net=None, supply_dir=None, week_start=None,
                 setup_min=None, clearance_min=None, min_usable_min=None,
                 headway_buffer_min=None):
        self.net = net or Network()
        supply = supply_dir or config.SUPPLY
        self.week_start = week_start or config.WEEK_START
        self.setup = config.SETUP_MIN if setup_min is None else setup_min
        self.clearance = config.CLEARANCE_MIN if clearance_min is None else clearance_min
        self.min_usable = config.MIN_USABLE_MIN if min_usable_min is None else min_usable_min
        self.buffer = config.HEADWAY_BUFFER_MIN if headway_buffer_min is None else headway_buffer_min

        self._trains = self._load_trains(os.path.join(supply, "train_paths.csv"))
        self._corridor = self._load_corridor(os.path.join(supply, "corridor_windows.csv"))
        self._goods = self._load_goods(os.path.join(supply, "goods_forecast.csv"))

    @staticmethod
    def _rows(path):
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def _load_trains(self, path):
        by_edge = {}
        for r in self._rows(path):
            by_edge.setdefault(r["block_section_id"], []).append(
                (to_min(r["entry_time"]), to_min(r["exit_time"]), r["days_of_week"]))
        return by_edge

    def _load_corridor(self, path):
        by_key = {}
        for r in self._rows(path):
            by_key.setdefault((r["block_section_id"], r["day_of_week"]), []).append(r)
        return by_key

    def _load_goods(self, path):
        by_key = {}
        for r in self._rows(path):
            by_key[(r["block_section_id"], r["forecast_date"], r["time_band"])] = (
                int(r["expected_rakes"]), float(r["confidence"]))
        return by_key

    def _goods_risk(self, bsid, date, band, usable_min):
        """Probability the gap is actually taken by a forecast freight rake."""
        hit = self._goods.get((bsid, date.isoformat(), band))
        if not hit:
            return 0.0
        rakes, conf = hit
        if rakes <= 0:
            return 0.0
        rate = rakes / 360.0                       # rakes per minute in the 6h band
        p = 1.0 - math.exp(-rate * usable_min)
        return round(conf * p, 3)

    def _occupations(self, bsid, dow):
        occ = []
        for entry, exit_, days in self._trains.get(bsid, []):
            if days[dow] != "1":
                continue
            lo, hi = entry - self.buffer, exit_ + self.buffer
            if hi > lo and exit_ > entry:
                occ.append((max(0, lo), min(1440, hi)))
            else:                                  # wraps past midnight
                occ.append((max(0, lo), 1440))
                occ.append((0, min(1440, exit_ + self.buffer)))
        return occ

    def enumerate(self):
        windows = []
        for offset in range(7):
            date = self.week_start + __import__("datetime").timedelta(days=offset)
            dow = date.weekday()
            daycode = DAY_CODE[dow]
            for sec in self.net.all_sections():
                bsid = sec["block_section_id"]
                merged = _merge(self._occupations(bsid, dow))
                for s, e in _free_arcs(merged):
                    usable = (e - s) - self.setup - self.clearance
                    if usable < self.min_usable:
                        continue
                    start = (s + self.setup) % 1440
                    band = band_of(start)
                    windows.append(self._row(sec, date, daycode, "traffic_gap",
                                             start, usable,
                                             self._goods_risk(bsid, date, band, usable), ""))
                corridor = self._corridor.get((bsid, daycode), [])
                for cw in corridor:
                    windows.append(self._row(sec, date, daycode, "corridor_block",
                                             to_min(cw["start_time"]),
                                             int(cw["duration_min"]), 0.0,
                                             cw["max_departments"]))
                # A requested-access option where no corridor block exists that
                # day, so urgent work can be fitted (FR-17). Its detention cost is
                # real, so it is dear on a busy line and cheap on a quiet one.
                if not corridor:
                    start = config.REQUESTED_START_MIN
                    windows.append(self._row(sec, date, daycode, "requested", start,
                                             config.REQUESTED_DURATION_MIN,
                                             self._goods_risk(bsid, date, band_of(start),
                                                              config.REQUESTED_DURATION_MIN), ""))
        return windows

    def _row(self, sec, date, daycode, wtype, start_min, duration, goods_risk, max_dept):
        bsid = sec["block_section_id"]
        tag = "CB" if wtype == "corridor_block" else "TG"
        return {
            "window_id": "%s-%s-%s-%s" % (tag, bsid, date.isoformat(), fmt(start_min).replace(":", "")),
            "block_section_id": bsid,
            "corridor_id": sec["corridor_id"],
            "line_id": sec["line_id"],
            "date": date.isoformat(),
            "day_of_week": daycode,
            "start_time": fmt(start_min),
            "start_min": start_min,
            "duration_min": int(duration),
            "window_type": wtype,
            "goods_risk": goods_risk,
            "max_departments": max_dept,
        }


HEADER = ["window_id", "block_section_id", "corridor_id", "line_id", "date",
          "day_of_week", "start_time", "start_min", "duration_min",
          "window_type", "goods_risk", "max_departments"]


def enumerate_windows(**kwargs):
    return WindowEnumerator(**kwargs).enumerate()


def write_csv(windows, path=None):
    path = path or os.path.join(config.DERIVED, "candidate_windows.csv")
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(windows)
    return path


def _selfcheck():
    from collections import Counter, defaultdict
    net = Network()
    wins = WindowEnumerator(net).enumerate()
    out = write_csv(wins)
    gaps = [w for w in wins if w["window_type"] == "traffic_gap"]
    blocks = [w for w in wins if w["window_type"] == "corridor_block"]
    print("candidate windows: %d  (%d traffic_gap, %d corridor_block) -> %s"
          % (len(wins), len(gaps), len(blocks), os.path.relpath(out, config.ROOT)))

    # Blueprint 5.3: suburban gaps exist only after midnight; the low-density
    # branch and freight lines have usable daytime holes. This is the test.
    print("\ntraffic-gap start band by corridor (Blueprint 5.3 asymmetry):")
    corridor_band = defaultdict(Counter)
    for w in gaps:
        corridor_band[w["corridor_id"]][band_of(w["start_min"])] += 1
    for cor in net.corridors():
        print("  %-8s %s" % (cor, dict(sorted(corridor_band[cor].items()))))

    # A worked look at the spec's TRL-AJJ suburban line for one day.
    sample = [w for w in gaps if w["block_section_id"] == "TRL-AJJ-UP_SUB"
              and w["date"] == config.WEEK_START.isoformat()]
    print("\nTRL-AJJ-UP_SUB on %s: %s" % (config.WEEK_START,
          [(w["start_time"], w["duration_min"]) for w in sample]))
    print("mean usable gap: %d min | with goods_risk>0: %d windows"
          % (sum(int(w["duration_min"]) for w in gaps) / max(1, len(gaps)),
             sum(1 for w in gaps if float(w["goods_risk"]) > 0)))


if __name__ == "__main__":
    _selfcheck()
