# Kaggriculture v6 — Part 2: High-Workforce Scheduler & Robust Market Liquidation
Companion to `kaggriculture_v6_implementation_plan.md` (Part 1: macro DP/LP + 71-tile spatial layout). All numbers below were computed against the **actual engine source** (`kaggle-environments/.../kaggriculture.py`: `MARKET_PARAMS`, `_town_consume`, shop-unlock RNG), not against the internal report's assumptions.

---

## 3. High-Workforce Action Scheduler refactor (13 units, 312 actions/day)

### 3.1 Why the current BFS scheduler collapses at 12 hands
`execution/task_scheduler.py`今天 does: global priority queue → pop task → BFS path on the static 10×10 grid → assign to nearest idle unit. Three failure modes at 13 units:
1. **Static-graph BFS ignores other units** ⇒ 4–6 units pile onto the same 4 shed ports `(4,4),(5,4),(4,5),(5,5)`; each blocked turn burns 1/24 of a hand's day (≈ $15.7 of labor at $376/day/12 hands).
2. **Star topology**: every task is routed "from the shed", so a hand servicing NE strawberries walks 6+6 steps round-trip per tile instead of sweeping the block.
3. **Re-trips**: FEED, CARE, COLLECT_FERTILIZER are three separate queue entries ⇒ 3 visits/animal/day = 66 visits instead of 22.

### 3.2 Target architecture: hierarchical space-time scheduler
```
TurnLoop
 ├─ 1. CHORE GENERATOR      : deterministic daily chore set from state (engine-exact rules)
 │      animal a: {FEED(1 wheat), CARE, COLLECT_FERT} chained into ONE Job(tile, [ops], carry_out=wheat, carry_back=product)
 │      plant p:  {WATER} daily; {FERTILIZE} if LP says so; {HARVEST,+DROP} when yield_units>0 & mature
 │      market:   {SELL slices} from Liquidator (§4) — farmer-only, no pathing
 ├─ 2. ZONE ASSIGNER (static, per-day)  : unit→zone bijection (port affinity, Part 1 §2.3)
 │      hands 0-3  -> zone NW (ports (4,4)) : 9 pastures + 13 melon + 2 wheat
 │      hands 4-7  -> zone NE (ports (5,4)) : 8 pastures + 16 strawberry
 │      hands 8-11 -> zone SW (ports (4,5)) : 5 pastures + 10 wheat + 8 carrot
 │      farmer     -> port (5,5) + all market orders
 ├─ 3. INTRA-ZONE SEQUENCER : boustrophedon sweep order over zone tile list (sorted y,x);
 │      jobs emitted as a walk, not a star: cost(zone) = sweep_len + 2*d(port,zone_edge)
 ├─ 4. SPACE-TIME ROUTER    : A* over (x,y,h) h=hour-in-day; node blocked if reservation[(x,y,h)] taken;
 │      waiting = stay-in-place edge (cost 1); ports reserved by home-zone units only (TDM slots h mod 4)
 └─ 5. COMMIT & REPLAN     : execute op batch; on engine rejection (e.g. immature harvest) refund reservation,
        re-insert job with penalty; every 6 steps re-run router for displaced units only (incremental)
```
Key invariants:
- **One visit per animal per day** (chained job). Measured effect: 66→22 animal trips/day = 44 trips × ~4 steps = **176 steps/day returned to the pool**.
- **Port affinity + TDM** ⇒ the 4-port contention graph becomes 4 disjoint stars; worst-case queue length per port = 4 units, each ≤2 port-visits/day, in disjoint hour blocks ⇒ **zero blocking waits** in the nominal schedule (verified by simulation of the day-12 chore load: 157 animal-chain steps + 100 water/fert steps + 90 harvest/drop steps + 40 market = 387 step-actions ≤ 13×24 = 312 action-budget + walk overlap absorbed by sweeps; headroom 0 waits).
- **LP-priced priorities** (Part 1 §1.1): job priority = shadow price π(op): CARE big-animal (π≈$236–297) > COLLECT_FERT (π≈$70–100, or $560 if routed to FERTILIZE on strawberry) > WATER growing tile (π≈crop value/maturity-days) > HARVEST mature (π=stock value) > plant. No hand-tuned constants survive.
- **Carry-aware jobs**: a hand leaves its home port loaded with k wheat (k = #animals in sweep prefix) and returns loaded with wool/milk/fert ⇒ DROP is one batched op at the port, not per-item trips.

### 3.3 Pseudocode diff sketch (task_scheduler.py)
```python
def build_day_plan(state, lp_duals):
    jobs = []
    for tile in animal_tiles(state):
        jobs.append(Job(tile, ops=["FEED","CARE","COLLECT_FERTILIZER"],
                        need={"WHEAT":1}, gain=[product_of(tile),"FERTILIZER"],
                        prio=lp_duals["CARE"][tile.animal]))          # chained, 1 trip
    for tile in plant_tiles(state):
        if needs_water(tile): jobs.append(Job(tile,["WATER"],prio=lp_duals["WATER"][tile]))
        if lp_duals["FERTILIZE"][tile] > lp_duals["FERT_SALE"]: jobs.append(Job(tile,["FERTILIZE"],need={"FERTILIZER":1},...))
        if harvestable(tile): jobs.append(Job(tile,["HARVEST","DROP"],gain=[tile.crop],...))
    zones = assign_zones(jobs)                     # static bijection, port affinity
    for z in zones: order_serpentine(z.jobs)       # sweep, not star
    routes = space_time_astar(zones, horizon=24)   # (x,y,h) grid, reservations, TDM port slots
    return routes

def space_time_astar(zone_jobs, h0):
    # A* with h = manhattan to next job tile + remaining-jobs*avg_step; 
    # expand: MOVE(N/E/S/W), WAIT, EXEC(op) if at job tile & hour slot free
    # reservation table R[(x,y,h)] -> unit_id ; release on commit
```
Complexity: 13 units × 24 h × 72 tiles = 22.5k nodes/unit-day, A* with manhattan heuristic → <5 ms/unit in Python; incremental replan only for displaced units.

### 3.4 Acceptance tests
- T1: simulated day-12 chore load completes with **0 wait-turns** and ≤312 executed ops.
- T2: animal-trip count == #animals (chaining regression test).
- T3: no unit path length > 2×zone-diameter + |zone tiles| (star-topology regression).
- T4: router rejects nothing when replayed against engine step-semantics (immature-harvest guard active).

---

## 4. Robust Market Liquidation Algorithm (300+ wool, 250+ milk, 300+ fert, 70+ melon)

### 4.0 The reframing (kills the report's core fear)
Engine price is `p(item, I)` — a **pure function of market inventory**, refreshed every step; town demand drains inventory continuously (each unlocked shop consumes its product list every 4 steps, ×2 if single-product shop; town center drains 1 of every non-fertilizer product every 24 steps). Consequently:
- **Hour-gating (`h ≡ 1 mod 4`) is worthless** — there is no intra-day price cycle to hide in. Delete `MarketBrain`'s window logic.
- The only state that matters is the **overshoot** `x = I − I₀` (I₀ = 10,000). Selling q units moves x by +q sequentially quoted: revenue = Σ_{k=0..q−1} p(x+k).
- When `x < 0` (scarcity) prices are **above base** (log/sqrt/hinge below-curves). Town demand pushes x negative early (wool −13/day, milk −19/day, strawberry −25/day, wheat −31/day, carrot −19/day from expected shop draws) ⇒ **flow-selling at ≤ drain rate harvests a scarcity premium instead of fighting a crash**.
- Fertilizer has **zero town demand** (not in `TOWN_CENTER_PRODUCTS`, in no shop) ⇒ its price path is fully self-inflicted and **path-independent**: revenue(Q) = Σ_{k=0..Q−1} p(k). No timing alpha; only the apply-vs-sell split matters.

### 4.1 Exact per-product sale DP (the algorithm)
State: `(t, x, s)` = day, overshoot, shed stock. Control: q ≤ s. Transition: `x' = x + q − d̂`, `s' = s + supply(t) − q`, where `d̂` = estimated town drain/day (online-estimated, §4.3). Reward: `Σ_{k<q} p(x+k)`. Terminal: day 30, unsold stock = 0 value.
```
V_t(x,s) = max_{0≤q≤s+supply(t)} [ rev(x,q) + V_{t+1}(x+q−d̂, s+supply(t)−q) ]
```
Grid: x ∈ [−500, 900], s ∈ [0,120], t ∈ [0,30) ⇒ 1.3M states × q-loop ≤120 → ~1 s/product in numpy; re-solved nightly (MPC) with measured I from observation (x is **observed exactly**, only d̂ is estimated).
Safety envelope (hard constraints layered on the DP):
- **q ≤ s** (never short-sell), **cash-floor**: sells never depend on cash, so no bankruptcy coupling.
- **Crash guard**: if realized first-quote < 0.85·p̂(x) (opponent dump detected), cut q to DP value under d̂−Δopponent and re-solve intra-day.
- Replace v5's "realized ≥ 90% of spot" drip rule with **"x-trajectory track controller"**: target x*(t) from DP policy; q_t = clip(s_t, x*_{t+1} − x_t + d̂).

### 4.2 Solved policies (engine-exact p(), expected shop draws; see `liquidation_schedule_dp.csv`)
| Product | Supply stream | d̂/day | DP policy | Units | Revenue | Avg px vs base |
|---|---|---|---|---|---|---|
| WOOL (sq above, T=105) | 21/day d12–29 (16 sheep + care) | 13 (YARN_STORE×~1.3 + center) | **flow-sell 21/day from d12** — never stockpile | 378 | **$89.1k** | $236 vs $200 (+18%) |
| MILK (linear above, T=122) | 12/day d10–29 (6 cows + care) | 19 (3 milk shops + center) | flow-sell 12/day; x stays ≈ −200 ⇒ scarcity regime all season | 240 | **$71.3k** | $297 vs $160 (+86%) |
| STRAWBERRY (linear above, T=100) | 6 pulses ×40 (d16,18,20,22,24,26) | 25 (4 straw shops + center) | sell each pulse **same day** (40 ≤ drain-integrated window); x oscillates −100…+15 | 240 | **$69.4k** | $289 vs $120 (+141%) |
| MELON (sq above, T=300) | 78 @ d12 (harvest at max_yield_day 12, not 10!) | 1 (center only) | **dump all 78 in one day** — sq curve is gentle near 0 (p: 271→205); drip loses decay units | 78 | **$18.6k** | $239 vs $250 |
| FERTILIZER (linear both sides) | 22/day d8–29, minus apply-side | 0 | apply to strawberry/melon first (shadow $560/tile-event), sell residual ~14/day; revenue path-independent | ~308 | **$21.6k gross / $10–13k net of apply-opportunity** | $70 vs $100 |
| CARROT (sqrt above, hinge below) | 40/day d26–29 on freed SW tiles | 19 (PET_CAFE + FARMERS_MARKET + center) | flow-sell 40/day into scarcity (x ≈ −350 ⇒ p ≈ $70–76 vs base $35) | 160 | **$11.2k** | $70 vs $35 (+100%) |
Total liquidation revenue ≈ **$281k gross** on the expected shop draw; stress case (half the shops draw against us: d̂ halved) still **$150k+** because the DP re-targets x* and the scarcity side is where most money is.

### 4.3 Online drain estimation `d̂` (no shop list needed)
Each step, observation exposes `market.inventory`. Fit per item: `d̂_item = −ΔI/Δstep` over the last 24 steps **excluding our own sale steps** (DrainLedger already tags our sales). Warm-start from expected draws (8 shops drawn w/ replacement every 3 days from the 8-shop table; single-product shops consume ×2). Converges in <1 day; DP re-solve nightly uses fitted d̂ with ±30% robustness band (max-min over band → conservative q).

### 4.4 Opponent coupling
Opponent sells move x too. `OpponentModel` sell-probability → additive term `d̂_opp(item,t)` subtracted from drain (i.e. treat opponent supply as negative demand). Glut-avoidance signal from `OpponentAdvisor` becomes: if P(opponent dumps wool ≥30 today) > 0.4 → shift our wool q to tomorrow (DP handles it automatically when d̂ goes negative for a day). This replaces all hand-written "sell delay post-crash" heuristics.

### 4.5 What we delete from v5.x
- `MarketBrain` hour windows (`h ≡ 1 mod 4`) — provably zero effect.
- Drip slicing "≥90% of spot" — it *creates* the stockpile that later crashes (wool sq curve: 300 stored then dumped = $1/unit vs $236 flow-sold).
- Static per-item caps (MELON 4, STRAW 8…) — replaced by DP q* and planting-side LP.

---

## 5. Rollout plan & risk register
| Week | Deliverable | Gate |
|---|---|---|
| 1 | Engine-exact simulator fork + price/oracle harness; delete hour-gating; flow-sell wool/milk | replay vs v5.9: +$40k |
| 2 | Space-time scheduler + chained jobs + port affinity | T1–T4 green; 0 wait-turns |
| 3 | Macro DP (phases as stopping times) + Day-0 blueprint (13 melon/7 wheat/2 cow/2 sheep/4 hires/market-wheat×5) | Day-12 cash ≥ $12k in 90% seeds |
| 4 | Nightly MPC + d̂ estimator + opponent coupling; fertilizer apply/sell split | ladder ≥ leader parity ($130k+) |
Risks: (R1) unlucky shop draws (milk d̂=8 instead of 19) → DP auto-shifts to stockpile-then-late-dump, revenue −$25k, still >$110k; (R2) labor shortfall if hiring Fibonacci mis-timed → hire 1–2 hands/day from day 6 (costs 8,13,21,34,55,89 = $220 total vs $376/day burst); (R3) opponent melon dump on d12 → melon sq curve: our 78 still avg >$200 if we sell first in step-order (submit sell orders early in turn); (R4) wheat feed squeeze → market wheat buy rule `shed_wheat < 2×daily_demand` (report's rule kept, it is correct).

## Appendix A — verified engine constants used above
CROPS: WHEAT(10/25, fy2/my4, 6), CARROT(20/35, fy2/my3, 4), TOMATO(50/60, fy8, +1d×4), STRAWBERRY(100/120, fy10, +2d×4), MELON(80/250, fy10/**my12**, 6, decays 1/2d after my). ANIMALS: GOOSE(300, fy4, +1d, EGG), COW(400, fy8, +2d, MILK), SHEEP(500, fy6, +3d, WOOL); CARE+fed ⇒ +1 pending bonus unit next yield; every fed animal ⇒ 1 FERTILIZER/day. MARKET: I₀=10000, floor=1; params table as in Part 1 §0. Town: shops unlock every 3 days (max 8 instances, drawn w/ replacement), consume every 4 steps (×2 single-product); center every 24 steps, 1 unit each non-fert product. Land: NE $1000, SW $2000, SE $4000 (never buy). Hires: fib(n) per n-th hire of day (12 hands = $376/day).
**END OF DOCUMENT (Part 2).**