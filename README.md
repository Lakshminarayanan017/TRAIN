# AI-Based Automatic Block Planning — Chennai Division

SIH internal hackathon project **PS26027**.

Three railway departments — Engineering (P.Way), Traction Distribution and Signal
& Telecommunication — independently request track access for maintenance through
BDMS. Nobody merges those requests, so a corridor that could be taken once for
three hours is taken three times. This system pools all three departments'
pending work, scores it by risk, matches it against real corridor availability,
packs compatible co-located jobs into shared blocks, routes the result through
human approval, and re-plans when reality breaks the schedule.

**The system advises; humans sanction.** No block is authorised without
departmental approval and operations sanction, BDMS remains the system of record,
and every officer-facing score decomposes into named factors.

The three specification documents live in [`docs/`](docs/) and are the build
contract: the System Blueprint, the PRD & Data Specification, and the Compendium.

---

## Quick start

```bash
pip install networkx ortools
```

```bash
python data/generator/generate_all.py     # rebuild every CSV, then validate
```

```bash
python -m src.evaluate --seeds 5          # coordinated vs current practice
```

Every module runs standalone and prints a self-check that demonstrates the
Blueprint property it is responsible for:

```bash
python -m src.network       # the multigraph, reroute options, never-sever
python -m src.detention     # night-versus-day block economics
python -m src.windows       # gap detection, the midnight-straddling window
python -m src.clustering    # merge candidates, the Data Spec 9.1 test
python -m src.optimizer     # a full weekly plan, hard constraints validated
python -m src.baseline      # current practice, modelled honestly
python -m src.scenario      # seeded independent weeks
```

---

## The data layer — four buckets

Every dataset falls into one of four buckets (Data Spec §7). Naming the bucket
says why the data exists and what breaks without it.

| Bucket | Question | Contents |
|---|---|---|
| **Reference** | what exists on the ground? | 31 stations, 67 block sections over 23 spans, 2,432 assets, 42 task types, 40 compatibility rules, 17 machines, 120 crews |
| **Demand** | what work is pending? | 4,000 tasks on the unified schema |
| **Supply** | when is the corridor free? | 6,378 train paths, 1,344 goods forecasts, 101 corridor windows |
| **History** | what happened last time? | 2,343 block executions, 3,500 defect lifecycles, 1,591 detention records, 180 emergencies |

Most projects collect demand and supply and stop. Reference data makes merging
possible; history makes the machine learning possible.

### What is real and what is modelled

Stated plainly, because an evaluator who spots an unstated assumption discounts
everything else (Data Spec §12.3):

- **Real.** Station names, codes and chainage; line counts and electrification;
  block-section geography; the identities, types, priorities and running days of
  the named trains, with their real Chennai departure times where verified.
  Corridor distances are reconciled against published rail distances — the
  Chengalpattu–Arakkonam branch is 68.8 km and the data says so.
- **Computed.** Per-section train timings, from origin anchor plus
  length ÷ speed. Never copied from a timetable that could be stale.
- **Grounded but modelled.** Suburban headways, port-bound freight patterns on
  the northern line, the Oct–Dec monsoon, the corridor-block pattern.
- **Synthetic.** Individual tasks, assets, crew and machine calendars, and all
  history — because **no system in service records them**. That is precisely why
  the field application exists, and collecting this data is the project's most
  defensible contribution independent of the optimiser.

Every table carries a README stating its own provenance. Four validators
(`data/checks/`) enforce referential integrity, domain rules and the properties
the models depend on; `generate_all.py` rebuilds everything from a fixed seed and
runs all four.

---

## The planning system

```
network → windows → clustering → optimiser → plan
                        ↑                       ↓
                    detention ────────── evaluation ← baseline
```

| Module | Responsibility |
|---|---|
| [`src/network.py`](src/network.py) | The multigraph (Blueprint §2). Parallel edges keyed by line, lateral vs longitudinal adjacency kept distinct, reroute feasibility, single-line capacity, never-sever. Validates the reference layer at load. |
| [`src/windows.py`](src/windows.py) | Candidate windows (§5). Corridor blocks read directly, traffic gaps detected cyclically so the midnight-straddling window survives whole, requested access for urgent work, goods risk attached, access claimed elsewhere subtracted. |
| [`src/detention.py`](src/detention.py) | The analytical cost core (§7.3, §2.5). Held / rerouted / cancelled trains, adjacent-line caution over the worksite length, one-hop cascade, single-line working, finite reroute capacity. Every estimate decomposes into named factors; a learned residual attaches later. |
| [`src/clustering.py`](src/clustering.py) | Merge candidates (§6). Compatible cliques up to size five, critical-path duration, access-type union with escalation, per-department crew profile. Singletons always emitted. |
| [`src/optimizer.py`](src/optimizer.py) | The weekly CP-SAT optimiser (§7). Set-packing over (candidate, window) pairs with every hard constraint at instance level, a greedy warm start, and post-solve validation of its own output. |
| [`src/baseline.py`](src/baseline.py) | Current practice (FR-32), booking through a shared ledger so both planners obey identical constraint semantics. |
| [`src/evaluate.py`](src/evaluate.py) | The counterfactual harness (§12): seeded weeks, paired comparison, ablations, honesty statement. |

### It runs with no trained model

The four ML models are not required for a plan. Duration falls back to requested
plus a fixed buffer, escalation to a rule-based hazard, and detention needs no
training data at all — the analytical estimate stands and the learned residual is
zero (Blueprint §8.5). The system works on day one and improves, rather than
requiring a training set before it can run.

### Some properties worth checking yourself

Each is printed by the module's self-check, not asserted here:

- Blocking one line of the four-line Tiruvallur–Arakkonam span leaves three open;
  blocking all four is refused as severing the section.
- A night block averages **35** weighted delay-minutes against **1,659** by day
  across all 67 edges — night is roughly **48× cheaper**, which is the economics
  the entire system rests on.
- The saturated suburban corridor has usable gaps only after midnight; the
  single-line branch genuinely has daytime ones. That asymmetry is why the
  corridor pattern places suburban blocks at 00:30 and branch blocks mid-morning.
- The Data Spec §9.1 worked example — an ENG rail weld, a TrD OHE inspection and
  an S&T point service at Tiruvallur — is discovered as one three-department
  candidate with a 180-minute critical path.
- In the history, severity-1 defects escalate *less often* than minor ones,
  because urgent work is attended fastest. A model that ignores this learns that
  IMDT is safe. The survival framing exists to see through it.

---

## Honesty statement

Results are on synthetic data with parameters chosen by the team. The baseline is
a model of current practice, not measured current practice, and the compatibility
matrix is unvalidated by railway officers. **Absolute numbers are illustrative;
the relative comparison is the claim.** The assertion is not "Chennai Division
will save N hours" but: under identical conditions, with identical constraints,
crews and windows, coordinated planning dominates independent planning — and here
is by how much, with what spread, and why.
