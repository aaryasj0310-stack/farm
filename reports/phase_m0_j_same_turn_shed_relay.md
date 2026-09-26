# Phase M0-J: Same-Turn Shed Relay & Inventory Handoff Exploitation Report

## Executive Summary

Phase M0-J investigated whether the agent can eliminate inventory handoff latency by exploiting the Kaggriculture engine's sequential worker execution ($u = 0, 1, 2...$): allowing a later worker $u_B > u_A$ at shed access tiles to execute a same-turn `PICKUP` for items deposited earlier in the same turn by worker $u_A$ (via `DROP` or `PLACE`), rather than waiting for a subsequent turn.

Real-engine microtests (Part A) proved that the game engine (`kaggle_environments.envs.kaggriculture.kaggriculture`) natively supports same-turn shed relay across all product, grain, fertilizer, and animal types: because worker actions execute in strict ascending index order and mutate the shared `observation.private` object immediately, items deposited by worker $u_A$ are instantly visible to worker $u_B > u_A$ in the same step.

However, the authoritative 100-match baseline audit (seeds 96501–96510 $\times$ 5 benchmark opponents $\times$ 2 seats, 72,000 steps) and counterfactual Oracle simulation demonstrated that **in practice, same-turn shed relay provides zero useful acceleration and produces negative terminal value**:

* **Mechanically Useful Opportunities:** **0.00 / match** during active farming.
  * Although 29.89 worker-order-valid pairs occur per match, **91.1% (2,722 / 2,989) occur on Day 29 during endgame liquidation**, where candidate workers are performing `DROP` to liquidate their own goods.
  * Across Days 0–28, only 267 valid pairs occur across 100 matches (2.67 / match), and **100% of them occur at Hour 22–23 (midnight rollover)** when all daily animal feeds are already completed (`unfed_animals == 0`) and workers are returning to the shed to deposit goods before the midnight rollover.
  * In baseline play, **wheat for animal feeding is purchased at market** (which lands directly in `private["shed"]` without any worker deposit) and staged in morning chunks. Field workers do not harvest and deposit wheat while other workers wait at the shed to feed.
  * Saleable harvested products (berries, melons, carrots, milk, wool) are deposited into the shed to be **SOLD** by MarketBrain; picking them back out has zero economic value and actively sabotages sales.
* **Counterfactual Oracle Terminal Gain:** **-$187.69 / match** (Decision Gate B Threshold: **+$250.00 / match**).
  * **Win / Tie / Loss Record:** 2W / 35T / 63L
  * **Median Delta (P50):** **-$94.00**
  * **Seed-Clustered 95% CI:** **[-$249.94, -$125.44]** (df=9, SE=$27.52)
  * **Positive Seed Clusters:** **0 / 10** (100% negative or neutral)

### Decision Gate Outcomes
```text
GATE A: Opportunity Frequency
Observed Valid Opportunities: 29.89 / match (Threshold: >= 0.25 / match)
STATUS: GATE A PASSED (due to Endgame Liquidation clustering)

GATE B: Oracle Economic Value
Observed Oracle Gain: -$187.69 / match (Threshold: >= +$250.00 / match)
STATUS: DECISION GATE B FAILED (Net negative terminal value across all 10 seed clusters)

VERDICT: M0-J CLOSED — same-turn relay opportunities are too rare
```

In accordance with the experimental specification, Phase M0-J terminates. No prospective treatment was enabled in production code, no speculative relay behavior was added, and all runtime invariants remain preserved.

---

## Part A: Real-Engine Microtest Verification

All 8 real-engine microtests executed against `kaggriculture.py` passed with 100% compliance:

| Test ID | Mechanic Verified | Forward Outcome | Reverse Outcome | Key Verification Metric |
| :--- | :--- | :--- | :--- | :--- |
| **A1** | Earlier DROP $\to$ Later PICKUP | **SUCCESS** | **FAILED** | Unit 0 `DROP` WHEAT 1; Unit 1 `PICKUP` WHEAT 1 same turn ($u_0=0, u_1=1, \text{shed}=0$) |
| **A2** | Reverse Worker Ordering | **FAILED** | **SUCCESS** | Unit 0 `PICKUP` fails when Unit 1 deposits later in same turn ($u_0=0, u_1=0, \text{shed}=1$) |
| **A3** | PLACE-to-shed $\to$ Later PICKUP | **SUCCESS** | N/A | Adjacent `PLACE` into shed access tile deposits 1 unit, available for later `PICKUP` |
| **A4** | Product Type Generality | **SUCCESS** | N/A | Relay verified across WHEAT, FERTILIZER, MILK, WOOL, STRAWBERRY |
| **A5** | Animal Relay Mechanics | **SUCCESS** | N/A | Live COW / SHEEP in worker inventory can be deposited and picked up |
| **A6** | Shed Capacity Bounds | **SUCCESS** | N/A | Full shed (100/100) blocks earlier DROP; earlier PICKUP frees headroom for later DROP |
| **A7** | Multi-Relay Independence | **SUCCESS** | N/A | Simultaneous relays (Unit 0 $\to$ 1 WHEAT; Unit 2 $\to$ 3 FERTILIZER) execute independently |
| **A8** | Single Action Invariant | **SUCCESS** | N/A | Engine strictly enforces exactly 1 action per unit per turn (PICKUP + FEED impossible) |

All microtest artifacts are stored under `simulations/results/phase_m0_j_engine_verification/`.

---

## Parts C–M: Authoritative 100-Match Baseline Logistics Audit

### 1. Panel Configuration
* **Seeds:** `96501–96510` (10 seeds)
* **Opponents:** `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent` (5 opponents)
* **Seats:** `Seat 0`, `Seat 1` (2 seats)
* **Total Matches:** 100 matches (72,000 engine steps)
* **Total Runtime:** 456.12 seconds

### 2. Shed Deposit & Handoff Latency Distribution
Across all 72,000 steps:
* **Total Worker Deposits:** 2,645 events (26.45 / match; 5,720 total units)
  * Days 0–28: 569 events (5.69 / match)
  * Day 29 (Endgame Liquidation): 2,076 events (20.76 / match, 78.5% of all deposits)
* **Total Worker Pickups:** 11,200 events (112.00 / match)

| Handoff Delay | Deposited Units | % of Deposited Inventory | Mechanical Role |
| :--- | :--- | :--- | :--- |
| **0-Turn Delay (Relay)** | **0** | **0.00%** | Zero same-turn pickups in baseline |
| **1-Turn Delay** | **16** | **0.28%** | Rare next-turn wheat pickup |
| **2+-Turn Delay** | **979** | **17.12%** | Stored feed wheat or staging |
| **Never Picked Up** | **4,725** | **82.60%** | Sold directly from shed by MarketBrain or liquidated |

### 3. Worker-Order Feasibility Breakdown
Across all 34,370 worker pairs evaluated during turns with active deposits:

| Feasibility Category | Total Count | % of All Pairs | Mean / Match | Description |
| :--- | :--- | :--- | :--- | :--- |
| **ORDER_REVERSED** | 15,652 | 45.54% | 156.52 | Worker $u_B < u_A$ acted before depositor $u_A$ |
| **WORKER_NOT_AT_SHED** | 13,079 | 38.05% | 130.79 | Worker $u_B > u_A$ was elsewhere on the farm |
| **SAME_WORKER_IMPOSSIBLE** | 2,645 | 7.70% | 26.45 | Single action invariant blocks same worker pick/use |
| **ORDER_VALID** | **2,989** | **8.70%** | **29.89** | Worker $u_B > u_A$ at shed during/after deposit |
| **NO_FREE_ACTION** | 5 | 0.01% | 0.05 | Worker $u_B$ blocked by critical task |

### 4. Displaced Action Inventory
For the 2,989 `ORDER_VALID` candidates:
* **`DROP` (1,314 events, 44.0%):** Worker $u_B$ was also at the shed executing its own deposit mission (liquidation or midnight storage).
* **`MOVE` (1,152 events, 38.5%):** Worker $u_B$ was transiting past the shed access tiles on an active assignment.
* **`PASS` (520 events, 17.4%):** Worker $u_B$ was idle at the shed.
* **`WATER` / Other (8 events, 0.3%):** Productive field actions.

---

## Parts N–T: Counterfactual Oracle Simulation (Decision Gate B)

### 1. Paired Economic Results (100 Matches)

| Metric | Historical Baseline (C0) | Oracle Relay Treatment | Paired Delta |
| :--- | :--- | :--- | :--- |
| **Mean Final Cash** | **$100,437.04** | **$100,249.35** | **-$187.69** |
| **Median Final Cash (P50)** | $98,412.00 | $98,318.00 | **-$94.00** |
| **Win / Tie / Loss** | — | — | **2W / 35T / 63L** |
| **P10 / P25 Delta** | — | — | **-$444.00 / -$179.00** |
| **P75 / P90 Delta** | — | — | **+$0.00 / +$0.00** |
| **Best / Worst** | — | — | **+$5.00 / -$1,393.00** |
| **Seed-Clustered 95% CI** | — | — | **[-$249.94, -$125.44]** |
| **Positive Seed Clusters** | — | — | **0 / 10** |

### 2. Breakdown by Opponent

| Opponent | Matches | Baseline Mean Cash | Oracle Mean Cash | Mean Paired Delta |
| :--- | :--- | :--- | :--- | :--- |
| **pass** | 20 | $104,112.50 | $103,980.20 | -$132.30 |
| **pure_wheat_rush** | 20 | $98,450.10 | $98,245.60 | -$204.50 |
| **cow_milk_engine** | 20 | $101,890.30 | $101,675.05 | -$215.25 |
| **melon_sniper** | 20 | $99,240.80 | $99,072.10 | -$168.70 |
| **full_production_agent** | 20 | $98,491.50 | $98,273.80 | -$217.70 |
| **ALL OPPONENTS** | **100** | **$100,437.04** | **$100,249.35** | **-$187.69** |

### 3. Forensic Analysis: Why Oracle Relay Loses Value

1. **Structural Decoupling of Logistics:**
   * Feed wheat is purchased directly at the market at Hour 0, depositing into `private["shed"]` without worker transit. Workers stage pickup from this stock in the morning.
   * Field workers rarely harvest wheat during the season because wheat yields only $10 spot revenue vs Strawberry ($100) or Melon ($80).
2. **Harmful Action Displacement:**
   * Displacing worker `DROP` on Day 29 prevents harvested crops from entering the shed before market closing, causing crops to remain stranded in worker inventory and unsold at season end.
   * Forcing a worker to pick up items at Hour 22–23 displaces midnight storage protection, causing workers to hold unnecessary items through the midnight overflow barrier.
3. **Product Destruction Risk:**
   * Picking saleable products (strawberries, melons, milk, wool) out of the shed reduces the inventory available to MarketBrain for scheduled high-price sales, directly cannibalizing cash generation.

---

## Authoritative Answers to the 34 Final Questions

1. **Can an earlier worker deposit an item and a later worker pick it up in the same turn?**
   **Yes**. Confirmed in real engine (`kengine.interpreter`). Sequential action application mutates `private["shed"]` in real time.
2. **Does reverse worker ordering fail?**
   **Yes**. Confirmed in Test A2. If $u_B < u_A$, $u_B$'s pickup executes before $u_A$'s deposit and fails.
3. **Which inventory types support same-turn relay?**
   Generic across all items: `WHEAT`, `FERTILIZER`, `MILK`, `WOOL`, `STRAWBERRY`, `CARROT`, `TOMATO`, `MELON`, and live livestock tokens.
4. **How many theoretical relay opportunities occur per match?**
   **343.70 pairs / match** (34,370 total pairs evaluated across 100 matches).
5. **How many are worker-order valid?**
   **29.89 / match** (2,989 total pairs).
6. **How many are action-feasible?**
   **29.89 / match** have legal ordering and worker presence, but 91.1% occur during Day 29 liquidation. During active season (Days 0–28), only **2.67 / match** are action-feasible.
7. **How many currently incur at least one turn of handoff latency?**
   **0.28%** (16 out of 5,720 deposited units). 82.60% of deposited units are sold directly from the shed and never picked up.
8. **Which resource creates most relay opportunities?**
   `PRODUCT_LOGISTICS` (11.02 valid pairs/match), followed by `FERTILIZER_APPLICATION` (9.62/match) and `WHEAT_FEED` (9.25/match).
9. **How many WHEAT relay opportunities occur?**
   **9.25 / match** (925 total). 794 on Day 29; only 1.31 / match during Days 0–28, all at Hour 22–23 rollover.
10. **How many FERTILIZER relay opportunities occur?**
    **9.62 / match** (962 total). 946 on Day 29; only 0.16 / match during Days 0–28, all at Hour 23.
11. **How many animal relay opportunities occur?**
    **0.00 / match**. Purchased animals land directly in the shed from market; workers never deposit live animals into the shed.
12. **What actions would relay PICKUP displace?**
    `DROP` (44.0%), `MOVE` (38.5%), `PASS` (17.4%), `WATER` (0.2%), `LOW_PRIORITY_FALLBACK` (0.1%).
13. **How often would it displace PASS?**
    **5.20 times / match** (17.4% of valid candidates).
14. **How often would it displace useful work?**
    **24.66 times / match** (82.5% of valid candidates), displacing liquidation drops or necessary transit.
15. **How many PICKUP turns can be accelerated?**
    **0.00 turns / match**. In zero observed instances did an earlier worker deposit wheat while an animal was unfed.
16. **How many FEED tasks can be accelerated?**
    **0.00 tasks / match**. All daily feeds are satisfied in Hours 0–3 using market-purchased shed inventory.
17. **Does relay rescue any production-day feed?**
    **No** (0 production feeds rescued).
18. **Does relay preserve care-bank bonuses?**
    **No** (0 impact on care-bank).
19. **Does fertilizer relay increase crop output?**
    **No**. All early fertilizer candidates occurred at Hour 23, where pickup cannot accelerate crop maturity before midnight.
20. **Does relay change same-turn market sellable inventory?**
    **Yes, adversely**. Picking up shed items can reduce available stock for MarketBrain's scheduled sales.
21. **Does relay change storage pressure?**
    **Yes, adversely**. Displacing worker drops leaves workers holding inventory across midnight rollover.
22. **What is mean oracle terminal gain?**
    **-$187.69 / match**.
23. **What is median oracle gain?**
    **-$94.00 / match**.
24. **What is P90 oracle gain?**
    **+$0.00 / match**.
25. **Which subclass drives oracle value?**
    **None**. All subclasses produce $\le \$0.00$ marginal terminal value.
26. **Is oracle value large enough for LIVE?**
    **No**. -$187.69 < +$250.00 threshold.
27. **If LIVE tested, what is paired mean terminal delta?**
    Not tested in LIVE (Decision Gate B failed). Oracle paired mean delta is -$187.69.
28. **What is median/P50?**
    Not tested in LIVE (Oracle P50 is -$94.00).
29. **What is seed-clustered 95% CI?**
    **[-$249.94, -$125.44]** (df=9, SE=$27.52).
30. **How many seed clusters are positive?**
    **0 / 10 positive seed clusters**.
31. **Were any feed/safety regressions introduced?**
    Zero engine violations, but economic regression occurs due to lost sales and action displacement.
32. **Were any inventory conservation violations found?**
    **Zero** (0 conservation errors across all 100 matches).
33. **Is M0-J independently valuable?**
    **No**. The shed is an endpoint buffer for sales and market buys, not an active intraday worker relay station.
34. **Should M0-J later be tested with M0-D?**
    **No**. M0-J is permanently closed. M0-D (Storage Rescue) remains the sole validated storage improvement (+$5,056.89).

---

## Deliverables Summary

| Artifact Path | Description |
| :--- | :--- |
| [`reports/phase_m0_j_same_turn_shed_relay.md`](file:///d:/website%20project/kaggri%20ox/reports/phase_m0_j_same_turn_shed_relay.md) | Authoritative comprehensive phase report answering all 34 questions |
| [`scripts/verify_same_turn_shed_relay.py`](file:///d:/website%20project/kaggri%20ox/scripts/verify_same_turn_shed_relay.py) | Engine microtests verifying real-engine sequential execution semantics |
| [`scripts/audit_same_turn_shed_relay.py`](file:///d:/website%20project/kaggri%20ox/scripts/audit_same_turn_shed_relay.py) | 100-match baseline shed handoff latency & feasibility audit |
| [`scripts/run_phase_m0_j_oracle.py`](file:///d:/website%20project/kaggri%20ox/scripts/run_phase_m0_j_oracle.py) | 100-match paired counterfactual Oracle simulation |
| [`agent/tests/test_same_turn_shed_relay.py`](file:///d:/website%20project/kaggri%20ox/agent/tests/test_same_turn_shed_relay.py) | 22 comprehensive unit tests covering all verification criteria |
| `simulations/results/phase_m0_j_engine_verification/` | 7 JSON verification artifacts for engine microtests |
| `simulations/results/phase_m0_j_relay_audit/` | 9 JSON baseline audit artifacts (latency, feasibility, subclasses) |
| `simulations/results/phase_m0_j_oracle/` | 10 JSON counterfactual Oracle artifacts |
