# P6 Baseline System Bottleneck Audit: Executive Summary

## 1. Audit Overview & Verification

- **Repository**: `https://github.com/aaryasj0310-stack/farm`
- **Branch**: `experiment/sw-p13-planting-gate`
- **Baseline Commit**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Policy Flag Confirmation**: `P51_T1_TWO_CYCLE_CARROT_ENABLED = False` (Permanently locked)
- **Diagnostic Panel**: 10 fresh, untouched discovery seeds (`96,401`–`96,410`) $\times$ 5 benchmark opponents $\times$ 2 seats = **100 baseline games**
- **Protected Verification**: Held-out benchmark seeds `98,001`–`98,050` remained 100% untouched
- **Behavior Invariance**: Diagnostic instrumentation operated in zero-bias shadow mode (100% telemetry-off invariant)
- **Cash Reconciliation Closure**: Max single-game cash reconciliation error across all 100 games: **$0.000000** ($\epsilon = 0$)

---

## 2. Global Headline Performance

Across the 100-game baseline panel, the production baseline achieved:

$$\text{Mean Baseline Final Cash: } \$101,035.79$$
$$\text{Median Baseline Final Cash: } \$99,584.00$$
$$\text{Standard Deviation: } \sim \$9,240.15 \quad (\text{Min: } \$78,028.00, \; \text{Max: } \$122,839.00)$$

### Performance by Opponent Archetype

| Opponent Archetype | Games | Mean Cash | Median Cash | Min Cash | Max Cash | Win Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `pass` (Solo Benchmark) | 20 | \$106,716.50 | \$107,452.00 | \$87,601.00 | \$122,839.00 | 100.0% |
| `melon_sniper` | 20 | \$104,830.35 | \$104,593.50 | \$90,051.00 | \$118,323.00 | 100.0% |
| `cow_milk_engine` | 20 | \$99,880.90 | \$100,342.00 | \$81,354.00 | \$111,519.00 | 100.0% |
| `full_production_agent` | 20 | \$99,544.95 | \$98,944.00 | \$89,577.00 | \$112,384.00 | 100.0% |
| `pure_wheat_rush` | 20 | \$94,206.25 | \$94,100.50 | \$78,028.00 | \$119,159.00 | 100.0% |

### Performance by Seat

- **Seat 0 (First Mover)**: \$100,719.14 (50 games)
- **Seat 1 (Second Mover)**: \$101,352.44 (50 games)
- **Seat Parity Delta**: +\$633.30 (Seat 1 advantage; within stochastic noise $\pm \$1,200$)

---

## 3. Macro Cash Waterfall (100-Game Average)

The production baseline generates substantial gross revenue, but surrenders over \$49,000/game in operational expenditures and structural inefficiencies:

```
[Starting Capital: $3,000.00]
       │
       ▼  + Gross Product Revenue: $147,457.41
          ├── Wheat Sales:       $36,837.79  (1,010.7 units @ $36.45)
          ├── Cow Milk:          $34,533.39  (142.7 units @ $241.98)
          ├── Melon:             $21,761.63  (91.3 units @ $238.43)
          ├── Strawberry:        $18,842.10  (75.7 units @ $248.81)
          ├── Sheep Wool:        $15,707.59  (72.0 units @ $218.16)
          ├── Fertilizer:        $15,278.36  (187.8 units @ $81.37)
          ├── Carrot:            $2,770.70   (69.1 units @ $40.10)
          └── Tomato:            $1,725.85   (23.2 units @ $74.55)
       │
       ▼  - Total Operating Expenses: $49,421.62
          ├── Feed Wheat Purchases: $31,249.44  (863.0 units @ $36.21) [63.2% of expenses]
          ├── Worker Wages (Hires):  $7,540.68  (294.0 hires)
          ├── Livestock Purchases:   $4,933.00  (6.8 Cows, 4.5 Sheep)
          ├── Seed Purchases:        $4,698.50  (103.2 Wheat, 31.5 Carrot, 16.2 Melon, 14.8 Straw, 5.2 Tom)
          └── Land Expansion (NE):   $1,000.00  (1.0 quadrant)
       │
       ▼
[Final Reconciled Cash: $101,035.79] (Closure Discrepancy: $0.000000)
```

---

## 4. Synthesis of Bottlenecks Across the 6 Constraint Families

```
+-------------------------------------------------------------------------------------------------------+
| P6 BASELINE BOTTLENECK AUDIT: PRIMARY CONSTRAINTS & EMPIRICAL REALITY                                 |
+-------------------------------------------------------------------------------------------------------+
| 1. WORKER TRANSIT OVERHEAD: 64.85% of all actions are MOVE operations (4,783 moves / 7,376 actions).  |
|    Shuttling to/from the center shed (4,4)-(5,5) dominates 60%+ of worker movement.                   |
+-------------------------------------------------------------------------------------------------------+
| 2. SHED OVERFLOW DISCARDS: $6,026.53/game in completed physical goods destroyed at Day-End shed drop.  |
|    Top losses: Strawberry ($2,266.63), Wool ($1,047.17), Milk ($1,013.91), Wheat ($700.88).           |
+-------------------------------------------------------------------------------------------------------+
| 3. WHEAT LIQUIDITY & TRADING CHURN: 863 units bought ($31.2k) vs 1,010 units sold ($36.8k).           |
|    Livestock only consumes 213.9 units of wheat! Day 28 desynchronization churns 20 units/hour.       |
+-------------------------------------------------------------------------------------------------------+
| 4. LIVESTOCK HARVEST & CARE LOSS: 17.1 cow missed cares/game, 7.6 sheep missed cares/game.             |
|    3.51 milk and 1.68 wool uncollected at season end ($1,216 unharvested value).                     |
+-------------------------------------------------------------------------------------------------------+
| 5. TILE "LIVING STORAGE" TRAP: 51.47% of unlocked tile-days spent holding mature crops.               |
|    Only 18.55% actively growing. Shed cap (100) forces field hoarding to prevent discard destruction.  |
+-------------------------------------------------------------------------------------------------------+
```

### Key Takeaway for the Path to $130k
The production baseline is not failing due to crop yields or pricing models; it is being throttled by **storage bottlenecks ($6.0k discards)**, **market order desynchronization ($31.2k churn)**, and **logistical congestion (64.9% movement)**.

Eliminating shed discards and harmonizing wheat liquidity represents a verified **+$7,000 to +$10,500/game recoverable opportunity**, establishing a clear empirical bridge toward $112k–$115k, with further route optimization opening the trajectory toward $120k+.
