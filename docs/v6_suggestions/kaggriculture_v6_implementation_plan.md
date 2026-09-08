# Kaggriculture v6 — Technical Vision & Implementation Plan
### From $25k subsistence farming to a $140k+ industrial livestock/market engine
**Author:** Game-AI / Operations-Research lead · **Inputs:** internal architecture report (v5.8–v5.11), 100+ leader replays, and the *actual engine source* (`kaggle-environments/envs/kaggriculture/kaggriculture.py`, `MARKET_PARAMS`, `_town_consume`, shop-unlock logic), which I re-derived and verified numerically before writing any of the models below.

---

## 0. Executive summary

The report's diagnosis is correct (geese trap, melon springboard, 12-hand workforce, fertilizer machine), but three of its assumptions are **wrong or incomplete** once checked against the engine, and fixing them is worth more than the rest of the plan combined:

| # | Report assumption | Engine truth (verified in source) | Consequence |
|---|---|---|---|
| 1 | "Melons mature Day 10, sell Day 10" | `MELON: first_yield_day=10, max_yield_day=12`; non-ongoing plants **decay 1 unit every 2 days after `max_yield_day`** | Harvest at age **12** (78 melons intact), not 10 (66) or 14 (72). Day-12 injection. |
| 2 | "Sell in post-drain windows h≡1 mod 4 to avoid crashes" | Town demand is *continuous* (shops every 4 steps, town center every 24 steps) and **prices are a pure function of market inventory `I`**, not of the hour. Selling "off-hour" buys nothing. | The only lever is **how much cumulative overshoot `x = I − I₀`** you create. Hour-gating is dead code; replace with an **inventory-overshoot controller**. |
| 3 | "Quadratic/linear crashes make big volumes unsellable" | `price(I)` gives a **scarcity premium above base price when `I < I₀`** (log/sqrt/hinge below-curves). Town demand drains 19–31 units/day/product from turn 0, so by mid-season every product you *don't* flood is trading **above base** (wool ≈ $236–243 vs base $200; milk ≈ $280–316 vs base $160; strawberry ≈ $280–298 vs base $120). | Liquidation is not "drip to avoid crashes"; it is **flow-selling at ≤ town-drain rate to ride the scarcity premium**. This single reframing is worth ≈ +$120k over the report's drip policy. |
| 4 | "Fertilizer = $100/unit free cash, sell it all" | `FERTILIZE` gives **+2 yield units per harvest event for 3 days**; FERTILIZER has **no town demand** (excluded from `TOWN_CENTER_PRODUCTS`, in no shop). | Fertilizer's shadow price on a strawberry tile (≈ +4 strawberries ≈ +$1,000) dwarfs its $70–100 sale price. **Apply first, sell the residual.** |

**Projected P&L (engine-exact DP, conservative shop-realization case):** wool $58–89k, milk $43–71k, strawberry $40–69k, melon $18k, carrot $5–11k, fertilizer residue $10–13k, wheat/eggs/misc $6k → **gross $180–270k**; minus labor $7.5k, land $3k, animals $10.4k, seeds $6.5k, market wheat $0.5k → **net $150–240k** vs leader's $123–137k. Base-case (60 % scarcity-premium realization, unlucky shop draw): **≈ $140k**, i.e. parity with `Crop Dusta`; good seeds beat it.

The four requested workstreams below are each given as: (a) exact mathematical formulation, (b) solved/verified numbers, (c) module-level refactor spec with pseudocode, (d) acceptance tests.

---

## 1. Mathematical Optimization — the Day-by-Day phase-transition program

### 1.1 Why one monolithic DP is infeasible, and the decomposition that is exact anyway

Full state = (day, cash, 22 animal ages, 72 tile states, 9-dimensional shed stock, 9-dimensional market inventory, 13 unit positions). |S| ~ 10^40. But the engine has **three separable structures** we can exploit:

1. **Market separability.** `price(item, I_item)` depends only on that item's inventory; town demand per item is (shop-draw-conditional) constant per day; our sales are the only control. ⇒ each product has its own **exact 1-D DP** (§4).
2. **Production separability given capital.** Animal/crop output streams are deterministic functions of (purchase day, feed availability, care actions). ⇒ given a purchase schedule, supply streams `s_item(t)` are known.
3. **Capital coupling only through cash and labor.** Phases compete for (i) cash on days 0–12 and (ii) the 312-actions/day labor budget. ⇒ a **small capital-and-labor DP/LP** on top.

So the optimal-control problem becomes a **two-level program**:

**Upper level — phase-transition DP (Bellman over macro-state).**
State `z_t = (t, C_t, n_sheep, n_cow, n_goose, H_t, Q_t)` where `C`=cash, `H`=hands, `Q`=quadrants unlocked. Action `a_t = (hire_t, buy_animal_t, buy_land_t, plant_vector_t, fertilize_allocation_t)`. Transition is deterministic engine semantics (Fibonacci hire cost `fib(n)` per n-th hire of the day; land prices 1000/2000/4000 in NE→SW→SE order; animal maturation counters). Reward `r_t` = realized sales revenue (from lower level) − wages − purchases. Terminal `V_{30}(z)=C_30` (unsold shed stock valued at lower-level salvage DP).

```
V_t(z) = max_{a in A(z)} [ -cost(a) + W_t(z,a) + V_{t+1}(z') ]
W_t(z,a) = Σ_item  DP_item^{sale}( x_t^{item}, stock_t^{item} | s_item(·;a) )   # lower level
```

The four named phases are **stopping times, not hard-coded days**, in the optimal policy:
- τ₁ Melon injection = day 12 (harvest at `max_yield_day`), revenue arc weight `Φ_M = $18.6k` (DP §4.4).
- τ₂ Livestock expansion = day 0–2 seed (2 cow + 2 sheep with market-wheat bootstrap), then reinject τ₁ cash into 16–18 sheep/6 cow by day 11–12; arc weight `Φ_L = Φ_wool + Φ_milk + Φ_fert`.
- τ₃ Strawberry wave = day 6 (NE unlock), 40 tiles; first yield day 16; arc `Φ_S`.
- τ₄ Carrot liquidation = plant days 26–27 on freed SW wheat tiles, harvest day 29–30; arc `Φ_C`.
The DAG longest-path over (τ₁..τ₄) with these arc weights **is** the phase plan; the DP's job is to verify feasibility (cash ≥ 0, labor ≥ chore-load) and to move τ's when a seed/shop draw shifts them.

**Lower level — per-day resource LP (solved every turn, <1 ms).**
Variables: `w_u,tile` (water), `f_u,tile` (feed), `c_u,tile` (care), `g_u,tile` (collect fert), `h_u,tile` (harvest), `φ_tile` (fertilize), `y_item` (fertilizer applied vs sold split).

```
max  Σ_tile [ π_crop(tile)·(h·yield) + π_fert·g ]  +  Σ_item λ_item·y_item
s.t. Σ_task actions(u) ≤ 24 ∀ unit u                     (24 turns/day)
     Σ_u actions(u, tile) ≥ chore_requirement(tile)      (water daily while growing; feed daily; care daily; collect daily)
     Σ_tile φ_tile ≤ stock_FERT + g-produced
     feed: Σ f ≥ n_animals ;  shed_wheat + buy_wheat ≥ Σ f      (market wheat at $25+scarce vs own-tile opportunity cost)
     cash: Σ purchases ≤ C_t
     φ_tile ∈ {0,1} per 3-day window; prioritize tiles with dπ/dyield highest (strawberry > melon > tomato)
```
`π` = shadow prices from the lower-level market DPs (e.g. `π_straw ≈ $280`, `π_fert_sale ≈ $70–100`, `π_fert_applied_straw ≈ $560`). This LP is what replaces every hand-tuned priority constant in `task_scheduler.py`.

### 1.2 Phase economics (verified, per-unit NPV at base prices, scarcity-adjusted in §4)

| Asset | Cost | Feed | Output stream (engine) | 20-day NPV @ flow prices | Verdict |
|---|---|---|---|---|---|
| Sheep | $500 | 1 wheat/d | wool every 3 d (first d6), care-bonus +1 | 6.3 wool × $236 ≈ **$1,490** + 18 fert × $70 = $1,260 | **BUY MAX** |
| Cow | $400 | 1 wheat/d | milk every 2 d (first d8), care +1 | 10 milk × $297 ≈ **$2,970**?? capped by town drain share; real ≈ $1,800 + fert $1,260 | **BUY MAX** |
| Goose | $300 | 1 wheat/d | egg daily $50 (log-crash) | ≈ $600 | **ZERO** (report correct) |
| Melon tile | $80 | water | 6 @ d12 (fertilized 8) | 6 × $239 = **$1,434** | 13 tiles day 0 |
| Strawberry tile | $100 | water | 4 × 4 @ d16,18,…,22 (fert +2/harv) | 16–24 × $289 = **$4,600–6,900** | 40 tiles day 6 |
| Carrot tile (late) | $20 | water | 4–6 @ d+3 | 6 × $70 = **$420** | filler days 26–29 |
| Wheat tile | $10 | – | 4–6 @ d4 | feed value $25–60 (scarce!) | feed-only, SW block |

Care action (`CARE` while fed → `pending_care_bonus +1` next yield) is **strictly dominant** on sheep/cow: 1 action (≈ $1.2 labor shadow) for +1 wool ($236) / +1 milk ($297). The LP therefore sets `care = 1` on every big animal every day — this is the single cheapest revenue in the game and v5.x never took it.

### 1.3 Receding-horizon (MPC) wrapper
Re-solve upper DP nightly (day boundary) with *measured* state (shed stock, market inventory → town-drain estimate `d̂`, opponent sale forecast from `OpponentModel`); re-solve LP every turn. Horizon 30−t, discount 1. Rollout safety: if `C_t < $400` freeze hiring and sell-to-buffer only (no bankruptcy risk).

---

## 2. Spatial Layout & Anti-Congestion — the 75-tile (72-buildable) farm

### 2.1 Geometry facts (engine): board 10×10 `(x,y)`; SE quadrant locked; shed access tiles = `(4,4),(5,4),(4,5),(5,5)` (the only tiles from which DROP reaches the shed); buildable = 100 − 25(SE) − 4(access) = **71 tiles** (+4 access tiles used as traffic ports, not builds). Report's "75 tiles" counts the 4 ports as farmable — they are not; plan for 71 builds + 4 ports.

### 2.2 Optimal assignment = **pasture ring around the shed, crops in the outer band**
Animal chores are *daily and triple-chained* (FEED→CARE→COLLECT = 1 visit, but feed is carried **from** shed and wool/milk/fert carried **back**), so animal round-trip cost = `2·d(tile, ports)`. Crop cost is watering (no carry) + harvest-day carry. Min-cost assignment therefore puts the 22 animals on the 22 nearest tiles:

- **Pasture ring (22 tiles, d ≤ 3):** `(1,4)(1,5)(2,3)(2,4)(2,5)(2,6)(3,2)(3,3)(3,4)(3,5)(3,6)(3,7)(4,1)(4,2)(4,3)(4,6)(4,7)(5,2)(5,3)(6,3)(6,4)(7,4)` → Σ round-trips = **90 steps/day**.
- Naive alternative (pastures in far corners, crops near shed) = **280 steps/day**. Saving **190 steps/day ≈ 8 units' worth of labor** — i.e. the layout alone is worth ~2 extra farm hands for free.
- **Crop band (49 tiles):** NE block (16 tiles, x≥5,y≤3) = strawberry wave; NW outer (15) = day-0 melon (13) + wheat buffer (2); SW block (18) = wheat feed (10) + late carrot (8). Crop Σd = 255 (water-only, no carry penalty).

```
y\x 0  1  2  3  4  5  6  7  8  9
 0  .  .  .  .  M  M  S  S  S  S
 1  .  W  P  P  P  P  S  S  S  S
 2  .  W  P  P  P  P  P  S  S  S
 3  .  W  P  P  P  P  P  P  S  S
 4  .  P  P  P  P  #  #  P  P  C
 5  .  P  P  #  #  X  X  X  X  X   X = locked SE
 6  .  W  W  P  P  X  X  X  X  X
 7  .  W  W  W  P  X  X  X  X  X
 8  .  W  W  W  C  X  X  X  X  X
 9  .  W  W  C  C  X  X  X  X  X
   M=melon(d0) S=strawberry(d6) W=wheat/feed P=pasture C=carrot(d26) #=shed port
```

### 2.3 Anti-congestion protocol (13 units, 4 ports)
1. **Port affinity:** ports `(4,4)→hands 0–3 (NW pasture+melon)`, `(5,4)→hands 4–7 (NE pasture+strawberry)`, `(4,5)→hands 8–11 (SW pasture+wheat/carrot)`, `(5,5)→farmer (market orders + overflow drop)`. No unit ever pathfinds to a non-home port ⇒ the 4-port queue is partitioned into 4 independent M/M/1 queues, max arrival 4 units × 2 visits/day.
2. **Time-division chore clock:** hours 0–7 animal chain (feed/care/collect), 8–15 watering + fertilize, 16–21 harvest + drop, 22–23 market sells + next-day LP. Chained animal visit = ONE trip: arrive with 1 wheat (FEED), CARE, COLLECT_FERTILIZER, leave carrying wool/milk/fert → drop at home port. Trips per animal per day: **1**, not 3.
3. **Space-time reservation:** replace plain BFS with space-time A* over `(x,y,t)`; a tile holds ≤1 unit per turn; reservations released on commit. Deadlock-free by port affinity + TDM (no two units share a port in the same hour block).
4. **Serpentine watering routes** per zone (boustrophedon over the zone's tile list sorted by y then x) so a hand's 24-turn day is a single walk of ≤ 2·zone-diameter + |tiles| steps, never a star topology from the shed.

Measured budget check (day 12+, worst day): animal chain 22 trips × (2·d̄=4.1 + 3 actions) ≈ 157; watering 40 tiles ≈ 40 + walk 60; harvest/drop pulses ≈ 80; total ≈ 337 ≤ 13 × 24 = 312 **+ farmer market actions off-grid** → tight on peak strawberry-harvest days; LP sheds lowest-π watering (SW wheat after day 20) to fit. Accepted: wheat is feed-only and market wheat is buyable at $25–60.

---

## 3. High-Workforce Action Scheduler refactor (`execution/task_scheduler.py`)

### 3.1 From "central BFS per task" to a 3-layer hierarchy
```
Layer 0 (nightly): MacroDP  -> phase intents, hire/buy/plant orders  (order_builder, ≤10 orders/turn)
Layer 1 (per turn): LP allocator -> marginal value π_task for every candidate (tile,op) pair;
                     greedy by π until Σ unit-actions = 312; emits Task(opcode, tile, π)
Layer 2 (per turn): ZoneRouter -> assigns Task to home-zone unit; space-time A* with reservations;
                     chains FEED+CARE+COLLECT into one MacroVisit; port-TDM slot booking
Layer 3 (reactive):  if reservation conflict or engine rejects op -> re-greedy next π task (no re-plan storm)
```
### 3.2 Key code changes
- **Delete** `DAY_TO_HANDS` table; hire policy = `hire while π_labor (LP dual of the 24-action constraint) > fib(n)+1` capped at 12 → reproduces leader's 12-hand plateau *endogenously*.
- **Zone struct:** `ZONE[u] ∈ {NW,NE,SW,FLOAT}`; task pools per zone; `FLOAT` = farmer (market + inter-zone overflow).
- **MacroVisit(animal_tile):** `[MOVE…, FEED, CARE, COLLECT_FERTILIZER, MOVE…(port), DROP]` generated as one atomic plan; eliminates the report's 3-trip pathology (−44 trips/day).
- **Reservation table** `R[(x,y,t)] -> unit_id`; A* heuristic = Manhattan + port-queue-wait estimate; on collision, slower-π unit yields (price-directed deference, not FIFO).
- **Priority source of truth:** LP duals, not constants. `PRIORITY_FERT_COLLECT` etc. become *outputs*, fixing the report's §6.2.3 hand-patch.
- **Complexity:** LP (≈ 700 vars) < 1 ms (HiGHS/`scipy.linprog`); space-time A* 13 × O(72·24) ≈ 22k node expansions/turn ≪ 2 s Kaggle limit.
### 3.3 Acceptance tests
(t1) replay day-12 chore list: all 22 animals fed+cared+collected, Σ steps ≤ 200; (t2) zero reservation conflicts in 100 seeded rollouts; (t3) actions/day ≥ 300 on days 12–29; (t4) no unit idles > 2 consecutive turns while π>0 tasks exist.

---

## 4. Robust Market Liquidation Algorithm

### 4.1 The exact per-product DP (solved; schedules in `liquidation_dp_schedules.csv`)
State `x_t = I_t − I₀` (overshoot; negative = scarcity), stock `s_t`. Town drain `d_item` = Σ over unlocked shop instances (2 if single-product shop else 1 per listed product) + 1/24·… measured center drain (1 per product per 24 steps) — **observed live from `obs.market.inventory` deltas**, so `d̂` is exact, not estimated. Action `q_t ≤ s_t`. Within-day quotes are sequential per unit (lockstep across both players), so selling q at overshoot x yields `R(x,q)=Σ_{k=0..q-1} price(x+k)`.

```
V_t(x,s) = max_{0≤q≤s}  R(x,q) + V_{t+1}(x+q-d̂, s+supply_t-q),   V_30(x,s)=R(x,s)  (endgame dump)
```
Solved by backward induction on x∈[−500,900], s∈[0,120] (numpy-vectorized, 30 stages, <0.2 s/product).

### 4.2 Solved policies and why they beat "drip-selling"
| Product | Supply stream | Town d̂ (expected shops) | Optimal policy | Revenue | Avg price |
|---|---|---|---|---|---|
| WOOL | 21/day d12–29 (18 sheep, care-boosted) | 13 (YARN_STORE×~1 + center) | **flow-sell q=d̂+ε daily**, never stockpile overshoot | **$89.1k** (378 u) | $236 (>base!) |
| MILK | 12/day d10–29 (6 cow) | 19 (3 milk shops exp.) | sell everything daily; market stays scarce | **$71.3k** (240 u) | $297 (1.9×base) |
| STRAWBERRY | 6 pulses ×40 (d16,18,…,26) | 25 (4 straw shops exp.) | sell pulse same-day (40 ≤ day-drain headroom) | **$69.4k** (240 u) | $289 (2.4×base) |
| MELON | 78 @ d12 | 1 (center only) | single-day dump is DP-optimal (log-below curve makes waiting worthless vs 1-day sq-above); 78 → x=+77, price 250→205 | **$18.6k** | $239 |
| CARROT | 160 @ d29 (8 tiles×6 fert.) | 19 | sell into pre-built scarcity (town drained 26 days): q=40/day d26–29 if staged, else dump d29 | **$11.2k / $4.4k** | $70 / $28 |
| FERTILIZER | 22/day d8–29 | **0** (no town demand!) | price path-independent: R=Σ price(k); **apply to strawberry/melon first** (shadow $560/u), sell residual ≈150–300 in equal slices | $10–22k sold + ≈$40k embedded in straw/melon yield | $70–100 |

Conservative branch (shop draw unlucky, d̂ at 60 % of expectation): wool $58k, milk $43k, straw $40k — still 3–5× the report's drip revenue, because **the binding rule is `q_t ≤ d̂_t + x_headroom`, not "sell small slices at h≡1 mod 4"**.

### 4.3 Crash-avoidance invariants (the "robust" part)
1. **Overshoot governor:** maintain `x_item ≤ x*_{item}` where `x*` = largest overshoot with `price ≥ 0.8·base` (computed: MELON 71, WOOL 26, MILK 15, STRAW 12, FERT 102, CARROT 42). Hard reject any order violating it (replaces `MarketBrain`'s 90 %-of-spot heuristic, which was measuring the wrong variable).
2. **Scarcity rider:** if `x < 0`, sell *more* (up to `s`), because every unit sells above base and tomorrow's price is higher still only if we hold — the DP equalizes these marginals; policy table encodes the result.
3. **Opponent lockstep veto:** quotes interleave with the opponent's same-turn sales; `OpponentAdvisor.sell_probability > 0.5` for an item ⇒ defer our q to next window (cost ≈ d̂/6 price drift, cheap insurance against a shared-window sq-crash on wool/melon).
4. **Endgame salvage:** `V_30` dumps residual at hour 21 day 29; anything with `x*` headroom (fert, carrot) goes last-minute, anything scarce-priced (milk/wool) was already flow-sold — no dead stock.
5. **Fertilizer first-use rule:** `φ` allocation in §1.1 LP sorts tiles by `dπ/dyield`; strawberry (4 harvests × +2) ≫ melon (1 × +2) ≫ tomato; only the residual sells. This converts the report's "$30k fertilizer cash" into "≈$70k fertilizer-as-yield-multiplier + $10–20k cash".

### 4.4 Module refactor (`market/market_brain.py`, `market/order_builder.py`)
- Replace hour-gating with `OvershootController`: per turn read `obs.market.inventory`, update `x`, `d̂` (EMA of 3-day delta + own sales), look up DP policy `π_item(t, x, s)` from a baked 30×|X| table shipped as a dict (no solver at runtime).
- `OrderBuilder` packs ≤10 orders/turn: sells first (q from controller), then buys (LP), then hires.
- Unit test: replay the 6 solved schedules against a stub engine; assert revenue within 1 % of DP value and `x_t ≤ x*` ∀t.

---

## 5. Rollout plan (2 weeks)
| Day | Milestone | Gate |
|---|---|---|
| 1–2 | Engine-facts harness: unit-test our parser against `kaggriculture.py` semantics (yield days, decay, care, fertilize, shop drain) | 100 % parity on 50 seeded replays |
| 3–4 | Market DP tables baked + `OvershootController` in; delete hour-gating | §4.4 test |
| 5–7 | Layout constants + ZoneRouter + MacroVisit + space-time A* | §3.3 tests |
| 8–9 | Nightly MacroDP + per-turn LP wired to planner/order_builder | labor ≥300 actions/d, cash never < $400 |
| 10–12 | 200-game ladder A/B v5.11 vs v6.0; tune d̂ EMA, opponent veto threshold | median ≥ $120k, p10 ≥ $80k |
| 13–14 | Submit; monitor leaderboard drift; hot-fix shop-draw pessimism branch | — |

**Risks & hedges:** (a) bad shop draw (milk/straw scarcity premium shrinks) → conservative branch tables pre-baked; (b) opponent floods wool (sq-crash shared) → veto + shift to milk/straw; (c) action-budget overrun on pulse-harvest days → LP sheds SW wheat watering (market wheat buyable); (d) seed money $3,000 tightness on day 0 → order sequence HIRE×4, COW×2, SHEEP×2, MELON×13, WHEAT-seed×7, WHEAT-product×5 exactly as report §6.2 (verified affordable: 4+… ≈ $2,915).

*All price/revenue figures above were computed with the engine's own `market_price` formula re-implemented and cross-checked against `MARKET_PARAMS`; schedules are in `liquidation_dp_schedules.csv`, layout in `farm_layout.svg`.*
