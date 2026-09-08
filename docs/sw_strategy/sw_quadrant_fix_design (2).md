# SW Quadrant Utilization Fix — Kaggriculture Agent Design
**Goal:** turn the idle $2,000 SW quadrant (25 tiles, x:0–4, y:5–9) from $0 contribution into a **~$26,000–30,000 net profit engine** (Feed → Livestock → Fertilizer → Late Carrot Blitz), matching the $140k leaderboard leader's playbook.

**Root-cause → fix map**
| Failure | Fix |
|---|---|
| Capital trap (expensive SW seed orders) | SW crop whitelist: WHEAT only (D9–25), CARROT only (D25–27). Strawberry/melon/tomato orders for SW are hard-blocked. |
| Treasury exhaustion on D9 | Seed **escrow** reserved *before* land purchase; land buy gated on `cash − 2000 − escrow − hires ≥ 0`. |
| Deadline lockout (strawberry D13) | SW never plants strawberry at all — the whitelist removes the blocking condition entirely. |
| Pathing starvation | Dedicated SW squad dispatched from **Port (4,5)** with static BFS routes and quadrant-exclusive task queues. |

---

## 1. Tile Layout — exact breakdown of the 25 SW tiles

```
 y=5 | PASTURE PASTURE PASTURE PASTURE | PORT (4,5) = shed PICKUP/DROP anchor
 y=6 | PASTURE PASTURE PASTURE PASTURE PASTURE
 y=7 | WHEAT   WHEAT   WHEAT   WHEAT   WHEAT      → CARROT from D25–27
 y=8 | WHEAT   WHEAT   WHEAT   WHEAT   WHEAT      → CARROT from D25–27
 y=9 | WHEAT   WHEAT   WHEAT   WHEAT   WHEAT      → CARROT from D25–27
      x=0     x=1     x=2     x=3     x=4
```

| Class | Tiles | Coordinates | Purpose & phase |
|---|---|---|---|
| **PORT / logistics** | 1 | (4,5) | Shed-access tile inside SW; spawn/queue anchor for the SW squad; DROP point for fertilizer/milk/wool/carrots. Never planted. |
| **PASTURE** | 9 | (0–3,5), (0–4,6) | Secondary herd: **6 COWS + 3 SHEEP** (cow-first: cow ROI $136/tile-day > sheep $118). Placed in the two rows nearest the port so feeding loops are shortest. Bought D9–11 as cash allows ($400/$500 each, cow priority). |
| **WHEAT feed engine** | 15 | (0–4,7), (0–4,8), (0–4,9) | $10 seed, 4-day cycle, 5 wheat/harvest ⇒ 1.25 wheat/tile-day ⇒ **18.75 wheat/day**, enough feed for an 18-animal herd. Replant continuously D9→D25. |
| **CARROT blitz** | same 15 | rows y=7–9 | D25–27: harvest wheat, plant $20 carrots (2–3 d cycle), liquidate D29: 15 × 3.5 × $70 ≈ **$3,675 gross / $3,375 net**. D28–29: harvest-only, then fallow. |

Counts: 1 + 9 + 15 = 25. ✔ No tile is ever idle between D9 and D29 except the port.

---

## 2. Purchasing Rule (Days 8–11): never starve seed capital

**Rule P1 — Escrow first, land second.** Every morning (D8–D11), before any purchase:
`ESCROW = $10 × 15 = $150` (mandatory wheat seeding budget for all 15 SW soil rows; kept in a reserved variable no other subsystem may spend).

**Rule P2 — Gated land buy.** Buy SW only if `cash − $2,000 − ESCROW − HIRE_COST(h) ≥ 0`. Prefer D8 if the gate passes (each extra day = 9 × $100 fertilizer + herd output); mandatory D9; fallback D10–11; **abort SW entirely after D11** (fertilizer window < 18 days no longer pays back $2,000).

**Rule P3 — Same-turn seeding (the anti-starvation invariant).** On the very turn SW is bought, immediately spend ESCROW: order 15 × WHEAT ($10) and plant the tiles closest to (4,5) first (row y=7, then y=8, then y=9). Seed orders are placed *before* hiring extra hands, so a Fibonacci hire spike can never abort them.

**Rule P4 — Hire scaling instead of a D9 spike.** D9: hire **8 hands ($54)**, not 10 ($143) — saves $89 exactly when treasury is thin; 4 hands go to the SW squad. From D11 (milk/fertilizer cash flowing): step to 10 ($143), and to 12 ($376) only while `daily_income ≥ $2,000` (true once ≥ 9 animals are fed: 9 × $100 fertilizer/day).

**Rule P5 — SW crop whitelist (kills capital trap + deadline lockout).**
- D9–D25: only `WHEAT` may be ordered/planted in SW.
- D25–D27: only `CARROT`.
- `STRAWBERRY`, `MELON`, `TOMATO` orders with any SW target tile are rejected by the order validator at all times (strawberry's D13 deadline can never collide with SW capital recovery, so the permanent block bug disappears).
- Pasture purchases are exempt but cow-priority and capped at 9 tiles.

---

## 3. Transition Logic (Day 25): wheat → carrot switch, exact rule

Definitions at the daily planning step of day `D`:
- `H` = fed herd size (animals alive on farm).
- `STOCK` = wheat in shed + wheat on SW/NW tiles harvestable on or before D29.
- `FEED_NEED(D) = H × (29 − D + 1)` = wheat required to keep every animal fed through D29 (2-day unfed = escape).
- Wheat planted on `D` harvests `D+4`; carrot planted on `D` harvests `D+2..D+3`.

**Switch rule (evaluated per free SW soil tile, in order):**
1. **Wheat replant allowed only if** `D + 4 ≤ 29` (i.e. `D ≤ 25`) **AND** `STOCK < FEED_NEED(D)`. Number of wheat tiles today: `N_wheat = min(free_tiles, ceil((FEED_NEED(D) − STOCK) / 5))`.
2. **Carrot plant allowed only if** `D + 3 ≤ 29` guaranteed (`D ≤ 26`), **or** `D = 27` where EV = 0.5 × 3.5 × $70 − $20 = **+$102.5/tile > 0**. All SW soil tiles not taken by rule 1 become carrots: `N_carrot = free_tiles − N_wheat`.
3. **Hard stop:** `D ≥ 28` → plant nothing (carrot EV ≤ 0); harvest-only until D29.

**Why D25 is the pivot in practice:** on D25, `FEED_NEED(25) = 5H` (≈ 90 wheat for H=18) while `STOCK` from 15 wheat tiles replanted since D9 plus NW surplus is already ≥ that; so rule 1 yields `N_wheat = 0` and the switch to **100 % carrot fires on D25**, giving 3 full blitz plantings (D25, D26, D27). If a feed shortfall ever exists on D25, rule 1 automatically keeps exactly `ceil(deficit/5)` wheat tiles as a buffer and converts the rest — the rule degrades gracefully instead of locking up.

Pseudocode:
```python
def sw_plant_decision(D, free_tiles, STOCK, H):
    if D >= 28:
        return {"wheat": 0, "carrot": 0}                    # fallow, harvest-only
    feed_need = H * (29 - D + 1)
    n_wheat = 0
    if D <= 25 and STOCK < feed_need:
        deficit = feed_need - STOCK
        n_wheat = min(free_tiles, (deficit + 4) // 5)       # ceil(deficit/5)
    n_carrot = free_tiles - n_wheat
    if D == 27 and (0.5 * 3.5 * 70 - 20) <= 0:
        n_carrot = 0                                        # EV gate
    return {"wheat": n_wheat, "carrot": n_carrot}
```

---

## 4. Worker Assignment: dedicated SW squad, no pathing starvation

**Rule W1 — Quadrant-partitioned squads (never global nearest-tile greedy).** Daily hires are split at dawn: `SW_SQUAD = 4 hands` (5 hands from D11 when hires = 12), remainder to NW/NE squad. The global task allocator is replaced by two **per-quadrant FIFO queues**; a hand only ever pops from its own quadrant's queue. This makes SW starvation structurally impossible.

**Rule W2 — Port (4,5) dispatch anchor.** SW hands start and end every loop at shed-access tile **(4,5)** (the SW-side port), not at (4,4)/(5,4) whose BFS trees bias toward NW/NE. At D9, precompute and **cache static BFS routes** from (4,5) to all 24 other SW tiles; reuse the cache all game (terrain is static), eliminating per-turn pathfind cost and drift.

**Rule W3 — Serpentine loop order.** Each SW hand walks: (4,5) → pasture row y=6 (x0→x4) → pasture row y=5 (x3→x0) → wheat rows y=7 (x0→x4), y=8 (x4→x0), y=9 (x0→x4) → back to (4,5) to DROP. Tiles are visited by ascending Manhattan distance from (4,5) within each class.

**Rule W4 — Intra-squad task priority (per turn):**
1. DELIVER wheat feed to any pasture with 0 feed buffer (before midday; unfed-2-days = escape).
2. COLLECT fertilizer / milk / wool (every fed animal = $100/day — highest value-per-action).
3. HARVEST mature wheat (D≤25) / carrots (D28–29).
4. PLANT per §3 decision (wheat or carrot).
5. DROP surplus at (4,5).

**Rule W5 — Capacity invariant & alarm.** Assert each planning step: `SW_pending_tasks > 0 ⇒ all SW_SQUAD hands have non-empty routes`. If SW queue backlog > 2 × squad capacity (e.g. fertilizer pickup slipped a day), borrow 1 hand from NW/NE for that day only and log a warning. Hires reset daily, so squad sizes are recomputed each dawn from §2 P4.

---

## 5. Expected SW P&L (D9–D29) vs today's $0

| Line | Value |
|---|---|
| Fertilizer: 9 animals × $100 × ~20 days | **+$18,000** |
| Milk: 6 cows × 10 milkings × $160 | **+$9,600** |
| Wool: 3 sheep × 6 shearings × $200 | **+$3,600** |
| Carrot blitz D25–29: 15 tiles × 3.5 × $70 − $300 seed | **+$3,375** |
| Wheat surplus sold (feed slack) | +$500–1,500 |
| SW land | −$2,000 |
| Animals: 6×$400 + 3×$500 | −$3,900 |
| Wheat seed: 15 tiles × ~4 cycles × $10 | −$600 |
| Incremental hires (8→10→12 ramp) | −$1,500 |
| **SW net** | **≈ +$26,000–28,000** (13× the land cost) |

Combined with a healthy NW/NE melon+strawberry core (~$110k), total score lands in the leader's **$140k+** band. Verified unit economics (per tile-day): cow $136 > wheat-as-feed $122.5 > sheep $118 > carrot $90 > wheat-as-cash $28.8 — which is exactly why SW runs feed+livestock first and carrots only in the final window. Fibonacci hire costs confirmed: 4=$7, 8=$54, 10=$143, 12=$376.
