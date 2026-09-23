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

Feed failures in previous SW iterations (e.g. P1.1, P5.1-C) occurred because planners assumed unharvested grain could feed animals.

### Feed Timing Invariants
1. **Accessible Wheat**: Only wheat currently inside the shed (`shed["WHEAT"]`) or carried by workers (`inventories[u]["WHEAT"]`) is immediately accessible.
2. **Strict Causality**: Wheat growing in tile $(x, y)$ that matures on $(Day_{10}, Hour_0)$ CANNOT feed animals on Day 8 or Day 9.
3. **Daily Animal Demand**: Every live animal consumes exactly 1 wheat per day. Feeding must occur before Hour 23.
4. **Projected Feed Balance**:
   $$\text{Balance}(d) = \text{Opening}(d) + \text{HarvestInflow}(d) - \text{FeedDemand}(d)$$
   A farm is certified feed-safe only if $\forall d \in [d_{\text{curr}}, d_{\text{curr}} + H], \text{Balance}(d) \ge 0$.

---

## 4. Market Order Capacity Sub-Ledger

The game engine enforces an absolute cap of **10 market orders per turn**. Extra orders are silently dropped by the engine.

### Command-Specific Slot Consumption
| Market Operation | Command Syntax | Slots Consumed | Mechanics |
|---|---|:---:|---|
| **Hire Hand** | `["HIRE"]` | **1 per hand** | 10 hires completely consume an entire turn's market capacity. |
| **Buy Product** | `["BUY_PRODUCT", prod, qty]` | **1 per order** | Single order can buy multiple units up to cash/shed limits. |
| **Buy Land** | `["BUY_LAND"]` | **1 per quadrant** | Consumes 1 slot; settles after farm unit actions. |
| **Buy Animal** | `["BUY_ANIMAL", species, qty]` | **1 per order** | Consumes 1 slot. |
| **Sell Product** | `["SELL", prod, qty]` | **1 per order** | Consumes 1 slot; pulls goods from shed only. |

The ledger tracks reservations per turn `(day, hour)` and rejects any candidate action that would exceed 10 total slots or displace high-priority survival orders.

---

## 5. Storage Sub-Ledger: Sequential Execution Order

Storage overflow in Kaggriculture destroys high-value goods at end-of-day. The storage ledger models the sequential turn mechanics:
```text
Worker Harvest
      ↓
Worker Inventory (Carried)
      ↓
Explicit PLACE/DROP (if adjacent to shed)
      ↓
Market Sale (Pulls from shed only)
      ↓
Midnight Worker Auto-Drop (Teleports all carried goods into shed)
      ↓
Capacity Overflow Check (Units > 100 discarded by engine)
```

The ledger computes net available headroom:
$$\text{NetHeadroom} = \max(0, 100 - \text{ShedOccupancy} - \text{WorkerCarriedUnits})$$
Harvest waves exceeding headroom trigger urgent drip-sales or harvest delays to prevent midnight discards.
