# SW Resource Ledger Specification

**Module:** `strategy/resource_ledger.py`  
**Status:** Implemented & Verified in Phase A  

---

## 1. Principles & Purpose

The `ResourceLedger` is the single authoritative accounting ledger for all shared resources across future turns of an episode. It replaces fragmented, single-turn capacity heuristics with a multi-resource commitment system.

Core resources tracked:
1. **Liquid Cash & Dated Liabilities**
2. **Accessible Feed & Strict Harvest Causality**
3. **Market Order Capacity (10 Encoded Commands)**
4. **Storage & Sequential Execution Mechanics**

---

## 2. Cash Sub-Ledger: Confidence Classes & Solvency Rules

To prevent speculative future revenue from funding immediate irreversible commitments, future inflows are classified into three confidence tiers:

```python
class InflowConfidence(str, Enum):
    HARD = "HARD"                  # Mechanically settled cash in farm wallet
    CONSERVATIVE = "CONSERVATIVE"  # Physically harvested inventory in shed/carriers at floor/drip price
    SPECULATIVE = "SPECULATIVE"    # In-ground crops, unlaid eggs, uncollected wool, future model projections
```

### Solvency & Reservation Invariants
1. **Hard Commitments**: Mandatory daily wages (Fibonacci hire schedule), mandatory daily livestock feed, and committed land purchases are classified as `is_hard = True`.
2. **Speculative Exclusion**: Hard commitments **CANNOT** depend on `SPECULATIVE` inflows. They must be guaranteed by `HARD` cash or `CONSERVATIVE` physically existing inventory.
3. **Forward Checkpoint Feasibility (Zero Double-Reservation)**:
   When reserving liquidity for $(Day_t, Hour_h)$, the ledger tests net cash at all future liability checkpoints $\mathcal{C} = \{(d, h) \in \text{liabilities}\}$:
   $$\forall (d, h) \in \mathcal{C}, \quad \text{CashOnHand} - \text{SafetyReserve} + \sum_{\tau \le (d, h)} \text{Inflows}_\tau - \sum_{\tau \le (d, h)} \text{Liabilities}_\tau \ge 0$$
   If any checkpoint drops below zero, the reservation is rejected. This guarantees that capital allocated for SW land on Day 8 cannot be simultaneously spent on Day 7 livestock.

---

## 3. Feed Sub-Ledger: Accessibility & Strict Harvest Causality

Feed failures in previous SW iterations (e.g. P1.1, P5.1-C) occurred because planners assumed unharvested grain could feed animals. In Phase A-R, this sub-ledger was hardened with engine-exact physical models:

### Feed Timing Invariants & Authoritative State Tracking
1. **Authoritative Crop Age**: Replaced bug-prone `getattr(t, "age", 0)` with the engine's authoritative helper `crop_age(t, self.day)` and `t.planted_day`.
2. **Accessible vs Mature Wheat**:
   - `get_projected_mature_wheat(day)`: Sum of expected yield from all in-ground wheat reaching full maturity (`max_yield_day = planted_day + 4`) on `day`.
   - `get_projected_accessible_wheat(day, hour)`: Strict physical accessibility. Future wheat maturing on $day' > day$ provides 0 accessible units today. Same-day wheat counts only if physically harvestable (`day >= planted_day + 2`) and reachable before the hour deadline.
3. **Same-Day Physical Harvest-to-Feed Feasibility**:
   `evaluate_same_day_harvest_feed_feasibility(wheat_harvest, animal_pos, current_hour, worker_id)` verifies the physical action chain:
   $$\text{Worker Pos} \xrightarrow{\text{move}} \text{Wheat Tile} \xrightarrow{\text{HARVEST (1)}} \text{Animal Tile} \xrightarrow{\text{FEED (1)}} \le 23$$
   If this physical chain cannot complete before Hour 23, the wheat is rejected as a feed source for that day.
4. **Projected Feed Balance**:
   $$\text{Balance}(d) = \text{Opening}(d) + \text{HarvestInflow}(d) - \text{FeedDemand}(d)$$
   A farm is certified feed-safe only if $\forall d \in [d_{\text{curr}}, d_{\text{curr}} + H], \text{Balance}(d) \ge 0$.

---

## 4. Market Order Capacity Sub-Ledger

The game engine enforces an absolute cap of **10 market orders per turn** (shared across all operations). Extra orders are silently dropped by the engine.

### Command-Specific Slot Consumption
| Market Operation | Command Syntax | Slots Consumed | Mechanics |
|---|---|:---:|---|
| **Hire Hand** | `["HIRE"]` | **1 per hand** | 10 hires completely consume an entire turn's market capacity. |
| **Buy Product** | `["BUY_PRODUCT", prod, qty]` | **1 per order** | Single order can buy multiple units up to cash/shed limits. |
| **Buy Land** | `["BUY_LAND"]` | **1 per quadrant** | Consumes 1 slot; settles after farm unit actions. |
| **Buy Animal** | `["BUY_ANIMAL", species, qty]` | **1 per order** | Consumes 1 slot. |
| **Sell Product** | `["SELL", prod, qty]` | **1 per order** | Consumes 1 slot; pulls goods from shed only (cannot sell from backpacks). |

The ledger tracks reservations per turn `(day, hour)` and rejects any candidate action that would exceed 10 total slots or displace high-priority survival orders.

---

## 5. Storage Sub-Ledger: Intraday Timeline & Backpack Separation

Storage overflow in Kaggriculture destroys high-value goods at end-of-day. The Phase A-R storage ledger explicitly models the engine's intraday turn timeline and separates shed storage from worker backpacks:

### Sequential Intraday Timeline
```text
Turn 00-22: Worker Harvest -> Carried in Backpack
      ↓
Worker Movement toward Shed -> Explicit PLACE/DROP (if adjacent to shed)
      ↓
Market Phase: SELL orders executed (pulls strictly from shed, NOT backpacks)
      ↓
Hour 23 End-of-Day: Midnight Auto-Drop (Engine teleports ALL carried goods into shed)
      ↓
Midnight Capacity Check: Any inventory exceeding Shed Capacity (100) is DISCARDED
```

### Worker-Level Storage Tracking (`WorkerStorageState`)
- Tracks each worker's `(x, y)` coordinate, carried items, and Manhattan distance to shed access tiles `(3, 4), (4, 3), (4, 5), (5, 4)`.
- Distinguishes between goods that can be deposited in time for market sales vs goods that will remain trapped in backpacks until midnight auto-drop.
- Computes net available headroom:
  $$\text{NetHeadroom} = \max(0, 100 - \text{ShedOccupancy} - \text{WorkerCarriedUnits})$$
- Projected multi-day storage timeline (`project_storage_timeline`) flags storage congestion and midnight overflow risk in advance, triggering pre-emptive drip selling.
