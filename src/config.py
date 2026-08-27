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

# --- reproducibility ---------------------------------------------------------
RANDOM_SEED = 26027
