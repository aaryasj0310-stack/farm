# P6 Tile Utilization & Spatial Serviceability Audit

## 1. Executive Summary & Epistemic Verdict

Land is the fixed capital foundation of farming. In the baseline system:
$$\text{Unlocked Tile-Days / Game} = 1,320.0 \text{ tile-days}$$
(NW starter quad: $25 \text{ tiles} \times 30 \text{ days} = 750 \text{ tile-days}$, plus NE expansion quad unlocked around Day 7–8: $\sim 570 \text{ tile-days}$).

```
                     TILE-DAYS BREAKDOWN (1,320 TOTAL)
   ┌───────────────────────┬──────────────────────────┬───────────┬──────────┐
   │ Mature Waiting Harvest│  Productively Growing    │ Pastures  │  Empty   │
   │  679.46 tile-days     │    244.87 tile-days      │ 221.23 td │ 154.51 td│
   │      (51.47%)         │        (18.55%)          │ (16.76%)  │ (11.71%) │
   └───────────────────────┴──────────────────────────┴───────────┴──────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> More than half of all unlocked tile-days (**51.47%**, 679.46 tile-days) are occupied by **mature crops sitting unharvested in the ground**.
> Actively growing crops occupy only **18.55%** of available land, while **11.71%** sits completely empty and unplanted.

---

## 2. Spatial Allocation of Farm Land

| Land State | Tile-Days / Game | % of Unlocked Land | Primary Mechanism |
| :--- | :---: | :---: | :--- |
| **Mature Waiting Harvest** | 679.46 | **51.47%** | Crops reach maturity (yield > 0) but remain unharvested for multiple days ("Living Storage"). |
| **Productively Planted** | 244.87 | **18.55%** | Active crop growth (seeds, vegetative stages prior to maturity). |
| **Livestock Pastures** | 221.23 | **16.76%** | Fenced pasture enclosures housing Cows (6.73) and Sheep (4.45). |
| **Empty Available (Fallow)** | 154.51 | **11.71%** | Tilled or untilled land with zero structures and zero crops. |
| **TOTAL UNLOCKED** | **1,320.00** | **100.0%** | Full seasonal land inventory. |

---

## 3. The "Living Storage" Paradox: Strategic Asset or Capacity Trap?

### Why Are Crops Held for 679 Tile-Days?
Holding mature crops in the soil is an emergent heuristic developed to bypass the **100-unit shed capacity limit**:
1. **Zero Storage Cost**: Crops in the field consume 0 units of shed space.
2. **Decay Immunity**: In Kaggriculture, mature crops do not begin decaying immediately; they have a decay buffer (`max_lifespan_step`) during which they can safely stand.
3. **Price Arbitrage**: Waiting for high-price town shop demand windows.

### Why It Became a Systemic Bottleneck
While rationally motivated, this heuristic has metastasized into a severe land-use pathology:
- **Tile Hijacking**: Holding a mature melon for 8 days blocks the coordinate from planting a new rotation.
- **Logistical Paralysis**: When a high-price window opens, workers cannot harvest 20 mature plants in a single hour without blowing through the shed limit and causing discards.
- **False Scarcity**: The agent refuses to plant because all tiles appear "occupied", while in reality over 50% of the farm is simply serving as an outdoor warehouse!

---

## 4. Unserviceable Fallow Land & Distance Friction

The **154.51 empty tile-days (11.71%)** are not uniformly distributed; they are concentrated in the outer perimeter of the NE quadrant:

```
        Outer NE Fallow Fringe (x = 8, 9; y = 0, 1, 2)
  ┌────────────────────────────────────────────────────────┐
  │  Manhattan distance to Shed Access (4,4)-(5,5):        │
  │  d = |9 - 5| + |0 - 4| = 8 steps                       │
  │  Round-trip travel time: 16 hours                      │
  │  Net work capacity per 24h day: 8 hours                │
  └────────────────────────────────────────────────────────┘
```

Because walking to the far northeastern corner costs **16 worker-hours round-trip**, the macro-planner frequently rejects planting on these tiles as mathematically unserviceable.
Buying the NE quadrant unlocks 25 physical tiles, but the outer 8–10 tiles effectively function as dead land due to transit decay.

---

## 5. Recoverable Value & Operational Verdict

| Land Efficiency Metric | Current Baseline State | Theoretical Max Opportunity | Inferred Recoverable Value | Epistemic Classification |
| :--- | :---: | :---: | :---: | :---: |
| **Mature Waiting Tile Turnover** | 679.5 tile-days (51.5%) | $12,000.00 (doubling crop cycles) | **$1,500.00 – $2,500.00** | `NOT A REAL OPPORTUNITY` (if attempted without shed expansion; causes discards) / `INFERRED RECOVERABLE` with synchronized selling |
| **Outer Fringe Tile Activation** | 154.5 fallow tile-days | $3,500.00 | **$500.00 – $1,000.00** | `INFERRED RECOVERABLE VALUE` (via localized worker assignment) |
| **Total Land Opportunity** | — | **$15,500.00** | **$2,000.00 – $3,500.00** | — |

> [!WARNING]
> **P5.1 Cautionary Reminder**:
> Attempting to "force" higher tile turnover by mandating instant replanting (as P5.1 did with carrots) without solving shed clearance directly causes wheat cannibalization and systemic collapse. Land turnover can ONLY be accelerated if shed liquidation throughput is increased first!
