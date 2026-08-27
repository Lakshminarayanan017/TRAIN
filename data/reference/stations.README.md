# stations.csv — Station master (Data Spec §8.1)

The first reference table in the build order (§12.5). One row per station node in the
network graph (§2.1: *Station = node, with code, km from origin, block-station flag, yard
flag, route capacity*). Consumed by clustering, the node resource model, the duration
model's section features, and by `data/generator/build_block_sections.py`, which cuts the
graph edges directly from this file rather than restating the geography.

## Schema (Data Spec §8.1, plus three added columns)

| Column | Type | Req | Notes |
|---|---|---|---|
| `station_code` | string | yes | Indian Railways abbreviation, e.g. `TRL`. Primary key. |
| `station_name` | string | yes | e.g. `Tiruvallur`. |
| `km_from_origin` | float | yes | Chainage in km from the origin named by `km_origin_ref`. |
| `is_block_station` | bool | yes | `true` = defines a block-section boundary; `false` = an intermediate halt that a block section spans over. |
| `has_yard` | bool | yes | `true` = node-located tasks (S&T disconnections, yard P.Way) can occur here. |
| `route_capacity` | int | no | Running lines / routes through the node; a disconnection consumes some. |
| `is_junction` | bool | yes | `true` for nodes of degree > 2 (Blueprint §2.4) **in the real network** — see below. |
| `corridor_id` | ref | yes | ★ added — the station's home corridor, one of the four in Blueprint §5.4. |
| `km_origin_ref` | ref | yes | ★ added — the station code `km_from_origin` is measured from. |
| `division_id` | ref | yes | ★ added — `SR-MAS` throughout the pilot. |

Booleans are lowercase `true`/`false` to match the spec's JSON/prose convention. No field
contains a comma, so the file needs no CSV quoting.

★ The three added columns are not in the §8.1 field list. They are additive, not
substitutive — every spec column is still present and unchanged in meaning.

## Pilot scope — the four modelled corridors (Blueprint §5.4)

31 stations (spec target: ~30 pilot / ~160 full division), grouped by `corridor_id`. **Bold**
= `is_block_station = true`, so it can bound a block section; the rest are halts that a
section spans over.

1. **`MAS-AJJ`** — Chennai Central – Arakkonam (quadruple trunk), 12 stations:
   **MAS**, **BBQ**, VJM, **PER**, VLK, **ABU**, **AVD**, **TI**, VEU, **TRL**, MAF, **AJJ**
2. **`BBQ-GPD`** — Basin Bridge – Gummidipoondi (freight, Ennore/Chennai Port), 7 stations
   plus the shared BBQ endpoint: **TNP**, TVT, WCN, **ENR**, **MJR**, **PON**, **GPD**
3. **`MSB-TBM`** — Chennai Beach – Tambaram (saturated suburban), 7 stations:
   **MSB**, **MS**, **MBM**, **GI**, **STM**, **PV**, **TBM**
4. **`AJJ-CGL`** — Chengalpattu – Kanchipuram – Arakkonam (single line), 5 stations plus the
   shared AJJ endpoint: **CGL**, **WJ**, **CJ**, **TMLP**, **TKO**

BBQ and AJJ are shared endpoints; each carries its **primary** corridor in `corridor_id`
(both on the trunk), which is also the corridor its `km_from_origin` is measured along.

Katpadi (KPD, 129 km) and Jolarpettai (JTJ, 213 km) — named as example codes in spec §7.1 —
sit beyond corridor 1 and belong to the full 160-station division build. They are deliberately
excluded: extending the trunk past AJJ would create block sections with no corridor block
pattern defined for them in Blueprint §5.4, which is worse than a short trunk.

## km_from_origin convention

Indian Railways sets km posts per line from that line's own zero, so `km_from_origin` is the
station's chainage along its **home corridor**, and `km_origin_ref` names that zero:

| `corridor_id` | `km_origin_ref` | Why |
|---|---|---|
| `MAS-AJJ` | `MAS` | Trunk, measured from Chennai Central. |
| `BBQ-GPD` | `MAS` | The North Line route map is chainaged from Chennai Central MMC. |
| `MSB-TBM` | `MSB` | Matches the published suburban chainage. |
| `AJJ-CGL` | `MSB` | South-western loop, also Beach-referenced. |

A junction shared between two corridors carries a single value on its primary corridor
(AJJ = 69.0 on the trunk, not its 122.71 south-western-loop chainage). The off-corridor
chainage lives on the edge that needs it, in `block_sections.csv` — `TKO-AJJ-SINGLE` ends at
122.71. Per-edge positioning of tasks uses `start_km`/`end_km` there (§8.2), never this scalar.

This honours the spec's anchor examples: **TRL = 42.0** and **AJJ = 69** (≈ the 68.5 end_km of
block section `TRL-AJJ-UP`).

## `is_junction` records the real network, not the modelled graph

Blueprint §2.4 defines a junction as a node of degree greater than two. Five stations are
flagged `is_junction = true` but have a lower degree in the pilot graph — MAS (1), MSB (1),
CGL (1), MS (2), AJJ (2) — because the arms that make them junctions run outside the four
modelled corridors. Arakkonam is the clearest case: four major lines meet there (Mumbai–Chennai,
Chennai–Bangalore, the West Line, and the Chengalpattu branch), of which the pilot models two.

The flag is deliberately left as **real-world truth**. Rewriting it to match the pilot graph
would be recording a modelling artefact as railway fact, and the moment the pilot extends it
would silently become wrong. `validate_reference.py` reports each mismatch as a **note** rather
than an error. The reverse case — a station of degree > 2 flagged `false` — **is** an error.

## Revision 2 — 2026-08-27, verified against published sources

The first revision's provenance section cited three Wikipedia pages, but the data had been
reconstructed from general knowledge of the network rather than read from them. That gap is now
closed: the pages were fetched and every value reconciled against them.

| Field | Was | Now | Source |
|---|---|---|---|
| Manavur `station_code` | `MVLR` | **`MAF`** | station code lookup — the old code was simply wrong |
| `PER` Perambur km | 6.0 | **5.0** | West Line route map |
| `BBQ-GPD` `km_origin_ref` | `MSB` | **`MAS`** | North Line is chainaged from Chennai Central MMC, not Beach |
| `WCN` Wimco Nagar | absent | **added at 15.0 km** | North Line route map |
| `TKO` `station_name` | Thakkolam | **Takkolam** | published spelling |
| `MS`/`MBM`/`GI`/`STM`/`PV`/`TBM` | 4.3 / 11.3 / 15.0 / 17.1 / 23.2 / 29.1 | **4.32 / 11.29 / 15.01 / 17.12 / 23.15 / 29.14** | South West Line station table |
| `CGL`/`WJ`/`CJ` | 59.8 / 81.6 / 95.8 | **59.84 / 81.78 / 95.82** | South West Line table; WJ from hop distances |
| `TMLP`/`TKO` | 108.4 / 116.0 | **105.60 / 112.12** | interpolated between the verified CJ and AJJ anchors |

The trunk anchors the spec depends on — `MAS = 0`, `BBQ = 2`, `VLK = 9`, `ABU = 15`,
`AVD = 21`, `TRL = 42`, `AJJ = 69` — were all **confirmed unchanged**. So was the quadruple
configuration of corridor 1: the fourth line stops about 500 m short of Arakkonam yard, which is
below this model's resolution.

Two reasoned values were **confirmed correct**, and they were the ones most likely to be wrong:
**AJJ has 8 platforms** and **CJ has 3 tracks / 3 platforms**, matching the `route_capacity`
figures that had been estimated rather than looked up.

One earlier suspicion was itself wrong, which is worth recording. The first audit guessed
Pallavaram was misplaced at 23.2 km against a "real ~20.5". The published figure is **23.15** —
the data was right and the audit was not.

Because `build_block_sections.py` reads `stations.csv` rather than restating it, all 67 edges,
2,417 assets and both resource tables regenerated from the corrected master with no hand-editing.
That refactor is what made this pass cheap.

## Revision 1 — 2026-08-27

An audit against `block_sections.csv` found three defects, all fixed.

**1. Three crossing stations were recorded as halts.** `is_block_station` changed
`false` → `true` for:

| Station | Was inside | Span length | Why it must bound a section |
|---|---|---|---|
| **PON** Ponneri | `MJR-GPD` | 21.0 km | A 21 km double-line freight section with no intermediate crossing station cannot work port-bound traffic. |
| **MBM** Mambalam | `MS-GI` | 10.7 km | Major station on the most saturated suburban corridor in the division. |
| **PV** Pallavaram | `STM-TBM` | 12.0 km | Same corridor; 12 km between block boundaries is implausible at EMU headways. |

PON's `route_capacity` was raised 3 → 4, since a block station needs a loop to hold a train
clear of the running line. This split three spans and took the graph from 57 edges over 20
spans to **67 edges over 23 spans**. `validate_reference.py` now fails the build if any block
station sits strictly inside a span on its own corridor, so this cannot recur silently.

**2. `km_from_origin` was not self-describing.** Both MAS and MSB sit at 0.0 and nothing in
the row said which origin applied. `corridor_id` and `km_origin_ref` make it machine-readable,
and the validator now derives the dual-chainage rule from the data rather than a hardcoded
exception.

**3. `division_id` was absent** while `block_sections.csv` carried it. Added for symmetry.

## Where the spec and the network disagree

Two conflicts surfaced when the geography was checked against published sources. Both are
resolved in favour of the **spec**, because it is the written build contract, and both are
recorded here rather than silently reconciled.

**1. The Kanchipuram–Arakkonam stretch is electrified.** Data Spec §8.2 states `electrified` is
*"false only for the AJJ–Kanchipuram stretch"*, and `block_sections.csv` follows that. The
Kanchipuram station article describes the line as fully electrified with EMU services in both
directions, and the Beach–Tambaram–Chengalpattu–Kanchipuram–Tirumalpur–Arakkonam route now
operates as a fully electrified circular route.

The spec value is kept, but it is now a single named switch — `BRANCH_ELECTRIFIED` in
`build_block_sections.py`. Flip it to `True` to follow the network instead. This matters
substantively: an unelectrified branch means TRD tasks cannot occur on three block sections at
all, which changes the shape of the merge problem on corridor 4.

**2. Arakkonam's trunk chainage.** The station article gives 68 km from Chennai Central; the
West Line route map gives 69, and Data Spec §8.2 anchors `TRL-AJJ` ending at 68.5. The
route-map figure of **69.0** is kept, since it is what the spec's own anchor is consistent with.

## What this sample omits

The pilot models **31 stations against a materially denser real network**, and that gap should
be visible rather than implied away. §12.4 sets the pilot at ~30 stations and the full division
at 160, so sampling is the intended design — but these are the specific stations it skips.

The published Beach–Tambaram list carries **20 stations**; corridor 3 models **7**. Omitted:
Chennai Fort, Chennai Park, Parktown, Chetput, Nungambakkam, Kodambakkam, Saidapet,
Pazhavanthangal, Meenambakkam, Tirusulam, Chromepet, Tambaram Sanatorium. Corridor 4 omits
Nathapettai between Walajabad and Kanchipuram. The West Line runs 57 stations to Jolarpettai;
corridor 1 models the 12 as far as Arakkonam.

Every omitted station is a **halt the block sections span over**, not a block boundary that has
been deleted — so the graph is coarser than the railway, but not wrong about it. Adding them is
a matter of extending `CORRIDORS` in the generator and re-running; the span-cutting logic
already handles it, as the PON / MBM / PV promotions demonstrated.

## Data provenance (spec §12.3 "Ground in reality")

**Verified against published sources.** Station names, codes, chainage, platform counts and line
configuration were checked directly against these pages, not reconstructed from memory:

- [West Line, Chennai Suburban](https://en.wikipedia.org/wiki/West_Line,_Chennai_Suburban) — corridor 1 route map and chainage; quadruple as far as Puliyamangalam
- [South West Line, Chennai Suburban](https://en.wikipedia.org/wiki/South_West_Line,_Chennai_Suburban) — corridors 3 and 4, full station table with two-decimal chainage
- [North Line, Chennai Suburban](https://en.wikipedia.org/wiki/North_Line,_Chennai_Suburban) — corridor 2 route map
- [Arakkonam Junction railway station](https://en.wikipedia.org/wiki/Arakkonam_Junction_railway_station) — 8 platforms, four lines meeting, electrified 1982–83
- [Kanchipuram railway station](https://en.wikipedia.org/wiki/Kanchipuram_railway_station) — code CJ, 3 platforms / 3 tracks, 95.82 km
- [IndiaRailInfo](https://indiarailinfo.com/) — branch-line hop distances (Walajabad–Chengalpattu 21.94 km, Walajabad–Kanchipuram 14.1 km) and station codes

**Still reasoned, not sourced.** Everything that is not geography remains an engineering
approximation, and no source was found for any of it: `is_block_station` for minor stations,
`has_yard`, `route_capacity` other than AJJ and CJ, and every per-section attribute in
`block_sections.csv` — sectional speeds, `daily_train_count`, `monsoon_sensitive`,
`bidirectional_capable`.

**Approximate / to verify before a submitted build (per spec §7.1 caveat).** The above must be
confirmed against the current Southern Railway working timetable, which is the only authority
for block-station status, running-line counts and sectional speeds.

The corridor-4 chainage carries a **known 6 km inconsistency**: the published South West Line
chainage puts Arakkonam at 122.71 km from Beach, while IndiaRailInfo's Kanchipuram–Takkolam–
Arakkonam hops sum to about 33 km against the 26.89 km those anchors imply. Tirumalpur and
Takkolam are placed proportionally between the verified CJ and AJJ anchors. On a branch carrying
14 trains a day this changes nothing in the model, but it is unresolved and should not be
presented as settled.

These are illustrative for the pilot; the relative model comparison is the claim, not the
absolute geography.
