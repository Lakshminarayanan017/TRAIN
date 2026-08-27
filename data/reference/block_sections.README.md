# block_sections.csv — Block section master / graph edges (Data Spec §8.2)

The second reference table in the build order (§12.5), and the one everything else is keyed
to. Blueprint §2.1: *Block section = edge, between consecutive block stations, per line —
where tasks live and where blocks are granted.* Consumed by clustering (§6.1 groups by
block section + line), the detention estimator (line count is decisive), the window
enumerator, and the unified task schema's `block_section_id`.

## Schema (Data Spec §8.2)

| Column | Type | Req | Notes |
|---|---|---|---|
| `block_section_id` | string | yes | `TRL-AJJ-UP`. Primary key. Always `<from>-<to>-<line_id>`. |
| `from_station` / `to_station` | ref | yes | Both must be `is_block_station = true` in `stations.csv`. |
| `line_id` | enum | yes | Part of the key — parallel edges share endpoints and differ only here. |
| `start_km` / `end_km` | float | yes | Chainage of the endpoints along the section's home corridor. |
| `corridor_id` | ref | yes | `MAS-AJJ`. Used only at the monthly horizon (§2.1). |
| `parallel_edges` | list[ref] | yes | Lateral adjacency — the other edges of the same span. Reroute options. |
| `next_sections` | list[ref] | yes | Longitudinal adjacency — cascade delay. |
| `electrified` | bool | yes | `false` on the AJJ–Kanchipuram stretch per §8.2 — but the real line is electrified; see below. |
| `sectional_speed_kmph` | int | yes | Permitted sectional speed on that line. |
| `daily_train_count` | int | yes | Trains per day **on that edge** — see below. |
| `traffic_type` | enum | yes | `suburban` / `trunk` / `freight` / `mixed` / `branch`. |
| `bidirectional_capable` | bool | yes | Can single-line working be instituted here? |
| `monsoon_sensitive` | bool | no | `true` for low-lying stretches. |
| `division_id` | ref | yes | `SR-MAS` throughout the pilot. |

List-valued columns use `;` as the separator, so no field needs CSV quoting.
Booleans are lowercase `true`/`false`, matching `stations.csv`.

## Multigraph construction (Blueprint §2.2)

**67 edges over 23 physical spans**, against the spec's ~60-edge indication in §12.4. The
overshoot is deliberate and is explained under *Revision* below.

Spans run between **consecutive block stations only**. The five remaining stations with
`is_block_station = false` — VJM, VLK, VEU, MAF, TVT, WCN — are spanned over, not split at. This
is why TRL→AJJ is one 26.5 km section rather than two.

| Corridor | `corridor_id` | Spans | Lines per span | Edges |
|---|---|---|---|---|
| Chennai Central – Arakkonam (quadruple trunk) | `MAS-AJJ` | 7 | UP, DN, UP_SUB, DN_SUB | 28 |
| Basin Bridge – Gummidipoondi (freight) | `BBQ-GPD` | 5 | UP, DN | 10 |
| Chennai Beach – Tambaram (saturated suburban) | `MSB-TBM` | 6 | UP, DN, UP_SUB, DN_SUB | 24 |
| Chengalpattu – Kanchipuram – Arakkonam (single line) | `AJJ-CGL` | 5 | SINGLE | 5 |

The four `TRL-AJJ-*` edges are the worked example in Blueprint §2.2 Figure 1 — one block
section, four separately blockable edges, blocking UP leaves three intact.

## Endpoint ordering and km convention

Every span is written **in increasing km order** (`from_station` is the lower chainage), so
`line_id` is the only thing distinguishing parallel edges and the `(from, to, line)` key is
unambiguous. `from_station` is a geographic convention here, **not** a direction of running:
`TRL-AJJ-DN` is the DN line over the TRL–AJJ span, not a DN-direction traversal.

`start_km` / `end_km` follow the home-corridor chainage set in `stations.README.md`. One
consequence is worth stating explicitly, since a naive join will flag it:

> **AJJ carries two chainages.** `stations.csv` records `km_from_origin = 69.0`, its position
> on its primary corridor (the trunk, MAS = 0). On corridor 4, measured from Chennai Beach,
> Arakkonam sits at **127.82**, which is what `TKO-AJJ-SINGLE.end_km` records. Both are correct
> for their own corridor. Per-task positioning uses `start_km`/`end_km` on the edge (§9), never
> the scalar on the node, precisely so this stays consistent.

Since the station master gained `corridor_id`, this is no longer a special case in code. The
validator checks an endpoint's km against the station master **only where the station sits on
its home corridor**; an off-corridor endpoint is trusted to the edge. The hardcoded AJJ
exception the first revision of the validator carried has been deleted.

`TRL-AJJ-*` ends at **68.5**, the spec's anchor value in §8.2, against AJJ's 69.0 station post.

## `next_sections` — longitudinal adjacency

Defined as the block sections incident on `to_station` that are **not** in this edge's own
parallel group (those are `parallel_edges`, a different relation — Blueprint §2.3 warns that
conflating them either loses reroute options or double-counts delay). Line continuity is
preserved where the adjoining span carries the same `line_id`; where it does not, the
plausible running connection is used instead:

- `TKO-AJJ-SINGLE` → `TRL-AJJ-UP;TRL-AJJ-DN` — traffic off the branch joins the main pair at
  Arakkonam, not the suburban pair.
- `MAS-BBQ-UP` → `BBQ-PER-UP;BBQ-TNP-UP` — Basin Bridge is where the northern freight line
  diverges, so the trunk main lines have two successors. The suburban pair has one, since EMU
  services do not continue onto the Ennore road.
- `PON-GPD-*` and `PV-TBM-*` have **empty** `next_sections`: they are the pilot's open ends.

Corridors 3 and 4 are joined to the rest of the graph only through AJJ. The Tambaram–
Chengalpattu stretch is real track but sits outside the four modelled corridors of Blueprint
§5.4, so no edges are emitted for it; corridor 4 begins at CGL. Add that stretch when the
pilot is extended, and `PV-TBM-*` gains successors.

## `daily_train_count` is per edge

Trains traversing **that one line** per day. The spec's §8.2 example gives 210 for
`TRL-AJJ-UP`; on a per-edge reading that is far too heavy for the outermost trunk section, so
210 is taken here as the **section** figure and split across its four edges — UP 70, DN 70,
UP_SUB 35, DN_SUB 35 — which sums to the anchor exactly while staying realistic (mail, express
and goods on the main pair; roughly half-hourly EMU services on the suburban pair).

The resulting shape is the asymmetry Blueprint §5.3 says must be visible: suburban edges near
Beach and Egmore carry ~200 trains a day and have no daytime gaps at all, while the single-line
branch carries 14–18 and genuinely does — which is why §5.4 gives the branch a mid-morning
corridor block and the suburban corridor a 00:30 one.

## `bidirectional_capable`

`true` on the main UP/DN pairs and on the already-single branch, `false` on the suburban pairs,
which run unidirectional automatic block signalling. This is the field that decides whether
blocking one edge of a double-line span can be worked around or severs the route.

## Data provenance (spec §12.3 "Ground in reality")

Section endpoints, line counts, electrification status, sectional speeds and approximate train
frequencies are grounded in the public Chennai Suburban network — same sources as
`stations.README.md`:

- [West Line, Chennai Suburban](https://en.wikipedia.org/wiki/West_Line,_Chennai_Suburban) — corridor 1
- [South West Line, Chennai Suburban](https://en.wikipedia.org/wiki/South_West_Line,_Chennai_Suburban) — corridors 3 and 4
- [North Line, Chennai Suburban](https://en.wikipedia.org/wiki/North_Line,_Chennai_Suburban) — corridor 2

`monsoon_sensitive` is set from the Oct–Dec northeast monsoon flood history the spec names as
groundable (§12.3): the whole Beach–Tambaram corridor, the Kosasthalaiyar / Ennore creek
stretch on the northern line, and the inner trunk as far as Ambattur across the Cooum and
Otteri drainage. The branch and the outer trunk are `false`.

**Approximate / to verify before a submitted build (spec §7.1 caveat).** Which block stations
bound a section, per-line `sectional_speed_kmph`, and the `daily_train_count` split are
reasoned engineering approximations, not lifted from the Southern Railway working timetable —
the same standing caveat as the station master. `electrified = false` on CJ–TMLP, TMLP–TKO and
TKO–AJJ follows the spec's §8.2 note rather than current status on the ground. These are
illustrative for the pilot; the relative model comparison is the claim, not the absolute
geography.

## Revision — 2026-08-27

Regenerated after an audit of `stations.csv` promoted three crossing stations from halts to
block stations. See `stations.README.md` for the reasoning; the effect here is that three spans
split in two:

| Was | Length | Became |
|---|---|---|
| `MJR-GPD` | 21.0 km | `MJR-PON` (9.0 km) + `PON-GPD` (12.0 km) |
| `MS-GI` | 10.7 km | `MS-MBM` (7.0 km) + `MBM-GI` (3.7 km) |
| `STM-TBM` | 12.0 km | `STM-PV` (6.1 km) + `PV-TBM` (5.9 km) |

**57 edges over 20 spans → 67 edges over 23 spans.** The spec's §12.4 figure of ~60 edges is a
volume estimate, not a constraint, and a 21 km double-line freight section with no intermediate
crossing station is not workable railway. The overshoot is the correct trade.

Two structural improvements came with the regeneration:

- **The generator now reads `stations.csv`.** Station codes, chainage, corridor membership and
  block-station status are no longer restated in `build_block_sections.py`; it cuts spans
  directly from the station master, so the two files cannot drift. Only the per-span attributes
  the station master does not carry — speeds, train counts, electrification, monsoon exposure —
  are held in the generator. Promoting another halt to a block station is now a one-cell edit in
  `stations.csv` plus one entry in the generator's `SPANS` table.
- **`next_sections` is derived, not enumerated.** Same-line continuation along a corridor falls
  out of the span sequence; only the genuine junction links are listed by hand, in
  `JUNCTION_LINKS`, each with the reason it is not simple continuation. Previously all 57 rows'
  successors were written out longhand, which would have silently gone stale the moment a span
  split — and did not, only because the file was regenerated.

`validate_reference.py` gained the check that would have caught the original defect: it now
fails the build if any block station sits strictly inside a span on its own corridor, and it
notes any span over 30 km for review. It also verifies that each corridor's spans chain end to
end with no gap or overlap.

## Revision 3 — verified geography

Regenerated after `stations.csv` was reconciled against published sources (see
`stations.README.md`, *Revision 2*). Because this file is generated from the station master
rather than hand-written, every corrected chainage propagated automatically: corridor 3 now
carries two-decimal km, corridor 4's endpoints moved, and `TKO-AJJ-SINGLE` ends at 127.82.
Edge and span counts are unchanged at 67 / 23 — the corrections moved boundaries, not topology.

## Revision 4 — 2026-08-27, AJJ–CGL branch section lengths corrected

Revision 3's corridor-4 chainage came from the Wikipedia South West Line route map, whose
cumulative undercounts the branch: it put CGL → AJJ at 62.9 km against IndiaRailInfo's measured
**68.82 km**. Regenerated after `stations.csv` was reconciled to IndiaRailInfo point-to-point
rail distances (see `stations.README.md`, *Revision 3*). The three branch sections that were
short are now right: `CJ-TMLP` 9.8 → **12.0 km**, `TMLP-TKO` 6.5 → **7.0 km**, `TKO-AJJ`
10.6 → **13.0 km**; `TKO-AJJ-SINGLE` now ends at 127.82. Topology unchanged at 67 / 23.

**`electrified` on corridor 4 is a spec-versus-reality decision, not a data error.** Data Spec
§8.2 mandates `false` on the AJJ–Kanchipuram stretch; the line is in fact electrified and now
runs EMUs end to end. The spec is followed because it is the build contract, via the single
switch `BRANCH_ELECTRIFIED` in `build_block_sections.py`. Flipping it to `True` makes
`CJ-TMLP`, `TMLP-TKO` and `TKO-AJJ` electrified, which allows TRD tasks onto corridor 4 and
materially changes the merge problem there. The choice belongs to the team, so it is one line.

The quadruple-track configuration of corridor 1 was **confirmed** against the West Line article:
four tracks run to within about 500 m of Arakkonam yard, so modelling all seven trunk spans as
quadruple is correct at this resolution.
