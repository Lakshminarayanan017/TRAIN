# -*- coding: utf-8 -*-
"""Stage 3 - candidate window enumeration (Blueprint section 5).

A window is a slice of time on one edge that maintenance can be worked in, and
this stage is what turns a timetable into opportunities. Three sources:

    corridor_block - pre-planned, already negotiated into the working timetable
                     and sanctioned in principle. Read directly (Blueprint 5.1).
    traffic_gap    - a hole in the train pattern wide enough to work in.
                     Detected, not given.
    requested      - access asked for outside the pre-planned pattern, so urgent
                     work can still be fitted (FR-17). Flagged distinctly and
                     penalised in the objective, never silently equivalent.

A gap is not a window (Blueprint 5.2). A block cannot begin the moment the last
train clears - men and machines must reach the site - nor run to the moment the
next is due, because the line must be cleared, tools accounted for and the
section certified fit. Setup and clearance come off each end and anything left
below the minimum is discarded.

Gaps are found cyclically over the 24-hour day, so the large hole that straddles
midnight - the one every suburban block lives in - is one window rather than two
useless halves split at 00:00.

Three complications, all modelled (Blueprint 5.3):
  - goods trains are not in the passenger timetable, so the freight forecast
    turns an apparently empty gap into a probabilistic one;
  - windows already claimed elsewhere (BDMS requests, possessions) are subtracted
    through ``existing_occupancy`` so this planner never double-books them;
  - gap availability varies by line, and that asymmetry is real - suburban lines
    have gaps only after midnight, the branch genuinely has daytime ones.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import os
from collections import Counter, defaultdict

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


def is_night(minute):
    m = minute % 1440
    return m < config.CANDIDATE_TERMINAL_MIN or m >= 22 * 60


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
    """Complement of the merged occupations, cyclically. `end` may exceed 1440
    for the arc that wraps past midnight - deliberately, so the block that starts
    at 23:28 and runs to 04:10 is one window."""
    if not merged:
        return [(0, 1440)]
    free = []
    for (_, b), (c, _) in zip(merged, merged[1:]):
        if c > b:
            free.append((b, c))
    last_end, first_start = merged[-1][1], merged[0][0]
    wrap = (1440 - last_end) + first_start
    if wrap > 0:
        free.append((last_end, last_end + wrap))
    return free


class WindowEnumerator:
    def __init__(self, net=None, supply_dir=None, week_start=None,
                 setup_min=None, clearance_min=None, min_usable_min=None,
                 headway_buffer_min=None, existing_occupancy=None,
                 emit_requested=True, slide_step_min=0):
        self.net = net or Network()
        supply = supply_dir or config.SUPPLY
        self.week_start = week_start or config.WEEK_START
        self.setup = config.SETUP_MIN if setup_min is None else setup_min
        self.clearance = config.CLEARANCE_MIN if clearance_min is None else clearance_min
        self.min_usable = config.MIN_USABLE_MIN if min_usable_min is None else min_usable_min
        self.buffer = config.HEADWAY_BUFFER_MIN if headway_buffer_min is None else headway_buffer_min
        self.emit_requested = emit_requested
        # Optional local refinement (Blueprint 7.1): offer several start offsets
        # inside a long gap so the optimiser can slide a block to a cheaper
        # moment. Off by default - it multiplies the window count.
        self.slide_step = slide_step_min

        # Access already claimed elsewhere: BDMS requests this system did not
        # create, and possessions, which enter as fixed unavailable windows
        # (Blueprint 1.3). FR-03: read them so a window is never double-booked.
        # (block_section_id, date_iso) -> [(start_min, end_min)]
        self.existing = defaultdict(list)
        for bsid, date_iso, start_min, dur in (existing_occupancy or []):
            self.existing[(bsid, date_iso)].append((start_min, start_min + dur))

        self._trains = self._load_trains(os.path.join(supply, "train_paths.csv"))
        self._corridor = self._load_corridor(os.path.join(supply, "corridor_windows.csv"))
        self._goods = self._load_goods(os.path.join(supply, "goods_forecast.csv"))

    @staticmethod
    def _rows(path):
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def _load_trains(self, path):
        by_edge = defaultdict(list)
        for r in self._rows(path):
            by_edge[r["block_section_id"]].append(
                (to_min(r["entry_time"]), to_min(r["exit_time"]), r["days_of_week"]))
        return by_edge

    def _load_corridor(self, path):
        by_key = defaultdict(list)
        for r in self._rows(path):
            by_key[(r["block_section_id"], r["day_of_week"])].append(r)
        return by_key

    def _load_goods(self, path):
        return {(r["block_section_id"], r["forecast_date"], r["time_band"]):
                (int(r["expected_rakes"]), float(r["confidence"]))
                for r in self._rows(path)}

    # ---- occupancy ----------------------------------------------------------
    def _occupations(self, bsid, dow, date_iso):
        """Every claim on the edge that day: timetabled trains, plus any access
        already granted elsewhere."""
        occ = []
        for entry, exit_, days in self._trains.get(bsid, []):
            if days[dow] != "1":
                continue
            lo, hi = entry - self.buffer, exit_ + self.buffer
            if exit_ > entry:
                occ.append((max(0, lo), min(1440, hi)))
            else:                                  # the path wraps past midnight
                occ.append((max(0, lo), 1440))
                occ.append((0, min(1440, exit_ + self.buffer)))
        for s, e in self.existing.get((bsid, date_iso), []):
            occ.append((max(0, s), min(1440, e)))
        return occ

    def _goods_risk(self, bsid, date, band, usable_min):
        """Probability the gap is actually taken by a forecast freight rake. A
        Poisson arrival over the band converts a rake count into the chance at
        least one lands inside the window."""
        hit = self._goods.get((bsid, date.isoformat(), band))
        if not hit:
            return 0.0
        rakes, conf = hit
        if rakes <= 0:
            return 0.0
        rate = rakes / 360.0                       # rakes per minute over a 6h band
        return round(conf * (1.0 - math.exp(-rate * usable_min)), 3)

    # ---- enumeration --------------------------------------------------------
    def enumerate(self):
        windows = []
        for offset in range(7):
            date = self.week_start + dt.timedelta(days=offset)
            date_iso = date.isoformat()
            dow = date.weekday()
            daycode = DAY_CODE[dow]
            for sec in self.net.all_sections():
                bsid = sec["block_section_id"]

                # 1. Pre-planned corridor blocks, read directly.
                corridor = self._corridor.get((bsid, daycode), [])
                claimed = []
                for cw in corridor:
                    start = to_min(cw["start_time"])
                    dur = int(cw["duration_min"])
                    claimed.append((start, start + dur))
                    windows.append(self._row(sec, date, daycode, "corridor_block",
                                             start, dur, 0.0, cw["max_departments"]))

                # 2. Detected traffic gaps, net of setup and clearance.
                merged = _merge(self._occupations(bsid, dow, date_iso))
                for s, e in _free_arcs(merged):
                    usable = (e - s) - self.setup - self.clearance
                    if usable < self.min_usable:
                        continue
                    start = s + self.setup
                    # A gap that merely re-offers a corridor block is not a second
                    # opportunity; the corridor block is the better-priced one.
                    if any(start < ce and start + usable > cs for cs, ce in claimed):
                        continue
                    for st, du in self._slices(start, usable):
                        windows.append(self._row(sec, date, daycode, "traffic_gap", st, du,
                                                 self._goods_risk(bsid, date, band_of(st), du), ""))

                # 3. Newly requested access where the pattern offers none (FR-17).
                if self.emit_requested and not corridor:
                    start = config.REQUESTED_START_MIN
                    dur = config.REQUESTED_DURATION_MIN
                    if not any(start < ce and start + dur > cs for cs, ce in claimed):
                        windows.append(self._row(sec, date, daycode, "requested", start, dur,
                                                 self._goods_risk(bsid, date, band_of(start), dur), ""))
        return windows

    def _slices(self, start, usable):
        """One window per gap, or several start offsets when local refinement is
        enabled, so the optimiser can slide a block to a cheaper moment."""
        if not self.slide_step or usable < self.min_usable * 2:
            return [(start % 1440, usable)]
        out = []
        off = 0
        while usable - off >= self.min_usable:
            out.append(((start + off) % 1440, usable - off))
            off += self.slide_step
        return out

    def _row(self, sec, date, daycode, wtype, start_min, duration, goods_risk, max_dept):
        bsid = sec["block_section_id"]
        tag = {"corridor_block": "CB", "traffic_gap": "TG", "requested": "RQ"}[wtype]
        start_min %= 1440
        return {
            "window_id": "%s-%s-%s-%s" % (tag, bsid, date.isoformat(), fmt(start_min).replace(":", "")),
            "block_section_id": bsid,
            "corridor_id": sec["corridor_id"],
            "line_id": sec["line_id"],
            "date": date.isoformat(),
            "day_of_week": daycode,
            "start_time": fmt(start_min),
            "start_min": start_min,
            "end_time": fmt(start_min + int(duration)),
            "duration_min": int(duration),
            "window_type": wtype,
            "goods_risk": goods_risk,
            "is_night": "true" if is_night(start_min) else "false",
            "max_departments": max_dept,
        }

    # ---- validation ---------------------------------------------------------
    def validate(self, windows):
        """A window the optimiser cannot trust is worse than no window."""
        out = []
        seen = set()
        sections = set(self.net.section_ids())
        for w in windows:
            wid = w["window_id"]
            if wid in seen:
                out.append("ERROR duplicate window_id %s" % wid)
            seen.add(wid)
            if w["block_section_id"] not in sections:
                out.append("ERROR %s: unknown block section" % wid)
            if w["duration_min"] < self.min_usable:
                out.append("ERROR %s: %d min is below the usable minimum"
                           % (wid, w["duration_min"]))
            if not (0 <= w["start_min"] < 1440):
                out.append("ERROR %s: start %d outside the day" % (wid, w["start_min"]))
            if w["window_type"] not in ("corridor_block", "traffic_gap", "requested"):
                out.append("ERROR %s: unknown window type %s" % (wid, w["window_type"]))
            if not 0.0 <= float(w["goods_risk"]) <= 1.0:
                out.append("ERROR %s: goods_risk outside [0,1]" % wid)
        # A detected gap must not overlap a train it was derived from.
        by_key = defaultdict(list)
        for w in windows:
            if w["window_type"] == "traffic_gap":
                by_key[(w["block_section_id"], w["date"])].append(w)
        for (bsid, date_iso), ws in by_key.items():
            dow = dt.date(*map(int, date_iso.split("-"))).weekday()
            occ = _merge(self._occupations(bsid, dow, date_iso))
            for w in ws:
                s = w["start_min"]
                e = s + w["duration_min"]
                for os_, oe in occ:
                    lo, hi = (os_, oe) if e <= 1440 else (os_ + 1440, oe + 1440)
                    if s < oe and e > os_ and not (s >= oe or e <= os_):
                        if not (e > 1440 and os_ < (e - 1440)):
                            out.append("ERROR %s: overlaps a train occupation %s-%s"
                                       % (w["window_id"], fmt(os_), fmt(oe)))
                        break
        return out

    def summary(self, windows):
        by_type = Counter(w["window_type"] for w in windows)
        by_corridor = defaultdict(Counter)
        for w in windows:
            by_corridor[w["corridor_id"]][w["window_type"]] += 1
        gaps = [w for w in windows if w["window_type"] == "traffic_gap"]
        return {
            "total": len(windows),
            "by_type": dict(by_type),
            "by_corridor": {k: dict(v) for k, v in sorted(by_corridor.items())},
            "mean_gap_min": round(sum(w["duration_min"] for w in gaps) / max(1, len(gaps))),
            "night_share": round(100.0 * sum(1 for w in windows if w["is_night"] == "true")
                                 / max(1, len(windows))),
            "with_goods_risk": sum(1 for w in windows if float(w["goods_risk"]) > 0),
        }


HEADER = ["window_id", "block_section_id", "corridor_id", "line_id", "date",
          "day_of_week", "start_time", "start_min", "end_time", "duration_min",
          "window_type", "goods_risk", "is_night", "max_departments"]


def enumerate_windows(**kwargs):
    return WindowEnumerator(**kwargs).enumerate()


def write_csv(windows, path=None):
    path = path or os.path.join(config.DERIVED, "candidate_windows.csv")
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(windows)
    return path


def _selfcheck():
    net = Network()
    we = WindowEnumerator(net)
    wins = we.enumerate()
    out = write_csv(wins)
    s = we.summary(wins)

    print("Window enumeration for the week of %s\n" % config.WEEK_START)
    print("windows: %d  %s" % (s["total"], s["by_type"]))
    print("mean usable gap %d min | %d%% start at night | %d carry a goods risk"
          % (s["mean_gap_min"], s["night_share"], s["with_goods_risk"]))

    errs = we.validate(wins)
    print("validation: %s" % ("PASS - every window is usable and train-free"
                              if not errs else "%d ERROR(S): %s" % (len(errs), errs[:3])))

    print("\nby corridor:")
    for cor, counts in s["by_corridor"].items():
        print("  %-8s %s" % (cor, counts))

    # Blueprint 5.3: the asymmetry must be visible. Suburban lines have gaps only
    # after midnight; the low-density branch genuinely has daytime ones.
    print("\ntraffic-gap start band by corridor (the Blueprint 5.3 asymmetry):")
    bands = defaultdict(Counter)
    for w in wins:
        if w["window_type"] == "traffic_gap":
            bands[w["corridor_id"]][band_of(w["start_min"])] += 1
    for cor in net.corridors():
        print("  %-8s %s" % (cor, dict(sorted(bands[cor].items())) or "{}  <- relies on corridor blocks"))

    print("\nthe midnight-straddling suburban window (TRL-AJJ-UP_SUB, %s):" % config.WEEK_START)
    for w in wins:
        if (w["block_section_id"] == "TRL-AJJ-UP_SUB" and w["date"] == config.WEEK_START.isoformat()
                and w["window_type"] == "traffic_gap"):
            print("  %s -> %s  (%d min, one window not two halves)"
                  % (w["start_time"], w["end_time"], w["duration_min"]))

    # FR-03: access already claimed elsewhere must not be re-offered.
    day0 = config.WEEK_START.isoformat()
    probe = [w for w in wins if w["block_section_id"] == "CGL-WJ-SINGLE" and w["date"] == day0]
    we2 = WindowEnumerator(net, existing_occupancy=[("CGL-WJ-SINGLE", day0, 0, 1439)])
    after = [w for w in we2.enumerate()
             if w["block_section_id"] == "CGL-WJ-SINGLE" and w["date"] == day0
             and w["window_type"] == "traffic_gap"]
    print("\nFR-03 existing occupancy - CGL-WJ-SINGLE on %s:" % day0)
    print("  %d windows normally; with the day already claimed in BDMS, %d traffic gaps remain"
          % (len(probe), len(after)))
    print("\nwritten -> %s" % os.path.relpath(out, config.ROOT))


if __name__ == "__main__":
    _selfcheck()
