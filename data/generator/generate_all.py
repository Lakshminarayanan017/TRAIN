# -*- coding: utf-8 -*-
"""Regenerate the whole data layer, in dependency order, then validate it.

    python data/generator/generate_all.py

Emits every derived CSV in all four buckets from a fixed seed (spec 12.5), so
every teammate and every demonstration run works against byte-identical data.
Exits non-zero if any generator or validator fails.

Three files are **hand-authored inputs**, not generated here, and the generators
read them: reference/stations.csv (8.1), reference/task_types.csv (8.4) and
reference/compatibility_matrix.csv (8.5) - the last being, per the spec, the only
place real railway domain knowledge enters the system. Everything else is derived
from those three plus the documents' pattern rules.

Build order follows spec 12.5: reference -> demand -> supply -> history. Each step
reads the CSVs the steps before it wrote, which is why the order is fixed.
"""
from __future__ import print_function

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = os.path.join(HERE, os.pardir, "checks")

# (script, one-line description of what it emits). Order is dependency-safe.
GENERATORS = [
    ("build_block_sections.py",  "reference/block_sections.csv   (8.2, from stations.csv)"),
    ("build_assets.py",          "reference/assets.csv           (8.3, from block_sections)"),
    ("build_resources.py",       "reference/machines.csv, crews.csv (8.6)"),
    ("build_tasks.py",           "demand/tasks.csv               (9, the unified schema)"),
    ("build_train_paths.py",     "supply/train_paths.csv         (10.1, real train roster)"),
    ("build_goods_forecast.py",  "supply/goods_forecast.csv      (10.2)"),
    ("build_corridor_windows.py","supply/corridor_windows.csv    (10.3, Blueprint 5.4)"),
    ("build_block_executions.py","history/block_executions.csv   (11.1, training set)"),
    ("build_detention_log.py",   "history/detention_log.csv      (11.3)"),
    ("build_defect_lifecycle.py","history/defect_lifecycle.csv   (11.2)"),
    ("build_emergency_events.py","history/emergency_events.csv   (11.4)"),
]

VALIDATORS = ["validate_reference.py", "validate_demand.py",
              "validate_supply.py", "validate_history.py"]


def run(path, label):
    print("  ->", label)
    result = subprocess.run([sys.executable, path], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    out = result.stdout.decode("utf-8", "replace").strip()
    for line in out.splitlines():
        print("     " + line)
    if result.returncode != 0:
        print("\nFAILED: %s (exit %d)" % (os.path.basename(path), result.returncode))
        sys.exit(result.returncode)


def main():
    print("Generating data layer (fixed seed 26027)\n")
    print("Hand-authored inputs (not regenerated): stations.csv, task_types.csv, "
          "compatibility_matrix.csv\n")
    print("Generators:")
    for script, label in GENERATORS:
        run(os.path.join(HERE, script), label)

    print("\nValidators:")
    for v in VALIDATORS:
        run(os.path.join(CHECKS, v), v)

    print("\nAll generators and validators passed. Data layer is complete and consistent.")


if __name__ == "__main__":
    main()
