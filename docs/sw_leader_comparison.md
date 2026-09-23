# Saved leader gameplay: evidence and architectural differences

Audit date 2026-09-23; repository HEAD `975da5e1683f1bb57463cb9478344d0acf379d58`. Read-only analysis of saved replays, not new tournament games. No protected seeds were run. These replays predate the current production baseline and are not matched comparisons against it.

## Reproducible evidence inventory

`simulations/experiments/sw_leader_audit.py` reads all JSON files under `replays/`, deduplicates by episode ID, and saves one analysis per episode plus `summary.json` under `simulations/experiments/results/sw_leader_audit/`. The census contains **132 unique episodes, 264 player records, and five duplicate copies**. Non-replay episode indexes are listed separately. The graph excludes `replays/`; these files were inspected directly. No unobserved leader strategy internals are inferred as facts.

Each episode artifact includes source path, episode ID, available engine/module metadata and configuration, player identity and final reward, NE/SW/SE first unlocked observation, worker counts immediately before/after that observation, daily cash and workforce, crop/species/structure counts by quadrant, animal and structure coordinates, crop tile-hours, workers' physical quadrant-hours, action requests by quadrant/opcode, movement distance outside midnight resets, market requested quantities, and inventory-confirmed harvest increases outside midnight. These files provide the per-replay reconstruction, including ordinary and losing games; this report highlights common patterns and counterexamples.

Reproduction from repository root:

```text
rtk proxy C:/Users/rohit/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe simulations/experiments/sw_leader_audit.py
```

The script also reaggregates P4.1 and asserts its published cash difference. It performs no gameplay, network calls, or production edits.

### Measurement boundaries

- A replay step's action produces that step's observation; action target positions come from the previous observation. Acquisition times below are **first observed unlocked states**. The purchase action belongs to the preceding decision hour: e.g. observed D8H8 means purchase processed from D8H7, barring omitted replay steps. This distinction prevents a one-hour timing error.
- Worker counts include the farmer. Hands are daily hires; changes around hour zero are not permanent workforce growth. Before/after counts may reflect concurrent hiring as well as land purchase.
- Crop utilization excludes empty structures and counts crop state at each recorded hour. A daily table is an hour-23 snapshot, not a daily peak. Structural occupancy is listed separately. Unlike our reserved-port policy, some opponents cultivate all 25 physical quadrant tiles; the engine does not universally reserve one tile as uncultivable.
- “Worker quadrant-hours” is physical location, **not home-zone assignment**. A unit standing on a central shed-access coordinate can count in a locked quadrant. Transit excludes midnight teleport/reset distances.
- Action counters are requests/attempts. Successful harvest inventory increases are a **lower bound**, excluding midnight receipts where automatic deposit/reset confounds personal inventories. They include animal products and crop units separately, not generic harvest counts.
- `BUY_PRODUCT` and `SELL` quantities are **requested**, not exact executed quantities or cash settlements. The replays expose both seats' private snapshots, permitting additional offline accounting; private opponent data would not be observable to our live agent. This research uses them only for offline harvest verification.
- Exact feed consumption, overflow attribution, market settlement prices, revenue by source quadrant, failed-action causes and task deadlines are not yet reconstructed by this extractor. Requested feed orders cannot stand in for feed bought/consumed. Fungible shed sales require a stated provenance allocation or engine transaction instrumentation. These limitations do not prevent direct observation of acquisition, staffing, crops, geography or final score.

## The broad saved sample does not average $140k

| Player identity | Saved player episodes | Mean final reward | SW acquired |
|---|---:|---:|---:|
| Crop Dusta | 105 | $100,044.52 | 105/105 |
| Milan Leonard | 30 | $92,087.50 | 30/30 |
| Ryo Hasegawa | 24 | $92,575.75 | 24/24 |
| Subramanya N | 16 | $87,080.13 | 16/16 |
| Aarya Jadhav (historical own-agent replays) | 27 | $45,291.22 | 23/27 |

These identities denote saved gameplay, not a claim about current leaderboard positions. Crop Dusta's range is **$59,302–$152,807**. Selection, historical versions, opponents, town RNG and strategic interaction differ. Do not subtract the modern $101k baseline mean from any row and call the result a treatment effect. High-scoring examples demonstrate possibility, not expected achievable mean cash.

## Crop Dusta: consistent early land, mixed production, ordinary workforce ceiling

Across all 105 saved Crop Dusta player episodes:

- NE is first observed **D5H2 in every episode**, with five workers afterward.
- SW is first observed **D8H5 to D9H13**, mean absolute hour 202.438 (D8H10.438), with **8–9 workers** afterward (mean 8.9905).
- By D12H23 every saved episode has **13 workers**. This is the same nominal mature workforce count as our farmer plus twelve hands, not evidence that leaders rely on a much larger late workforce.
- Mean SW planted crop tile-days across the whole observed season: **350.92** (hourly integration / 24). This does not include animal occupancy.
- Mean worker physical SW presence: **1,772.49 recorded worker-hours/game**. Mean movement outside reset: **3,856.13 steps/game** out of **7,393.34 requested unit actions/game**. This is not a matched routing improvement versus our baseline; successful and failed move semantics and horizon must be aligned first.

### Mean hour-23 regional crop portfolio

Numbers are active crop tiles, averaged across 105 episodes; zero/absent crops omitted. S = strawberry, W = wheat, M = melon, T = tomato, C = carrot.

| Day | Workers | NW | NE | SW |
|---|---:|---|---|---|
| 5 | 5.00 | S6.96 W5.02 M5.04 | S1.37 W6.05 M0.05 | none |
| 8 | 8.99 | S9.02 W3.95 M6.57 | S5.43 W10.06 M5.29 | S2.76 W3.08 M0.74 |
| 10 | 11.37 | S11.14 W4.56 M1.87 | S7.35 W6.88 M5.45 | S4.51 W11.04 M1.22 |
| 12 | 13.00 | S11.66 W5.24 M1.88 | S7.78 W6.72 M5.47 | S5.51 W13.83 M1.26 |
| 15 | 13.00 | S11.76 W4.63 M2.04 | S8.21 W5.59 M5.63 | S6.26 W11.63 M1.54 |
| 20 | 13.00 | S9.67 W6.43 M0.31 T1.02 | S8.13 W7.45 M0.33 T2.73 | S6.25 W10.74 M0.46 T1.87 |
| 25 | 13.00 | S2.59 W6.88 C5.93 T1.02 | S2.70 W6.90 C5.65 T2.72 | S3.41 W7.25 C5.33 T1.87 |

SW is substantially developed within two to four days of acquisition. Its role changes: a large wheat component supports the farm while strawberries/melons provide commercial production; tomatoes appear later and carrots take endgame acreage. **The saved evidence contradicts a universal wheat-only SW whitelist.** It also contradicts the idea that leaders simply add undifferentiated land without developing it.

### Mean hour-23 animal geography

| Day | NW cow/sheep/goose | NE cow/sheep/goose | SW cow/sheep/goose |
|---|---|---|---|
| 8 | 3.01 / 2.01 / 0.01 | 2.11 / 1.61 / 0.05 | 0.22 / 0.48 / 0.14 |
| 12 | 3.32 / 2.45 / 0.15 | 2.30 / 2.15 / 0.24 | 0.90 / 1.26 / 0.39 |
| 15 | 3.45 / 2.65 / 0.22 | 2.44 / 2.35 / 0.30 | 1.17 / 1.62 / 0.62 |
| 20 | 3.50 / 2.85 / 0.22 | 2.49 / 2.62 / 0.34 | 1.27 / 1.88 / 0.66 |

Crop Dusta does not uniformly reduce livestock to fund SW. At D15 the mean herd is about 14.82 animals, distributed over three quadrants, versus the roughly eleven-animal modern baseline measured on separate local panels. That comparison is descriptive, not causal. The per-episode JSON preserves exact animal/structure coordinates for layout work. Counting empty pastures as animals would exaggerate actual herd size.

Across these episodes, SW harvest inventory increases average at least 164.77 wheat, 36.36 strawberry, 8.97 melon, 33.47 carrot, 12.50 tomato, 22.61 milk and 34.66 wool units/game. Midnight harvests are excluded, so these are lower bounds, not exact full production totals. Requested wheat purchases average 1,544.83 units/game; **this is not purchased feed volume**, and includes possibly unsuccessful or repeated requests and trading. Thus the replays do not justify claiming feed self-sufficiency.

## Contrasting high-score complete farm snapshots

| Episode / player | Final cash | NE observed / workers after | SW observed / workers after | First >=12 SW crop tiles |
|---|---:|---|---|---|
| 100862188 / Crop Dusta | $139,299 | D5H2 / 5 | D8H8 / 9 | D10H22 |
| 100862188 / Ryo Hasegawa | $137,315 | D6H10 / 8 | D10H15 / 13 | D11H11 |
| 101361968 / Crop Dusta | $152,807 | D5H2 / 5 | D9H2 / 9 | D11H17 |
| 101361968 / Mingkang YAN | $137,911 | D6H15 / 7 | D11H2 / 11 | D12H5 |
| 102694950 / Milan Leonard | $156,877 | D6H7 / 9 | D11H2 / 12 | D11H14 |
| 102694950 / Crop Dusta | $151,380 | D5H2 / 5 | D8H8 / 9 | D9H23 |

The simultaneous two-player high outcomes are particularly important: shared favorable town markets can elevate both scores, making a single $150k episode poor evidence for the causal value of its SW policy.

Day-15 layouts show fundamentally different viable roles:

- **100862188 Crop Dusta:** NW 12 strawberries/3 wheat/2 melon and 4 cows/3 sheep; NE 10 strawberries/8 melon and 5 sheep; SW 9 strawberries/6 wheat/3 melon and 2 cows/5 sheep. Mixed crop/livestock SW; regional animal clusters coexist with intensive repeats.
- **100862188 Ryo:** NW 9 wheat/2 strawberries and 5 cows/7 sheep; NE 19 strawberries with 2 cows/1 sheep; SW 9 strawberries/8 wheat and 1 sheep. Livestock concentrated toward NW, commercial repeat production toward NE, SW mixed support.
- **101361968 Crop Dusta:** NW 12 strawberries/3 wheat/2 melon and 3 cows/5 sheep; NE 5 strawberries/3 wheat/6 melon and 10 sheep; SW 6 strawberries/12 wheat/3 melon and 3 sheep. Sheep-heavy farm with SW feed/commercial mix.
- **102694950 Milan:** NW 6 strawberries/12 wheat/1 carrot and 4 cows/2 sheep; NE 15 strawberries/3 wheat and 5 cows/2 sheep; SW **15 strawberries/10 wheat, no animals**. Crop-led SW is demonstrated without reducing the entire farm to a minimal herd.
- **102694950 Crop Dusta:** NW 17 strawberries/3 melon and 3 cows/2 sheep; NE 17 strawberries/3 melon and 5 cows; SW 13 strawberries/6 wheat and 2 cows/1 sheep. This is a much larger repeat-crop portfolio than the wheat-only design in our older SW notes.

These are observed configurations, not blueprints proven optimal or safe. The table intentionally includes an SW D11 purchase: buying before D9 is not a necessary condition for an individual high score.

## Hypothesis verdicts

| Proposed leader difference | Evidence verdict |
|---|---|
| Earlier SW purchase | Yes versus our no-SW baseline / P4.1 D14; Crop Dusta consistently D8–9, other strong examples D10–11 |
| Faster development | Yes: Crop Dusta mean SW crop footprint ~16.8 by D10H23, ~20.6 by D12H23; high examples cross twelve crops within 12–63 hours |
| More workers per land | Not established. Crop Dusta grows to 13 workers, matching our mature count, but timing and realized assignments differ |
| Fewer livestock | Not a universal pattern; many leaders maintain larger herds and/or relocate species between regions |
| Lower-maintenance crops | Wheat is important, but strawberries and melons also occupy SW. Net maintenance advantage requires action-success and yield-per-action analysis |
| Geographic concentration | Observed, but heterogeneous: Ryo NW livestock/NE strawberries; Milan crop-only SW; Crop Dusta mixed production in every region |
| Deliberate sacrifice of lower-value core activity | Not directly observable as intent or marginal counterfactual. Crop composition evolves, but no replay reveals the alternative it rejected |
| Specific SW role | Yes; feed plus repeats, crop-led commercial production, and mixed crop/livestock roles all appear. No single role is universally dominant |
| Better routing/task completion | Movement and regional presence reconstructable; task ownership, latent queues and missed alternative opportunities are not in public replays. Compare standardized successful-action traces before attributing gains |

## What additional evidence would close the gaps

No additional replay upload is required to establish the observations above; the repository already contains substantial direct evidence. To quantify complete leader economics, the next read-only audit should instrument the matching historical engine and replay recorded actions, verifying every intermediate state hash. It needs successful per-unit action events, exact unit-by-unit market settlements, feed consumption by species/tile, midnight inventory drop/discard events, crop maturity/expiry transitions, and product provenance. Historical engine/module version compatibility must be checked; silently replaying old actions under current rules is not exact reconstruction.

To establish that a leader's *policy* causally outperforms ours would additionally require an executable leader agent or sufficiently faithful policy reconstruction on matched seeds/opponents/seats. Saved trajectories alone cannot answer off-trajectory decisions. Worker priority intent and deliberate substitution logic require code or policy telemetry; they cannot be recovered uniquely from actions.

The strongest design clue is coordinated early commitment: land arrives while there is enough time to build a mixed regional portfolio, staffing ramps around it, and the farm maintains substantial feed and cash-producing production. It supports testing a forward-committed three-quadrant architecture. It does **not** prove that copying a purchase day, increasing utilization, or adding nine animals will improve our average final cash.
