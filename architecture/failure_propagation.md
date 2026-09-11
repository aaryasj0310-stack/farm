# Kaggriculture Failure-Propagation Graph

> **Target Environment**: Kaggle Environments `kaggriculture`  
> **Source Package**: `submission/`  
> **Purpose**: Maps causal chains, systemic ripple effects, and failure propagation when formulas, assumptions, state trackers, or execution logic fail.

---

## 1. Failure Severity Classification & Lifecycle Status

### Severity Definitions
- **`[P0]` Catastrophic**: Causes game loss, match disqualification, permanent loss of 25+ tiles, animal starvation/death, or engine crashes.
- **`[P1]` Major Degradation**: Severe economic loss ($\ge \$10,000$), systemic harvest decay, worker lock-up, market paralysis, or missed production cycles.
- **`[P2]` Minor Inefficiency**: Suboptimal travel distances, minor price slippage ($<\$2,000$), transient task churn, or slight telemetry distortion.

### Failure Lifecycle Statuses
- **`[REGRESSION_GUARD]`**: Invariant actively protected by runtime checks or architectural constraints; failure was historically observed and patched.
- **`[MITIGATED]`**: Robust multi-layered heuristics or recovery paths actively prevent propagation under normal conditions.
- **`[ACTIVE / PARTIALLY_MITIGATED]`**: Partially protected for specific subsystems (e.g., Melon), but active vulnerabilities remain exposed in other subsystems.
- **`[ACTIVE STRATEGIC SIZING RISK / REGRESSION GUARDED]`**: Hard bounds prevent catastrophic unbounded execution, but rigid sizing introduces strategic inefficiency.
- **`[HYPOTHETICAL]`**: Modeled theoretical failure edge case with low observed occurrence.

---

## 2. Land & Strategic Expansion Failures

### Chain 1: Market-Order Saturation & Land Starvation (`FAIL-LAND-01`) — `[REGRESSION_GUARD]`
*Root cause resolved in v5.12: When 10 HIRE orders consumed all 10 turn slots, `BUY_LAND` was dropped. Guarded by `DEC-SLOT-01` (`FORM-SLOT-01`) Hour 0 slot reservation and Hour 1 deferred hiring.*

```mermaid
flowchart TD
    F1["[P0] FAIL-MKT-01: Market Order Slot Saturation
    Target hands = 10+ emits 10 HIRE orders at Hour 0"]
    F2["[P0] FAIL-LAND-01: BUY_LAND Dropped (land_slots)
    slots == 0 when reaching TIER_LAND"]
    F3["[P0] FAIL-LAND-02: Window Closure Lockout
    Day 14+ permanently blocks SW unlock (current_day > 13, RULE-LAND-06)"]
    F4["[P1] FAIL-CAP-01: 25 SW Tiles Never Unlocked
    Farm capped at 50 tiles (NW + NE)"]
    F5["[P1] FAIL-CAP-02: SW Land Capacity Starved
    Lost 15 Wheat/Carrot soil tiles, 9 pasture tiles, 1 portal"]
    F6["[P0] Catastrophic Score Loss (Severe margin collapse)"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
```

---

### Chain 2: Overly Conservative Treasury Gate & Delayed Unlock (`FAIL-LAND-03`) — `[RESOLVED / MITIGATED]`
*Mitigated by dynamic net seed tranche and removal of hard Day-13 cutoff (`RULE-LAND-06`); purchase is governed dynamically by economic payback (`expected_remaining_profit_from_SW > land_price + incremental_support_costs`), labor serviceability, and treasury feasibility through Day 25.*

```mermaid
flowchart TD
    F1["[P1] FAIL-TREAS-01: Treasury Hoarding / Shortfall
    Over-buffering feed wheat or labor acquisition capital in should_buy_land()"]
    F2["[P1] FAIL-LAND-03: Land Purchase Evaluated Dynamically
    Dynamic payback and labor checks permit late unlock if profitable"]
    F3["[P1] Dynamic Window Closes at Day 25 (opportunity_window_factor)
    Only blocks when remaining days cannot pay back land + support costs"]
    F4["[P1] Controlled Capital Allocation"]

    F1 --> F2 --> F3 --> F4
```

---

## 3. Livestock & Feed Chain Failures

### Chain 3: Feed Staging Failure & Animal Starvation (`FAIL-FEED-01`) — `[MITIGATED]`
*Guarded by dual-priority architecture: Priority 86 staging + Priority 85 feed, backed by P99 emergency feed rescue when consecutive_unfed >= 1 (with P100 reserved for survival water).*

```mermaid
flowchart TD
    F1["[P1] FAIL-STG-01: Feed Staging Missed (P86)
    No worker executes PICKUP WHEAT from shed"]
    F2["[P1] FAIL-HOLD-01: Wheat-Holder Mismatch
    Eligible workers nearby hold no wheat in inventory"]
    F3["[P1] FAIL-FEED-02: Production Feed Missed
    Animal unfed before turn 24 end-of-day refresh"]
    F4["[P1] FAIL-CARE-01: Banked Care Bonus Wiped
    Cow/Sheep yield multiplier resets to baseline"]
    F5["[P0] FAIL-SURV-01: Consecutive Unfed == 1 (Danger)
    Animal enters starvation survival state"]
    F6{"P99 Emergency Feed Rescue
    Executed Today?"}
    F7["[P0] ANIMAL DIES (-$400/$500 capital + permanent loss)"]
    F8["[P1] Survival Disruption (P99 emergency feed preempts routine work)"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
    F6 -->|No| F7
    F6 -->|Yes| F8
```

---

### Chain 4: Shed Overflow & Placement Blockage (`FAIL-SHED-01`) — `[MITIGATED]`
*Mitigated by 3-tier sell pressure: soft cap at 65, midnight hard guard at 88, and end-of-season liquidation.*

```mermaid
flowchart TD
    F1["[P1] FAIL-SHED-01: Shed Reaches 100 Capacity
    Unsold produce and bought animals fill shed"]
    F2["[P1] FAIL-HARV-01: Harvests Blocked
    Workers cannot drop harvested crops/animal yields"]
    F3["[P0] FAIL-DECAY-01: Field Decay Kills Produce
    Ripe crops decay on field losing 100% value"]
    F4["[P1] FAIL-PLACE-01: Purchased Animals Trapped in Shed
    Cannot build pasture or place animals onto land"]
    F5["[P1] Heavy Capital Sunk with Zero Amortization"]

    F1 --> F2 --> F3
    F1 --> F4 --> F5
```

---

## 4. Labor, Dispatch & Spatial Failures

### Chain 5: Stale Sticky Missions & Travel Churn (`FAIL-EXEC-01`) — `[ACTIVE / PARTIALLY_MITIGATED]`
*Root causes arise from long cross-quadrant routes, stale missions persisting after surrounding context changes, or task reprioritization churn. Mitigated by mission validity checking, consecutive_no_progress tracking (release at $\ge 4$), mission_age limit (release at $> 40$), urgent-task preemption (prio $\ge 100$ or feed rescue), and completion/invalidation release.*

```mermaid
flowchart TD
    subgraph CAUSES["Possible Root Causes"]
        RC1["Long Cross-Quadrant Routes
        (Travel across distant quadrants)"]
        RC2["Stale Sticky Mission
        (Surrounding work changes while worker en route)"]
        RC3["Task Reprioritization Churn
        (Mission becomes invalid before worker arrives)"]
    end

    F1["[P1] FAIL-STICKY-01: Long-Distance / Stale Sticky Mission
    Worker remains committed across multiple turns"]
    F2["[P2] FAIL-CHURN-01: High Movement Share / Delayed Reassignment
    Repeated travel without enough productive operations"]
    F3["[P1] Routine Local Work Backlog
    Nearby routine watering, harvesting, and care delayed"]
    F4["[P1] Water, Harvest, and Care Tasks Become Urgent
    consecutive_unwatered reaches 1, crops near decay, animals un-cared"]
    F5["[P0] Survival Tasks Preempt Routine Work
    P100 survival water / P99 feed rescue break mission lock to save assets"]

    subgraph MITIGATIONS["Active Mitigations in task_scheduler.py"]
        M1["Mission Validity Checking & Invalidation Release"]
        M2["consecutive_no_progress >= 4 Tracking Release"]
        M3["mission_age > 40 Limit Release"]
        M4["Urgent-Task Preemption (Prio >= 100 or feed_rescue)"]
        M5["Task Completion Release"]
    end

    RC1 --> F1
    RC2 --> F1
    RC3 --> F1
    F1 --> F2
    F2 --> F3
    F3 --> F4
    F4 --> F5

    MITIGATIONS -.->|Breaks Lock / Releases Worker| F1
    MITIGATIONS -.->|Preempts Locked Unit| F5
```

---

### Chain 6: Under-Hiring vs Over-Hiring Disruption (`FAIL-HIRE-01`) — `[ACTIVE STRATEGIC SIZING RISK / REGRESSION GUARDED]`
*Guarded against runaway Fibonacci hiring explosion by static DAY_TO_HANDS schedule; but actively risks strategic over-hiring on 50-tile farms when SW unlock fails.*

```mermaid
flowchart TD
    subgraph UNDER_HIRE["Under-Hiring (Guarded by Base Hands)"]
        U1["[P1] Labor Shortage (<4 hands early game)"]
        U2["Action Deficit: Cannot water 25 crops + feed animals"]
        U3["[P0] Crop Dehydration & Animal Production Misses"]
    end

    subgraph OVER_HIRE["Over-Hiring (Active Strategic Sizing Risk)"]
        O1["[P1] Static Schedule Forces 12 Hands on Day 11"]
        O2["SW Land Purchase Failed -> Farm Capped at 50 Tiles"]
        O3["[P1] Incremental Fibonacci Hire Acquisition Cost + Low-Utilization Capital Inefficiency"]
        O4["[P1] Treasury Depletion Starves Late Seed & Animal Capital"]
    end

    U1 --> U2 --> U3
    O1 --> O2 --> O3 --> O4
```

---

## 5. Market Trading & Pricing Failures

### Chain 7: Crop Self-Glut & Monoculture Price Collapse (`FAIL-MKT-02`) — `[REGRESSION_GUARD]`
*Guarded by committed crop counting (`FORM-CROP-01`), quadratic supply feedback, and hard crop tile caps (`RULE-CROP-01`).*

```mermaid
flowchart TD
    F1["[P1] FAIL-GLUT-01: If FORM-CROP-01 Regresses
    Scorer evaluates only live tiles, ignoring planned today"]
    F2["[P1] Monoculture Over-Planting (e.g., 25 Melons)"]
    F3["[P1] Market Inventory Ingestion Exceeds 12,000"]
    F4["[P1] Quadratic Price Drop: Melon falls from $250 -> $1 floor"]
    F5["[P1] Floor Hold Freezes Shed Stock; Recovery Fails"]
    F6["[P0] Negative ROI on Seeds & Labor Sunk"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
```

---

### Chain 8: Bad Sell Timing & Dumping into Depressed Markets (`FAIL-MKT-03`) — `[ACTIVE / PARTIALLY_MITIGATED]`
*Melon is protected by drip sizing (`FORM-DRIP-01`) and floor hold ($1). Non-Melon commodities sell in fixed batch sizes with uncalled carry gain checks (`FORM-CARRY-01` dormant), exposing them to spot price depression.*

```mermaid
flowchart TD
    F1["[P1] Non-Melon Generic Carry Check Dormant (FORM-CARRY-01)
    _reason() uncalled; MarketBrain sells without intertemporal forecast"]
    F2["[P1] Non-Melon Phase Batch Targets (D0-5: 15, D6-8: 7, D9+: 4)
    Drip sizing FORM-DRIP-01 active ONLY for Melon"]
    F3["[P1] Spot <= 1 Sets Non-Melon Priority = 0.95
    Does NOT bypass sell window or hold stock"]
    F4["Dumping Fixed Batches into Elevated Market Inventory"]
    F5["[P1] Severe Realized-Price Slippage on Non-Melon Goods"]

    F1 --> F4
    F2 --> F4
    F3 --> F4
    F4 --> F5
```

---

## 6. Opponent Modeling & State Leakage Failures

### Chain 9: State Leakage Across Match Episodes (`FAIL-STATE-01`) — `[REGRESSION_GUARD]`
*Guarded by primary episode boundary detection in `state_tracker.get_state()` (tracking day/step rewind) and registered reset hooks / main reset integration, resetting opponent trackers on day 0.*

```mermaid
flowchart TD
    F1["[P1] FAIL-LEAK-01: Episode Reset Missed in state_tracker.get_state()
    day=0 check fails because episode.last_day not cleared"]
    F2["[P1] Stale Opponent Sales & Shed Inventories Persist"]
    F3["[P2] Hallucinated Dump Predictions & Erroneous Delays"]
    F4["[P1] Unwarranted Preemptive Sells at Bad Market Hours"]

    F1 --> F2 --> F3 --> F4
```

---

## 7. System Exceptions & Fallback Activation

### Chain 10: Unhandled Exception in Strategic Pipeline (`FAIL-EXC-01`) — `[MITIGATED]`
*Guarded by domain-isolated execution in `main.py`: Strategic failure triggers survival fallback, while Market sell execution runs independently in its own protected block.*

```mermaid
flowchart TD
    F1["[P0] Unhandled Bug in MacroPlanner or TaskScheduler"]
    F2["Try/Except Catches Crash in Strategy Layer of main._agent_decision()"]
    F3["[P1] _LAST_FALLBACK_DIAGNOSTIC Records Traceback"]
    F4["[P1] _survival_fallback_from_ctx() Dispatches Survival Actions
    Emergency feeds & waters keep animals and crops alive"]

    subgraph ISOLATED_MARKET["Domain-Isolated Market Layer"]
        M1["MarketBrain.sell_orders() Executes in Separate Try/Except"]
        M2["Sell Orders Successfully Compiled & Dispatched!
        Cash generation continues uninterrupted"]
    end

    F5{"Did Entire
    _agent_decision Crash?"}
    F6["[P0] _emergency_fallback() Activates"]
    F7["_survival_fallback_raw(obs) Emits Blind Emergency Actions"]

    F1 --> F2 --> F3 --> F4
    F2 -.->|Strategy Error Does Not Block Market| M1 --> M2
    F4 --> F5
    F5 -->|Yes: Outer Crash| F6 --> F7
    F5 -->|No: Strategy Handled| M2
```
