# task_types.csv — Task type catalogue (Data Spec §8.4)

The third reference table in the build order (§12.5). Every row in the unified task schema
(§9) points at one of these through `task_type_id`, and inherits its access mechanism,
nominal effort and restrictions. Read by the duration predictor (§12.2), the clustering
stage, and the compatibility matrix — whose `type_a` / `type_b` columns are refs into this
file, so this table must be stable before `compatibility_matrix.csv` is authored.

## Schema (Data Spec §8.4)

| Column | Type | Req | Notes |
|---|---|---|---|
| `task_type_id` | string | yes | `ENG-RAIL-WELD`. Primary key. Prefix is always the department. |
| `description` | string | yes | Plain-language name shown to officers. |
| `department` | enum | yes | `ENG` / `TRD` / `SNT`. |
| `location_kind` | enum | yes | `edge` / `node` — determines the access mechanism (Blueprint §2.4). |
| `access_required` | enum | yes | `traffic_block` / `power_block` / `disconnection` / `none`. |
| `nominal_duration_min` | int | yes | The cold-start estimate, before any history exists. |
| `min_crew` | int | yes | Floor, not the request — a task may ask for more. |
| `machine_required` | enum | yes | `none` and six machine classes. |
| `night_permitted` | bool | yes | `false` forces daylight — expensive on suburban lines. |
| `monsoon_restricted` | bool | yes | `true` blocks scheduling during the Oct–Dec northeast monsoon. |
| `adjacent_line_speed_restriction_kmph` | int | no | Caution imposed on lines past the worksite. |
| `worksite_length_km` | float | no | Length the caution applies over. |
| `default_periodicity_days` | int | no | Empty for defect-driven work; drives the monthly forecast. |
| `applies_to_asset_type` | enum | no | ★ added — the asset type this work is raised against. Empty = span-based work with no single asset. |
| `routes_consumed` | int | yes | ★ added — station route capacity taken while the task runs. `0` for edge tasks. |

Empty cells are the spec's nulls. Booleans are lowercase, matching the other reference tables.
No field contains a comma, so the file needs no CSV quoting.

## Two columns added beyond §8.4

Both close gaps that block the synthetic task generator, found by tracing §12.2 backwards from
the models to their inputs. Neither replaces a spec column.

**`applies_to_asset_type`.** §9 requires every task to carry both `task_type_id` and `asset_id`,
and the two must agree — a `SNT-POINT-SERVICE` task cannot be raised against a bridge. Nothing
in the original schema said which asset type a task acts on, so `tasks.csv` could not be
generated consistently. All 16 asset types in the §12.1 enumeration are now covered by at least
one task type, and the validator fails the build if any is orphaned: an uncovered asset type
would mean rows in `assets.csv` that no task can ever be raised against.

Four types leave it **empty** — `ENG-DRAIN-CLEAR`, `ENG-TRACK-PATROL`, `SNT-CABLE-LAY`,
`SNT-TELECOM`. This is not missing data: §9 makes `asset_id` nullable precisely for *"span-based
work with no single asset"*, and these are it.

**`routes_consumed`.** Blueprint §2.4 defines the node resource model as *"a station has a route
count, a disconnection consumes some, compatibility rules govern concurrency"*. `route_capacity`
was on the station but nothing said how much a task takes, so node concurrency was uncomputable.
Nine node task types consume 1–3 routes; every edge task consumes `0`.

`SNT-INTERLOCK-TEST` was initially set at 4 and the validator flagged that it could then never
run at Kanchipuram, whose 3 routes are the smallest of any yard. An interlocking test takes the
whole interlocking regardless of station size, so 3 is both correct and schedulable everywhere —
at CJ it consumes the entire station, which is the right behaviour. A fixed integer is a
simplification of "takes all of it"; noted here rather than hidden.

## Composition

**42 rows**, inside the spec's 30–50 target (§12.4).

| Department | Rows | Dominant access |
|---|---|---|
| ENG — Engineering / P.Way | 18 | `traffic_block` (16 of the 16 in the file) |
| TRD — Traction Distribution | 12 | `power_block` (11) |
| SNT — Signal & Telecommunications | 12 | `disconnection` (8) |

That split is the whole point of the project restated as data: three departments, three
different access mechanisms, on the same physical asset base. It is what makes Blueprint §6.3's
access-union escalation table non-trivial — `traffic + power` and `traffic + disconnection` both
occur naturally in this catalogue rather than being contrived for the demo.

The four spec anchors are present verbatim, so the §9.1 sample records and the CMP-018 conflict
in Document 3 resolve against real rows:

| Anchor | Source | Value here |
|---|---|---|
| `ENG-RAIL-WELD` | §8.4 example row | 180 min, 6 crew, caution 30 kmph over 1.0 km |
| `ENG-TAMPING` | §8.5 / CMP-018 | 240 min, 8 crew, `tamper` |
| `TRD-OHE-INSP` | §9.1 sample record | 90 min, 4 crew, `OHE_tower_car` |
| `SNT-POINT-SERVICE` | §9.1 sample record / CMP-018 | 60 min, 3 crew, node, `disconnection` |

## `access_required = none` is deliberate

Seven rows need no block at all: drain clearance, foot patrol, signal lamp checks, relay room
and telecom work, substation maintenance, cable laying along the cess. They still enter the task
pool, still consume crew, and still compete for the same men — but the window enumerator never
has to find them a slot. Without them the optimiser's crew constraints look artificially slack,
and the demand side reads as if every maintenance activity in a division required track access,
which is not true.

## Machines are scarce on purpose

Only 16 of 42 types need a machine, and the heavy P.Way machines are single-purpose:
`tamper` (3 types), `BCM`, `USFD_car`, `rail_grinder`, `ballast_regulator` (1 each), against
`OHE_tower_car` on 9 TRD types. This is what gives Blueprint §7.6's hard machine-transit
constraint something to bite on — one tamper serving the whole pilot cannot be in two corridors
in one night, and `machines.csv` (§8.6) will size the fleet against these counts.

## Caution on adjacent lines

`adjacent_line_speed_restriction_kmph` is set wherever men or plant stand inside the danger zone
of a line that is still open to traffic. This is the field the detention model charges Blueprint
§7.3's "~1.4 minutes per train on parallel lines" against, so two cases are worth stating because
a naive validator flags both:

- **Node tasks can carry a caution.** `ENG-TURNOUT-TAMP`, `ENG-TURNOUT-OVERHAUL`, `ENG-YARD-PWAY`
  and `TRD-OHE-YARD` are node-located, but a tamper working in yard limits genuinely gets trains
  cautioned past it. `worksite_length_km` for these is the yard length (0.2–0.3 km), not a
  section length. The S&T node tasks carry no caution, correctly — a disconnection puts nobody on
  the running line.
- **A caution can accompany a disconnection.** `SNT-SIGNAL-REPLACE` holds only a disconnection,
  yet carries a 30 kmph caution: the line stays open, and the caution order *is* the protection.

## Periodicity

31 of 42 types carry a `default_periodicity_days`; 11 are defect-driven and leave it empty
(rail welding, rail and sleeper renewal, bridge repair, contact wire and insulator renewal, OHE
fault attention, point machine replacement, signal replacement, interlocking testing, cable
work). Blueprint §11.2 splits the monthly forecast into exactly this deterministic / stochastic
pair, so the empty cells are load-bearing, not missing data. Periodicities span 30 days (patrol)
to 1825 days (deep screening), which is what makes the monthly horizon's quota reservation
meaningful rather than uniform.

## Data provenance (spec §12.3 "Ground in reality")

Activity names, departmental ownership, access mechanism and the general shape of periodicities
follow standard Indian Railways permanent-way, traction-distribution and S&T maintenance
practice. The spec classes individual task instances as *synthesise* and this catalogue as
authored reference, so:

**Approximate / to verify before a submitted build (spec §7.1 caveat).** Every
`nominal_duration_min`, `min_crew`, caution value and periodicity in this file is a reasoned
engineering approximation, not lifted from a Southern Railway schedule of dimensions or
maintenance manual. They are internally consistent and correctly ordered relative to one another
— deep screening is the longest job, a lamp check the shortest — and that relative ordering is
the claim. Absolute figures should be confirmed against the division's own schedule before any
submitted build. `nominal_duration_min` in particular is only the **cold-start fallback** the spec
demands in §12.3: on day one the duration model has no history and falls back to the requested
duration plus a fixed buffer, and says so.
