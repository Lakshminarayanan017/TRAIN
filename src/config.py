# -*- coding: utf-8 -*-
"""Configuration parameters (Blueprint section 13).

Policy lives in config, not code (NFR-08). Divisions differ; these are the
tunable knobs, held in one place so a change is a one-line edit and never a hunt
through the pipeline. Defaults are the Blueprint 13 reference values.
"""
import datetime as dt
import os

# --- paths -------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REFERENCE = os.path.join(DATA, "reference")
DEMAND = os.path.join(DATA, "demand")
SUPPLY = os.path.join(DATA, "supply")
HISTORY = os.path.join(DATA, "history")
DERIVED = os.path.join(DATA, "derived")     # pipeline intermediates, for inspection

# --- window enumeration (Blueprint 5, 13) ------------------------------------
SETUP_MIN = 20            # men and machines onto the track after the last train
CLEARANCE_MIN = 20        # clear, account for tools, certify the line fit
MIN_USABLE_MIN = 60       # below this a window is discarded
HEADWAY_BUFFER_MIN = 0    # optional extra pad around each train occupation
# A newly requested access window - track access asked for outside the pre-planned
# corridor blocks (FR-17). Offered on every edge/day that has no corridor block, so
# urgent work can be fitted; penalised by lambda_access and by its real detention,
# so the optimiser reaches for it only when it pays.
REQUESTED_START_MIN = 60          # 01:00 night slot
REQUESTED_DURATION_MIN = 180

# The planning week the enumerator builds windows for. Seven consecutive dates
# from here; day-of-week joins the train paths and corridor pattern, the date
# joins the goods forecast.
WEEK_START = dt.date(2026, 9, 7)

# --- clustering / merge candidates (Blueprint 6, 13) -------------------------
MAX_CANDIDATE_SIZE = 5    # no genuine block carries ten departments
# geo_key bucket (Data Spec 9): tasks merge only when genuinely co-located. A
# shared possession covers a worksite neighbourhood, not a whole 26 km section,
# so "same block section" is bounded to a km bucket - realistic, and it keeps the
# candidate count tractable. 9.1's three tasks all sit near km 42, one bucket.
GEO_BUCKET_KM = 3.0

# --- detention cost (Blueprint 7.3, 7.4, 2.5, 13) ----------------------------
REROUTE_PENALTY_MIN = 8          # fixed cost of diverting a train to a parallel line
CANCELLATION_PENALTY_MIN = 240   # a train that can be neither held nor diverted
CASCADE_HORIZON_MIN = 45         # a held train delays those following within this reach
CASCADE_DECAY = 0.5              # first-order only: the follower takes this share
# Rerouting is not unlimited. A parallel line already carrying its own traffic can
# absorb only so many diverted trains; beyond that they are held. This is what
# makes a daytime block on a saturated section genuinely expensive, and a night
# one cheap - the difference the whole argument rests on (Blueprint 7.3).
REROUTE_HEADWAY_MIN = 10         # spacing a diverted train needs on the parallel line
# Adjacent-line caution (Blueprint 2.5). Men and plant on one line put the
# parallel lines under a caution order, charged over the WORKSITE length only -
# applying it over a whole 26 km section would swamp the objective.
CAUTION_WORKSITE_KM = 1.0
CAUTION_SPEED_KMPH = 30
# Single-line working on the surviving edge of a double-line section is not free
# (Blueprint 2.5): capacity falls sharply and crossovers are needed at both ends.
SINGLE_LINE_CAPACITY_FACTOR = 0.4

# Delay minutes are weighted by train type (Blueprint 7.4). The balanced column
# is the default; aggressive mirrors how punctuality is officially measured but
# pushed too far it makes freight the dumping ground.
PRIORITY_WEIGHT_PROFILES = {
    "balanced":   {1: 1.8, 2: 1.5, 3: 1.3, 4: 1.1, 5: 1.3, 6: 0.7},
    "aggressive": {1: 3.0, 2: 2.0, 3: 2.0, 4: 1.5, 5: 1.5, 6: 0.3},
}
TRAIN_PRIORITY_PROFILE = "balanced"
PRIORITY_WEIGHT = PRIORITY_WEIGHT_PROFILES[TRAIN_PRIORITY_PROFILE]
GOODS_DELAY_PENALTY = 90         # expected weighted minutes if a forecast rake takes the gap

# --- optimiser (Blueprint 7, 13) ---------------------------------------------
COLD_START_BUFFER_FRAC = 0.15    # stage-1 duration = critical path + fixed buffer (8.5)
LAMBDA_WASTE = 0.4               # penalty per unused window minute - drives merging
LAMBDA_ACCESS = 60               # penalty per block placed outside a corridor block (flagged access)
LAMBDA_FAIR = 25                 # penalty on the busiest crew's night count - spreads nights
WEEKLY_SOLVE_TIME_LIMIT_S = 60   # CP-SAT ceiling for the scheduled run
SAFETY_SCHEDULE_BONUS = 5000     # reward for fitting a safety-critical task before its deadline
MAX_BLOCKS_PER_CORRIDOR_WEEK = 40  # practical ceiling on corridor disruption
TOP_K_CANDIDATES_PER_ANCHOR = 5  # merge candidates kept per worksite per size class
CANDIDATE_TERMINAL_MIN = 6 * 60  # night-shift window: a block starting before 06:00 is a night duty

# --- reproducibility ---------------------------------------------------------
RANDOM_SEED = 26027
