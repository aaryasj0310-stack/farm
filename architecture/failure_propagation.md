# Kaggriculture Failure-Propagation Graph

> **Target Environment**: Kaggle Environments `kaggriculture`  
> **Source Package**: `submission/`  
> **Purpose**: Maps causal chains, systemic ripple effects, and failure propagation when formulas, assumptions, state trackers, or execution logic fail.

---

## 1. Failure Severity Classification

- **`[P0]` Catastrophic**: Causes game loss, match disqualification, permanent loss of 25+ tiles, animal starvation/death, or engine crashes.
- **`[P1]` Major Degradation**: Severe economic loss ($\ge \$10,000$), systemic harvest decay, worker lock-up, market paralysis, or missed production cycles.
- **`[P2]` Minor Inefficiency**: Suboptimal travel distances, minor price slippage ($<\$2,000$), transient task churn, or slight telemetry distortion.

---

## 2. Land & Strategic Expansion Failures

### Chain 1: Market-Order Saturation & Land Starvation (`FAIL-LAND-01`)
*Root cause resolved in v5.12: When 10 HIRE orders consumed all 10 turn slots, `BUY_LAND` was dropped.*

```mermaid
flowchart TD
    F1["[P0] FAIL-MKT-01: Market Order Slot Saturation
    Target hands = 10+ emits 10 HIRE orders at Hour 0"]
    F2["[P0] FAIL-LAND-01: BUY_LAND Dropped (land_slots)
    slots == 0 when reaching TIER_LAND"]
    F3["[P0] FAIL-LAND-02: Window Closure Lockout
    Day > 13 triggers sw_window_closed_after_day_13"]
    F4["[P1] FAIL-CAP-01: 25 SW Tiles Never Unlocked
    Farm capped at 50 tiles (NW + NE)"]
    F5["[P1] FAIL-CAP-02: Strawberry & Wheat Land Starved
    Lost 475 tile-days of production"]
    F6["[P0] Catastrophic Score Loss (-$36,000+ margin loss)"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
```

---

### Chain 2: Overly Conservative Treasury Gate & Delayed Unlock (`FAIL-LAND-03`)

```mermaid
flowchart TD
    F1["[P1] FAIL-TREAS-01: Excessive Treasury Hoarding
    Over-buffering feed wheat or wages in should_buy_land()"]
    F2["[P1] FAIL-LAND-03: Land Purchase Delayed Past Day 11
    shortfall reported despite positive cash balance"]
    F3["[P1] FAIL-CROP-01: Strawberry Planting Window Closed
    Misses Day 13 Strawberry deadline (3 harvests impossible)"]
    F4["[P2] Forced Pivot to Lower Margin Crops (Carrots)"]
    F5["[P1] Reduced Seasonal Revenue (-$15,000+)"]

    F1 --> F2 --> F3 --> F4 --> F5
```

---

## 3. Livestock & Feed Chain Failures

### Chain 3: Feed Staging Failure & Animal Starvation (`FAIL-FEED-01`)

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
    F6{"Rescue Feed
    Executed Today?"}
    F7["[P0] ANIMAL DIES (-$400/$500 capital + permanent loss)"]
    F8["[P1] Survival Disruption (P100 preempts other work)"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
    F6 -->|No| F7
    F6 -->|Yes| F8
```

---

### Chain 4: Shed Overflow & Placement Blockage (`FAIL-SHED-01`)

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

### Chain 5: Sticky Mission Deadlock & Worker Oscillation (`FAIL-EXEC-01`)

```mermaid
flowchart TD
    F1["[P1] FAIL-STICKY-01: Sticky Mission Target Occupied
    Worker assigned to tile blocked by another unit"]
    F2["[P1] Pathfinding bfs_first_step() Returns None / Oscillation"]
    F3["[P1] FAIL-CHURN-01: Unit Spends Turn PASSing or Moving in Place"]
    F4["[P2] Excessive Travel Share (>75% travel actions)"]
    F5["[P1] Routine Watering / Harvesting Backlog Grows"]
    F6["[P0] Crops Enter Survival State (consecutive_unwatered = 1)"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
```

---

### Chain 6: Under-Hiring vs Over-Hiring Disruption (`FAIL-HIRE-01`)

```mermaid
flowchart TD
    subgraph UNDER_HIRE["Under-Hiring Failure"]
        U1["[P1] Labor Shortage (<12 hands on 75 tiles)"]
        U2["Action Deficit: Cannot water 50 crops + care 18 animals"]
        U3["[P0] Crop Dehydration & Animal Production Misses"]
    end

    subgraph OVER_HIRE["Over-Hiring Failure"]
        O1["[P1] Over-Hiring (>12 hands)"]
        O2["Fibonacci Wage Explosion: Day 12 costs $376 -> Day 13 costs $610"]
        O3["[P1] Treasury Depletion: Starves Land & Seed Capital"]
    end

    U1 --> U2 --> U3
    O1 --> O2 --> O3
```

---

## 5. Market Trading & Pricing Failures

### Chain 7: Crop Self-Glut & Monoculture Price Collapse (`FAIL-MKT-02`)

```mermaid
flowchart TD
    F1["[P1] FAIL-GLUT-01: Incomplete Committed Crop Accounting
    Scorer evaluates only live tiles, ignoring planned today"]
    F2["[P1] Monoculture Over-Planting (e.g., 25 Melons)"]
    F3["[P1] Market Inventory Ingestion Exceeds 12,000"]
    F4["[P1] Quadratic Price Drop: Melon falls from $250 -> $1 floor"]
    F5["[P1] Floor Hold Freezes Shed Stock; Recovery Fails"]
    F6["[P0] Negative ROI on Seeds & Labor Sunk"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
```

---

### Chain 8: Bad Sell Timing & Dumping into Depressed Markets (`FAIL-MKT-03`)

```mermaid
flowchart TD
    F1["[P2] Selling on Non-Drain Hours (t % 4 != 1)"]
    F2["Realizes Pre-Drain Depressed Price Quotes"]
    F3["[P1] Selling Massive Batch Without Drip Slicing"]
    F4["Marginal Sale Units Crash Spot to $1 Floor"]
    F5["[P1] Realized Revenue Drops by 40%-60%"]

    F1 --> F2 --> F5
    F3 --> F4 --> F5
```

---

## 6. Opponent Modeling & State Leakage Failures

### Chain 9: State Leakage Across Match Episodes (`FAIL-STATE-01`)

```mermaid
flowchart TD
    F1["[P1] FAIL-LEAK-01: Episode Reset Detection Missed
    day=0 check fails because episode.last_day not cleared"]
    F2["[P1] Stale Opponent Sales & Shed Inventories Persist"]
    F3["[P2] Hallucinated Dump Predictions & Erroneous Delays"]
    F4["[P1] Unwarranted Preemptive Sells at Bad Market Hours"]

    F1 --> F2 --> F3 --> F4
```

---

## 7. System Exceptions & Fallback Activation

### Chain 10: Unhandled Exception in Strategic Pipeline (`FAIL-EXC-01`)

```mermaid
flowchart TD
    F1["[P0] Unhandled Bug in MacroPlanner or TaskScheduler"]
    F2["Try/Except Catches Crash in main._agent_decision()"]
    F3["[P1] _LAST_FALLBACK_DIAGNOSTIC Records Traceback"]
    F4["[P1] _survival_fallback_from_ctx() Activates"]
    F5["Only Survival Feeds & Emergency Waters Dispatched"]
    F6["Zero Market Orders Dispatched (Growth Paralyzed)"]
    F7{"Context Parsing
    Succeeds?"}
    F8["Maintain Basic Survival"]
    F9["[P0] _survival_fallback_raw() Activates (Blind Emergency)"]

    F1 --> F2 --> F3 --> F4 --> F5 --> F6
    F4 --> F7
    F7 -->|Yes| F8
    F7 -->|No| F9
```
