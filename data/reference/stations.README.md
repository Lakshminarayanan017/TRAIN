# stations.csv — Station master (Data Spec §8.1)

The first reference table in the build order (§12.5). One row per station node in the
network graph (§2.1: *Station = node, with code, km from origin, block-station flag, yard
flag, route capacity*). Consumed by clustering, the node resource model, and the duration
model's section features.

## Schema (Data Spec §8.1)

| Column | Type | Req | Notes |
|---|---|---|---|
| `station_code` | string | yes | Indian Railways abbreviation, e.g. `TRL`. Primary key. |
| `station_name` | string | yes | e.g. `Tiruvallur`. |
| `km_from_origin` | float | yes | Chainage in km from the corridor origin (see convention below). |
| `is_block_station` | bool | yes | `true` = defines a block-section boundary; `false` = an intermediate halt that a block section spans over. |
| `has_yard` | bool | yes | `true` = node-located tasks (S&T disconnections, yard P.Way) can occur here. |
| `route_capacity` | int | no | Running lines / routes through the node; a disconnection consumes some. |
| `is_junction` | bool | yes | `true` for nodes of degree > 2 (Blueprint §2.4). |

Booleans are lowercase `true`/`false` to match the spec's JSON/prose convention.

## Pilot scope — the four modelled corridors (Blueprint §5.4)

30 stations (spec target: ~30 pilot / ~160 full division). Grouped by corridor:

1. **Chennai Central – Arakkonam** (quadruple trunk): MAS, BBQ, VJM, PER, VLK, ABU, AVD, TI, VEU, TRL, MVLR, AJJ
2. **Basin Bridge – Gummidipoondi** (freight, Ennore/Chennai Port): BBQ*, TNP, TVT, ENR, MJR, PON, GPD
3. **Chennai Beach – Tambaram** (saturated suburban): MSB, MS, MBM, GI, STM, PV, TBM
4. **Arakkonam – Kanchipuram – Chengalpattu** (single line): AJJ*, TKO, TMLP, CJ, WJ, CGL

`*` = shared endpoint. Katpadi (KPD) and Jolarpettai (JTJ) — named as example codes in
spec §7.1 — sit **beyond** corridor 1 (west of Arakkonam) and belong to the full 160-station
division build, not this pilot's four corridors. They can be added when the trunk is extended.

## km_from_origin convention

Indian Railways sets km posts per line from that line's own zero, so `km_from_origin` is the
station's chainage along its **home corridor**:

- Trunk (corridor 1) and northern (corridor 2): measured from **Chennai Central (MAS = 0)**.
  MAS and Chennai Beach coincide at ~Basin Bridge (both put BBQ ≈ 2 km), so the northern
  corridor's Beach-referenced posts are used directly.
- Southern / south-western (corridors 3 & 4): measured from **Chennai Beach (MSB = 0)**,
  matching the published suburban chainage.

A junction shared between two corridors carries a single value on its primary corridor
(AJJ = 69.0 on the trunk, not its 122.7 south-western-loop chainage). Per-edge positioning of
tasks uses `start_km`/`end_km` in `block_sections.csv` (§8.2), not this scalar.

This honours the spec's anchor examples: **TRL = 42.0** and **AJJ = 69** (≈ the 68.5 end_km of
block section `TRL-AJJ-UP`). Note the single block section TRL→AJJ spans ~27 km over the
intermediate halt Manavur (MVLR) — hence MVLR is `is_block_station = false`.

## Data provenance (spec §12.3 "Ground in reality")

Station names, codes, ordering, junction/yard classification, and km markers are grounded in
the public Chennai Suburban network:

- [West Line, Chennai Suburban](https://en.wikipedia.org/wiki/West_Line,_Chennai_Suburban) — trunk MAS→Arakkonam
- [South West Line, Chennai Suburban](https://en.wikipedia.org/wiki/South_West_Line,_Chennai_Suburban) — Beach→Tambaram→Chengalpattu→Kanchipuram→Arakkonam
- [North Line, Chennai Suburban](https://en.wikipedia.org/wiki/North_Line,_Chennai_Suburban) — Beach→Ennore→Gummidipoondi
- Station codes cross-checked against IndiaRailInfo / Southern Railway station lists.

**Approximate / to verify before a submitted build (per spec §7.1 caveat):** km markers are
rounded to the nearest published value; `route_capacity`, `has_yard`, and `is_block_station`
for minor stations are reasoned engineering approximations, not lifted from the working
timetable. Codes are standard IR abbreviations but should be confirmed against the current
Southern Railway working timetable. These are illustrative for the pilot; the relative model
comparison is the claim, not the absolute geography.
