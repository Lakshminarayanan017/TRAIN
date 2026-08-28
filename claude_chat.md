# Working log — data layer build

Running context for this repository. The file was empty when this session started; it is now
the handoff note between sessions. Append at the top of the log, newest first.

## Where the project stands

**PS26027 — AI-Based Automatic Block Planning, Chennai Division (SIH internal hackathon).**
Three source documents in `docs/` are the contract:

| Doc | Role |
|---|---|
| `1_System_Blueprint_Block_Planning.pdf` | Architecture — the network model, the five pipeline stages, the optimiser formulation |
| `2_PRD_and_Data_Specification.pdf` | Requirements (§1–6) and the **build contract for the data layer** (§7–12) |
| `3_Complete_Project_Compendium.pdf` | Narrative, worked scenario, user-facing screens |

The problem, compressed: ENG, TRD and SNT each request track access independently through BDMS.
Nobody merges the requests, so a section that could be taken once for three hours gets taken
three times. The system is a planning layer above BDMS that merges compatible work into single
blocks, ranks what to defer, and costs both sides of the trade-off in weighted train-delay
minutes. It advises; humans sanction.

We are in the **data collection phase**. Data Spec §12.5 sets the build order —
reference data, then the unified task schema, then supply, then history — and §12.4 sets the
volumes. Nothing downstream can start before its input tables exist (§12.2).

## Build status

| Bucket | Table | Spec | Target rows | Status |
|---|---|---|---|---|
| 1 Reference | `stations.csv` | §8.1 | ~30 | **done** — 31, web-verified 27 Aug |
| 1 Reference | `block_sections.csv` | §8.2 | ~60 | **done** — 67 over 23 spans |
| 1 Reference | `assets.csv` | §8.3 | 2,000–5,000 | **done** — 2,419 |
| 1 Reference | `task_types.csv` | §8.4 | 30–50 | **done** — 42, +2 columns |
| 1 Reference | `compatibility_matrix.csv` | §8.5 | 30–40 | **done** — 40 |
| 1 Reference | `machines.csv` / `crews.csv` | §8.6 | ~50 / ~120 | **done** — 49 / 120 |
| 2 Demand | `tasks.csv` | §9 | ~4,000 | **done** — 4,000, 283 pending |
| 3 Supply | `train_paths.csv` | §10.1 | ~15,000 | **done** — 6,378 |
| 3 Supply | `goods_forecast.csv` | §10.2 | — | **done** — 1,344 |
| 3 Supply | `corridor_windows.csv` | §10.3 | ~200 | **done** — 101 |
| 4 History | `block_executions.csv` | §11.1 | ~2,000 | **done** — 2,343 |
| 4 History | `defect_lifecycle.csv` | §11.2 | ~3,000 | **done** — 3,500 |
| 4 History | `detention_log.csv` | §11.3 | ~2,000 | **done** — 1,591 |
| 4 History | `emergency_events.csv` | §11.4 | ~150 | **done** — 180 |

**All four buckets are complete**, and the planning system in `src/` is built on top of them.
The project is now in **step 4, evaluation** — running the coordinated planner against the
modelled current practice over seeded weeks and reporting the difference honestly.

`train_paths.csv` landed at 6,378 rows against a §10.1 target of ~15,000. The table is one row
per train per section per running day for the trains actually named in the pilot's four
corridors; reaching 15,000 would mean inventing services that do not run. Flagged rather than
padded.

## Conventions settled so far

These were decided while building the tables above. Keep them; they are load-bearing across
files.

- **Provenance claims must match what was actually done.** The first pass cited Wikipedia in the
  READMEs while writing the geography from general knowledge. If a README lists a source, that
  source was read. Anything reasoned rather than sourced is now stated as such, per-field.
- **Every CSV gets a `<name>.README.md`** next to it recording schema, construction, and a
  provenance section separating what is grounded in the real Chennai network from what is a
  reasoned approximation. Data Spec §12.3 divides the data into *ground in reality* /
  *synthesise* / *expert validation required*, and §7.1 requires the approximations be flagged.
- **No CSV needs quoting.** No field contains a comma. List-valued fields use `;`.
- **Booleans are lowercase** `true` / `false`, matching the spec's JSON and prose.
- **Empty cell = the spec's null.** It is never a placeholder for missing work.
- **`km_from_origin` is per home corridor**, and the corridor is now on the row.
  `corridor_id` + `km_origin_ref` make the convention machine-readable: trunk measures from
  MAS = 0, the other three corridors from MSB = 0. AJJ carries 69.0 as a node and 122.7 on
  corridor 4; the validator resolves this from the data (check an endpoint's km only where the
  station is on its home corridor) rather than from a hardcoded exception.
- **`is_junction` records the real network, not the modelled graph.** Five stations are
  junctions in reality but have degree ≤ 2 in the pilot, because their other arms lie outside
  Blueprint §5.4's four corridors. The validator reports these as notes, never errors. The
  reverse — degree > 2 flagged `false` — is an error.
- **The generator reads `stations.csv`.** Geography is stated once. Promoting a halt to a block
  station is a one-cell edit plus one generator entry; spans, `parallel_edges` and
  `next_sections` all fall out.
- **Block sections are written in increasing km order**, so `line_id` alone separates parallel
  edges. `from_station` is geography, not a direction of running.
- **Absent compatibility pair = `parallel`.** The matrix is a list of exceptions, not a
  whitelist. Argued at length in `compatibility_matrix.README.md`; the clustering code must
  implement this default or the 40 rules will forbid everything.
- **`validated_by` stays blank** on every compatibility rule until a real officer signs it. The
  validator fails the build if any row is filled in.
- **`rule_id` values are stable — append, never renumber.** The Compendium's conflict screen
  names `CMP-018` on screen, so the identifiers are user-facing.
- **Derived fields are never emitted into source data.** §9 stars eight fields as
  system-computed; `tasks.csv` omits all eight and the validator fails if any appears. Writing
  a `predicted_duration_p80` next to the data the duration model trains on makes every later
  accuracy figure circular.
- **Synthetic features must carry real correlation.** Anything a model is meant to learn has to
  actually be in the data — `assets.csv` builds tonnage/age/criticality into `failure_count_12m`
  on purpose, and says so. Independently drawn features would train a model that looks like it
  works and has learned nothing. The flip side is stated in every generated README: a model
  fitted on this data recovers the generator's assumptions, so accuracy figures measure the
  pipeline, never the railway.
- **Seed is 26027** (the problem statement number) in every generator, per §12.5.
- **Fixed seed for anything synthetic** (§12.5). Nothing generated may shift between rehearsal
  and demonstration.

## Table sizes are not all meant to be large

A recurring question, worth settling once. §12.4 splits the data layer into two kinds of table
and they are sized on completely different logic:

- **Catalogues** — stations, block sections, task types, compatibility rules, machines, crews,
  corridor windows. Small because they are *closed sets*. There are 30 stations in the pilot and
  only so many kinds of maintenance activity; padding them means inventing railway that does not
  exist. §8.5 flags the 40-row compatibility matrix **"HIGHEST VALUE PER ROW"** — those 40
  hand-reasoned rules are worth more than every generated row in the repository.
- **Populations** — assets, tasks, train paths, and all four history tables. Large because they
  are samples from a distribution, and because the models need volume to fit against.

Everything built so far sits on its §12.4 target. The ML training volume is almost entirely in
tables not yet built: roughly **26,150 rows still to come** against ~5,100 built.

## Checks

```bash
python data/generator/generate_all.py     # rebuild every CSV, then run all four validators
python data/checks/validate_reference.py
python data/checks/validate_demand.py
python data/checks/validate_supply.py
python data/checks/validate_history.py
python -m src.evaluate --seeds 5          # coordinated vs current practice
```

Referential integrity, enumeration conformance and domain rules across the reference tables,
plus the Data Spec §9.1 integration test: the three sample records
(`ENG-RAIL-WELD` 180 + `TRD-OHE-INSP` 90 + `SNT-POINT-SERVICE` 60) must form a valid merge with a
**critical path of 180 minutes**, not the naive sum of 330 — the Blueprint §6.4 shape. Currently
passes clean. Extend the script as each new table lands.

`data/generator/build_block_sections.py` regenerates `block_sections.csv` from the corridor
constants; hand-editing 67 rows across 16 columns is not worth the risk.

## Open questions for the team

0. **Pilot scope is 30 stations, not the full 160-station division.** Every upgrade so far has
   improved the pilot's fidelity rather than extending its footprint. KPD and JTJ stay out
   (spec §7.1 names them, but they would create sections with no corridor block pattern defined
   in Blueprint §5.4). Say so if the intent was the full division build — that is a different
   piece of work, not a bigger version of this one.
1. **`daily_train_count` granularity.** Spec §8.2's example gives 210 for `TRL-AJJ-UP`. Read
   per-edge that is far too heavy for the outermost trunk section, so it is treated here as the
   *section* figure and split across the four edges (70/70/35/35) to sum to the anchor exactly.
   Flag if the intent was genuinely per-edge.
   This is now visible downstream. `validate_supply.py` notes `TI-TRL-UP` and `TRL-AJJ-UP` at
   0.3x their anchor — 12 of 67 edges sit below 0.5x — while the supply layer matches the
   reference layer in aggregate (6,378 paths against a 6,312 anchor, 1.01x) and per corridor
   (MAS-AJJ 0.77x, the other three between 1.15x and 1.56x). It is the 70/70/35/35 split on the
   outer trunk edges, not a shortfall in the table. It matters because `detention.py` costs a
   block from the paths alone — `daily_train_count` only ever reaches it as a feature of the
   untrained residual model — so a daytime block on those two edges is priced off roughly a
   third of the traffic the reference layer says runs there, and is understated accordingly.
2. **Tambaram–Chengalpattu is not modelled.** Real track, but outside the four corridors named
   in Blueprint §5.4, so corridors 3 and 4 connect only through Arakkonam. Intentional; revisit
   if the pilot scope widens.
3. **Corridor 4 chainage has a 6 km inconsistency.** Published South West Line chainage puts AJJ
   at 122.71 km from Beach; IndiaRailInfo's CJ-TKO-AJJ hops sum to ~33 km against the 26.89 km
   those anchors imply. TMLP and TKO are placed proportionally. Immaterial on a 14-train branch,
   but unresolved.
4. **`electrified` on corridor 4 is spec-versus-reality.** §8.2 mandates `false` on the
   AJJ-Kanchipuram stretch; the line is actually electrified and runs EMUs end to end. Spec is
   followed via the `BRANCH_ELECTRIFIED` switch in the generator. Flipping it lets TRD tasks onto
   corridor 4 and changes the merge problem there. Team's call.
5. **The compatibility matrix needs an officer.** Spec §12.3 lists it under *expert validation
   required*. Forty unsigned rules is the honest state, and the demo should say so rather than
   present it as settled practice.

## Log

### 2026-08-28 — step 4, evaluation

The harness ran end to end for the first time and three defects came out of it. All three were
measurement faults rather than planner faults, and two of the three flattered our own system.

- **A failed solve was being scored as a brilliant week.** On seed 26027 at a 15 s ceiling
  CP-SAT returned `UNKNOWN` — no incumbent at all — and `_extract` handed back an empty block
  list. An empty plan validates clean, occupies zero line-hours and causes zero detention, so
  the week averaged into the results as a crushing win on both headline metrics. `validate()`
  now fails a result whose status is neither `OPTIMAL` nor `FEASIBLE`, and fails an empty plan
  offered candidates. The harness discards such a seed **across every arm**, so the paired
  comparison stays paired, and prints what it discarded and why.
- **The corridor ceiling was enforced on the optimiser only.** `MAX_BLOCKS_PER_CORRIDOR_WEEK`
  is 40; the baseline, booking through the ledger, had no such check and was taking **64 blocks
  on MAS-AJJ** against the optimiser's 40. The shortfall then showed up as tasks the
  coordinated planner had failed to complete. The ceiling is a policy on the railway, not a
  property of the solver, so it now lives in `ResourceLedger` and binds both planners.
- **Deadlines were being applied asymmetrically, the other way.** The baseline refused any
  window past a task's `deadline`; the optimiser bars only `safety_deadline`, the
  safety-critical subset. Current practice was being held to the stricter rule. Ordinary work
  that runs late is backlog cost, not a constraint breach, so the baseline now bars a window
  only for safety-critical work — which moves the numbers *against* us, and is correct.

**What the corrected comparison actually says** (3 seeds, 60 s ceiling; the 30-seed run is what
counts):

| | baseline | coordinated | |
|---|---|---|---|
| weighted detention (min) | 4,543 | 1,372 | **−70%**, better in 3 of 3 weeks |
| merge rate | 13.5% | 26.4% | **+95%** |
| tasks completed | 120.3 | 136.7 | **+14%** |
| line-minutes per task done | 130.9 | 118.4 | **−9.6%** |
| work per line-minute | 96.2% | 105.9% | over 100% — parallel work in one possession |
| line occupation (hours) | 262.6 | 269.6 | **+2.6%, worse** |

The headline metric goes the wrong way, and that is the honest result rather than a bug. The
coordinated planner is not buying back corridor time; it is doing **14% more work in the same
corridor time**. Raw occupation is not comparable between two arms that completed different
amounts of work, so the report now says so in place of a bare "worse", and the comparable
figure is occupation per task done. Anyone presenting this should lead with detention and
occupation-per-task, never with raw occupation.

One number still to answer for: **new access requested is up 122%** (16.3 → 36.3 windows). The
optimiser reaches outside the corridor pattern far more readily than current practice does, and
each of those needs fresh sanction. `LAMBDA_ACCESS` is 60 and is evidently not pricing that
properly. Open.

Renamed `block_utilisation_pct` to `work_per_line_minute_pct` across `metrics.py` and
`evaluate.py`. The old name invited a reader to see a figure over 100% as a bug; exceeding 100%
is the whole point, being what parallel work in one possession looks like.

### 2026-08-27
- Read all three source documents; established the build order and volumes from Data Spec §12.
- Built `block_sections.csv` (§8.2) — 57 edges over 20 spans across the four pilot corridors,
  with a generator script and a provenance README.
- Authored `task_types.csv` (§8.4) — 42 types, ENG 18 / TRD 12 / SNT 12, carrying the four
  anchors named in the spec (`ENG-RAIL-WELD`, `ENG-TAMPING`, `TRD-OHE-INSP`,
  `SNT-POINT-SERVICE`).
- Authored `compatibility_matrix.csv` (§8.5) — 40 rules, `CMP-018` reproduced verbatim. Added
  `CMP-039` / `CMP-040` so the documented §9.1 merge candidate resolves against real rules
  rather than the permissive default.
- Added `data/checks/validate_reference.py`; passes clean.
- **Audited and upgraded `stations.csv`, then remastered downstream.** Three defects found:
  (a) PON, MBM and PV were recorded as halts despite bounding spans of 21.0, 10.7 and 12.0 km —
  promoted to block stations, PON's `route_capacity` raised 3 → 4 for its crossing loop;
  (b) `km_from_origin` had no recoverable origin with both MAS and MSB at 0.0 — added
  `corridor_id` and `km_origin_ref`; (c) no `division_id` while `block_sections.csv` had one.
  Regenerated `block_sections.csv` (57/20 → **67 edges over 23 spans**), rewrote the generator
  to read the station master instead of restating it, and derived `next_sections` from the span
  sequence with only genuine junction links listed by hand.
  `task_types.csv` and `compatibility_matrix.csv` carry no geography and needed no change.
- Built `tasks.csv` (§9) — 4,000 rows, 283 pending over 69 locations, **53 locations with two
  or more departments pending and 17 with all three**. Asset draw is weighted by failure
  history, criticality and tonnage, so work clusters onto busy track; uniform arrival would give
  ~3 per location and leave almost nothing to merge. The three §9.1 sample records are verbatim
  and resolve against real assets. Two more cross-table bugs caught: `SNT-LC-GATE` tasks lost
  their asset because level crossings are ENG-owned but S&T-maintained for the gate (fixed — a
  task keeps its asset when its type declares it acts on that type), and a generated id collided
  with a §9.1 record.
- **Found a contradiction inside the spec.** §9.1 places `TRD-2026-01188` at km 40.00–44.00 on
  `TRL-AJJ-UP`, but §8.2 starts that section at km 42.0. Kept verbatim rather than clamped —
  editing the record would make the spec's own integration test pass by changing the test.
  Reported as a validator note. Needs a ruling from whoever owns the spec.
- **Grounded the geography against published sources.** Fetched the three Chennai Suburban line
  articles plus the Arakkonam and Kanchipuram station pages and IndiaRailInfo. Corrected nine
  fields — the worst being Manavur's code, which was `MVLR` and is actually **`MAF`** — added
  Wimco Nagar, fixed Perambur to 5.0 km, and switched corridor 2's chainage origin from Beach to
  Chennai Central. Confirmed the trunk anchors (`MAS=0`, `TRL=42`, `AJJ=69`), the quadruple
  configuration, and — pleasingly — that AJJ's 8 platforms and CJ's 3 tracks matched the
  `route_capacity` values that had only been reasoned. All four generators regenerated off the
  corrected master with no hand-editing.
- **Verified the reference layer against §12.2 before proceeding.** Traced each model back to
  its inputs. Task density checks out — 23 spans + 14 yard nodes = 37 locations, ~300 pending
  gives 8.1 per location, inside Blueprint §6.2's 5–20. Found two real gaps in `task_types.csv`:
  no link from a task type to the asset type it acts on (blocks `tasks.csv` generation, since §9
  needs both `task_type_id` and `asset_id` to agree), and no `routes_consumed` (Blueprint §2.4's
  node resource model was uncomputable). Added both columns.
- Built `assets.csv` (§8.3) — 2,413 rows, fixed seed, densities per line-km. Tonnage, age and
  criticality drive `failure_count_12m`: highest tonnage quartile shows 1.43 mean failures
  against 0.35 in the lowest, monotone across criticality A/B/C. The validator's new
  asset-to-task cross-check caught that yard OHE and yard ballast were unsited, leaving
  `TRD-OHE-YARD` and `ENG-YARD-PWAY` with no asset to be raised against.
- Built `machines.csv` / `crews.csv` (§8.6) — 49 availability windows over 17 machines, and 120
  crews / 993 men. `TAMP-SR-07` at AVD is the spec's own §8.6 example row. The machine table is
  keyed `(machine_id, available_from)`: §8.6 calls the field an *availability calendar* and §12.4
  wants ~50 rows, which only reconciles with a realistic sub-twenty fleet if a row is a window
  rather than a machine. Gaps between windows are what make the transit constraint bite.
- **Second cross-table bug caught by generation, same class as the unsited yard assets.** The
  first crew establishment rotated archetypes by base index and never reached the renewal,
  inspection, substation and telecom archetypes — leaving ten task types with nobody qualified
  to do them, while every individual crew row was valid. Fixed with explicit per-archetype
  counts; the validator now fails the build on any task type with zero qualified crews, any
  machine class in `task_types` that is absent from the fleet, and any day-only crew carrying a
  night allowance.
- Remastered the validator: corridor-aware chainage (hardcoded AJJ exception deleted), a check
  that no block station sits inside a span, corridor continuity, and errors split from notes so
  deliberate pilot-boundary departures stay visible instead of being suppressed.
