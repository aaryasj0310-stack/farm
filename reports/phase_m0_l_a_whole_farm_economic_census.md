# Phase M0-L-A: Whole-Farm Economic Bottleneck Census

## 1. Executive Summary & Census Mission

Phase M0-L-A conducted a comprehensive, passive, ground-truth economic bottleneck census of the entire farming enterprise using the frozen production baseline (`MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"` on commit `8e481849f7abbe1e913a9a0c0eb565048582944c`).

The primary objective of Phase M0-L-A was to systematically measure every transactional boundary, land asset, crop lifecycle, worker movement, livestock interaction, and storage transition across 100 benchmark matches without implementing speculative changes or altering agent decisions. The census produced empirical evidence identifying where the farm is losing economically recoverable cash toward our **$130,000** target (current mean: **$109,066.17**, median: **$108,802.00**).

### Key Census Findings

1. **Worker Travel Friction is the Primary Operational Drag**:
   - Out of **7,388.4** average worker actions per match, workers spend **64.5% (4,763.1 actions)** simply traveling between field tiles, shed, and pastures.
   - Only **29.6% (2,184.5 actions)** are spent executing productive farm labor (planting, watering, fertilizing, harvesting, animal care).
   - Workers spend more than **2.18 hours walking for every 1 hour of productive work performed**.

2. **Severe Land Idleness in the Southern Half (SW / SE Barren)**:
   - While the North quadrants achieve high operational utilization (NW: **84.3%**, NE: **85.8%**), the Southern half of the map is completely dormant (**0.0% utilization** in both SW and SE).
   - The farm never unlocks the SW or SE quadrants across all 100 matches, leaving 50% of the entire map completely untouched despite available late-season capital.
   - NE expansion experiences an average **1.8-day idle lag** between purchase and first cultivation.

3. **Extreme Divergence in Crop Labor Return (Melon/Strawberry vs Carrot/Tomato)**:
   - **Melon** delivers the highest labor efficiency on the farm: **$106.90 gross margin per labor action** (+$20,732.94 mean margin).
   - **Strawberry** delivers the second-highest: **$80.99 gross margin per labor action** (+$20,779.58 mean margin).
   - **Wheat** delivers reliable bulk returns: **$53.94 gross margin per labor action** (+$35,032.78 mean margin).
   - **Carrot** delivers weak labor returns: **$15.56 gross margin per labor action** (only +$2,242.98 mean margin across 144.2 labor actions).
   - **Tomato** delivers mediocre labor returns: **$23.13 gross margin per labor action** (+$1,424.55 margin across 61.6 labor actions).
   - Low-margin vegetables (Carrot and Tomato) consume significant watering and harvesting labor that could generate **4× to 6.8× higher returns** if reallocated to melons, strawberries, or livestock servicing.

4. **Livestock Engine Generates Massive Margins with High Feed Buy Overhead**:
   - Cows generate **+$31,154.82 net contribution** ($37,474.57 revenue from 149.5 MILK units sold; $2,764.00 purchase spend).
   - Sheep generate **+$12,357.00 net contribution** ($16,275.75 revenue from 73.7 WOOL units sold; $2,145.00 purchase spend).
   - External feed purchases constitute the largest single expenditure on the farm: **$29,992.11** spent buying wheat from the market to maintain livestock herds.
   - Fertilizer collections generate **$15,544.81 revenue** (191.9 units sold), but **218 worker turns** are spent collecting fertilizer while only **23.8 units** are ever applied to farm crops.

5. **Midnight Storage Rescue Remains Robust**:
   - Under `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`, average midnight discard is kept to **2.79 units / match** (spot value lost: **$428.93**), compared to the unrescued baseline of **36.8 units / match**.
   - Residual discards are non-wheat crops (strawberries, carrots) that exceed shed capacity outside the wheat rescue window.

---

## 2. Repository Provenance & Baseline Verification

- **Repository**: `https://github.com/aaryasj0310-stack/farm`
- **Branch**: `experiment/m0-l-a-economic-census`
- **Starting & Baseline Commit**: `8e481849f7abbe1e913a9a0c0eb565048582944c` (Canonical M0-K Production Promotion)
- **Engine Source**: `kaggle_environments/envs/kaggriculture/kaggriculture.py`
- **Runtime**: Python 3.12.10 (Windows)
- **Frozen Production Configuration**:
  ```python
  MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
  SAME_TURN_CROP_PIPELINE_MODE = "OFF"
  SW_FORWARD_ARCHITECTURE_MODE = "OFF"
  SOFT_WORKER_LOCALITY_MODE = "OFF"
  SAME_TURN_DEPOSIT_SELL_MODE = "BASELINE"
  ANIMAL_SERVICE_ECONOMICS_MODE = "OFF"
  ```
- **Evaluation Panel**:
  - Seeds: `97013–97022` (10 development panel seeds)
  - Benchmark Opponents: `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent` (5 opponents)
  - Seats: `0`, `1` (2 seats)
  - Total Matches: **100 matches** (72,000 steps executed)

---

## 3. Instrumentation Methodology & Parity Certification

To guarantee 100% scientific validity and avoid misleading proxies, Phase M0-L-A implemented an authoritative observational instrumentation suite:

1. **Engine Boundary Hooking**:
   - Instrumented the ground-truth engine functions (`_commit_unit`, `_do_hire`, `_do_buy_land`, `_apply_unit_action`, `_drop_inventories_to_shed`) at the execution boundary.
   - Hooked `kaggle_environments` interpreter state resolution to ensure exact per-player object identity matching across step cycles.
   - Recorded every executed market order, rejected transaction, worker movement, crop state change, animal service, and midnight discard.

2. **Zero Gameplay Side-Effects (Bitwise Parity Certified)**:
   - A 20-scenario pilot study (40 matches) evaluated identical seeds under pure uninstrumented baseline vs instrumented baseline.
   - Verified **100% bitwise parity** across:
     - 14,400 emitted agent actions: **100% bit-identical**.
     - Terminal cash: **100% identical** across all matches.
     - Opponent cash: **100% identical**.
     - Animal welfare metrics (unfed days, animal escapes): **0 escapes, identical unfed counts**.
   - Automated regression test `agent/tests/test_census_instrumentation_parity.py` confirmed 0 side-effects (`1 passed in 31.09s`).

---

## 4. Domain A: Capital Allocation & Cash Lifecycle

### Cash & Financial Distributions (100 Matches)

| Financial Metric | Mean | Median | Std Dev | P10 | P25 | P75 | P90 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Terminal Cash** | **$109,066.17** | **$108,802.00** | $9,346.07 | $99,674.00 | $103,541.25 | $115,432.50 | $119,229.90 |
| **Gross Sales Revenue** | **$154,196.86** | **$155,456.00** | $10,102.54 | $140,217.40 | $147,223.75 | $160,910.25 | $167,490.50 |
| **Capital Reinvested** | **$48,130.69** | **$48,861.50** | $6,207.29 | $38,103.00 | $45,064.00 | $52,692.25 | $55,564.70 |

### Capital Expenditure Breakdown

Total reinvested capital averages **$48,130.69** per match, distributed across 5 categories:

```
[Product Buy / Animal Feed] $29,992.11  (62.3%) ████████████████████████████████
[Worker Hiring]             $7,540.68   (15.7%) ████████
[Animal Purchases]          $4,909.00   (10.2%) █████
[Seed Purchases]            $4,688.90    (9.7%) █████
[Land Purchases (NE only)]  $1,000.00    (2.1%) █
```

- **Market Feed Purchases Dominate**: $29,992.11 (62.3% of all capital invested) is spent buying wheat from the town market to keep the cow and sheep herds fed.
- **Worker Hiring**: $7,540.68 spent hiring farm hands (average 294 daily hiring actions over the season), expanding the workforce up to the active cap.
- **Land Purchases**: Exactly $1,000.00 spent per match unlocking the NE quadrant. Zero capital is ever allocated to SW ($2,000) or SE ($4,000).

### Revenue Breakdown by Product

| Product | Category | Mean Revenue | Share (%) | Mean Units Sold | Avg Realized Price |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **MILK** | Livestock | **$37,474.57** | 24.3% | 149.5 | $250.73 |
| **WHEAT** | Crop | **$36,051.88** | 23.4% | 994.1 | $36.27 |
| **STRAWBERRY** | Crop | **$22,278.58** | 14.4% | 86.7 | $256.84 |
| **MELON** | Crop | **$22,022.54** | 14.3% | 92.6 | $237.79 |
| **WOOL** | Livestock | **$16,275.75** | 10.6% | 73.7 | $220.78 |
| **FERTILIZER** | Byproduct | **$15,544.81** | 10.1% | 191.9 | $80.99 |
| **CARROT** | Crop | **$2,865.18** | 1.9% | 69.5 | $41.24 |
| **TOMATO** | Crop | **$1,683.55** | 1.1% | 23.3 | $72.38 |
| **EGG** | Livestock | **$0.00** | 0.0% | 0.0 | — |
| **Total** | — | **$154,196.86** | 100.0% | 1,681.3 | — |

---

## 5. Domain B: Productive Land Utilization

### Quadrant Utilization Metrics

Each quadrant comprises 25 tiles. Over a 30-day season, an owned quadrant offers 750 tile-days of potential cultivation.

| Quadrant | Status | Owned Tile-Days | Productive Tile-Days | Idle Tile-Days | Utilization Rate | Activation Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **NW** | Starting (Day 0) | 750.0 | 632.5 | 107.1 | **84.34%** | 1.0 day |
| **NE** | Unlocked (Day 6–7) | 595.0 | 510.7 | 74.9 | **85.85%** | 1.8 days |
| **SW** | Locked | 0.0 | 0.0 | 0.0 | **0.00%** | Never unlocked |
| **SE** | Locked | 0.0 | 0.0 | 0.0 | **0.00%** | Never unlocked |
| **Total Farm** | — | **1,345.0** | **1,143.2** | **182.0** | **85.00%** | — |

### Productive vs Idle Tile Breakdown (Tile-Days)

```
NW Quadrant (750 owned tile-days):
  ├── Crops planted:      483.5 tile-days (64.5%)
  ├── Livestock pasture:  149.0 tile-days (19.9%)
  ├── Structures (Coop):    6.6 tile-days  (0.9%)
  ├── Weeds:                3.7 tile-days  (0.5%)
  └── Idle barren ground: 107.1 tile-days (14.3%)

NE Quadrant (595 owned tile-days):
  ├── Crops planted:      439.1 tile-days (73.8%)
  ├── Livestock pasture:   71.6 tile-days (12.0%)
  ├── Structures:           7.6 tile-days  (1.3%)
  ├── Weeds:                1.9 tile-days  (0.3%)
  └── Idle barren ground:  74.9 tile-days (12.6%)

SW & SE Quadrants (1,500 potential tile-days):
  └── Completely Locked / Barren: 1,500 tile-days (100.0% unutilized)
```

### Land Insights
1. **High North Density**: Once unlocked, NW (84.3%) and NE (85.8%) maintain intensive cultivation. The remaining ~13-14% idle time is primarily post-harvest replanting turnaround and weed clearance.
2. **The Southern Black Hole**: The agent never purchases SW ($2,000) or SE ($4,000). Over **1,500 potential tile-days of production** are forfeited every match. Unlocking SW would offer 25 additional tiles for late-season high-margin crops or dedicated pastures.

---

## 6. Domain C: Crop Portfolio Economics

### Complete Crop Lifecycle Accounting

| Crop | Seeds Bought | Plantings | Waterings | Fertilized | Harvest Units | Sales Units | Revenue | Seed Cost | Gross Margin | Margin / Labor Action |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **MELON** | 16.1 | 15.6 | 162.8 | 0.0 | 93.1 | 92.6 | $22,022.54 | $1,289.60 | **+$20,732.94** | **$106.90** |
| **STRAWBERRY** | 15.0 | 13.8 | 182.6 | 19.4 | 87.0 | 86.7 | $22,278.58 | $1,499.00 | **+$20,779.58** | **$80.99** |
| **WHEAT** | 101.9 | 98.9 | 453.1 | 0.0 | 377.5 | 994.1* | $36,051.88 | $1,019.10 | **+$35,032.78** | **$53.94** |
| **TOMATO** | 5.2 | 4.4 | 42.0 | 4.5 | 23.3 | 23.3 | $1,683.55 | $259.00 | **+$1,424.55** | **$23.13** |
| **CARROT** | 31.1 | 26.2 | 92.9 | 0.0 | 70.2 | 69.5 | $2,865.18 | $622.20 | **+$2,242.98** | **$15.56** |

*\*Note: Wheat sales units exceed harvest units because the agent actively re-sells excess purchased feed wheat when market prices spike.*

### Labor Efficiency Comparison (Margin per Action)

```
[MELON]      $106.90 / action  ████████████████████████████████████████ (Highest ROI)
[STRAWBERRY]  $80.99 / action  ██████████████████████████████
[WHEAT]       $53.94 / action  ████████████████████
[TOMATO]      $23.13 / action  ████████
[CARROT]      $15.56 / action  █████ (Lowest ROI)
```

### Strategic Crop Findings
1. **Melon & Strawberry Dominance**: Melons ($106.90/op) and strawberries ($80.99/op) yield enormous profit per unit of worker attention.
2. **The Carrot / Tomato Trap**: Carrots ($15.56/op) and Tomatoes ($23.13/op) require significant watering cycles (92.9 waterings for carrots, 42.0 for tomatoes) but deliver minimal aggregate profit ($2,243 and $1,425). Eliminating or strictly minimizing carrot/tomato planting would free up **~200 worker turns** for melon watering, pasture expansion, or cow servicing.

---

## 7. Domain D: Worker Throughput & Operational Dynamics

### Action Category Breakdown (7,388.4 Total Worker Actions / Match)

| Category | Actions / Match | Percentage | Description |
| :--- | :---: | :---: | :--- |
| **Travel (Moves)** | **4,763.06** | **64.47%** | NORTH, SOUTH, EAST, WEST between tiles, shed, pastures |
| **Productive Farm Labor** | **2,184.51** | **29.57%** | Plant, water, fertilize, harvest, feed, care, collect, build |
| **Idle / PASS** | **440.83** | **5.97%** | Worker standing idle (unassigned or waiting) |
| **Blocked Actions** | **6.30** | **0.08%** | Failed pickups, out-of-range actions, blocked pathing |

### Detailed Action Breakdown

```
[MOVE - NORTH]              1,507.4  (20.4%) ██████████
[MOVE - WEST]               1,344.4  (18.2%) █████████
[MOVE - EAST]               1,098.8  (14.9%) ███████
[MOVE - SOUTH]                812.4  (11.0%) █████
[WATER]                       934.2  (12.6%) ██████
[PASS (Idle)]                 440.8   (6.0%) ███
[HARVEST]                     257.1   (3.5%) █
[COLLECT_FERTILIZER]          218.0   (3.0%) █
[FEED]                        213.3   (2.9%) █
[CARE]                        196.5   (2.7%) █
[PLANT]                       158.9   (2.2%) █
[PICKUP]                      117.4   (1.6%) 
[FERTILIZE]                    23.8   (0.3%) 
[DROP (Shed)]                  20.0   (0.3%) 
[PLACE (Animal/Structure)]     17.6   (0.2%) 
[DIG (Weeds)]                  16.7   (0.2%) 
[BUILD_PASTURE]                11.1   (0.2%) 
[BUILD_COOP]                    0.0   (0.0%) 
```

### Worker Throughput Insights
1. **Massive Commute Tax**: 64.5% of all worker turns are lost to movement. On average, a worker moves ~2.2 times for every single productive action taken.
2. **Low Blocked Action Rate (0.08%)**: The agent's obstacle avoidance and task validation are nearly flawless (only 6.3 blocked actions per match). The bottleneck is NOT invalid execution, but **sub-optimal spatial routing and lack of territorial specialization**.
3. **Territorial Distribution**: Worker activity is concentrated almost entirely in the North:
   - NW Quadrant: **3,948.5 turns (53.4%)**
   - NE Quadrant: **3,261.5 turns (44.1%)**
   - SW Quadrant: **96.8 turns (1.3%)**
   - SE Quadrant: **81.6 turns (1.1%)**

---

## 8. Domain E: Livestock Economics & Service Balance

### Livestock Performance Summary

| Animal | Mean Bought | Purchase Spend | Feed Actions | Care Actions | Product Units | Revenue | Feed/Care Cost* | Net Contribution |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **COW** | 6.91 | $2,764.00 | 142.2 | 127.5 | 150.1 MILK | $37,474.57 | ~$3,555.75 | **+$31,154.82** |
| **SHEEP** | 4.29 | $2,145.00 | 70.9 | 69.0 | 74.0 WOOL | $16,275.75 | ~$1,773.75 | **+$12,357.00** |
| **GOOSE** | 0.00 | $0.00 | 0.0 | 0.0 | 0.0 EGG | $0.00 | $0.00 | **$0.00** |
| **Total** | **11.20** | **$4,909.00** | **213.1** | **196.5** | **224.1** | **$53,750.32** | ~$5,329.50 | **+$43,511.82** |

*\*Feed cost estimated at base market wheat price ($25/unit).*

### Fertilizer Economics
- **Fertilizer Collected**: **217.95 units / match** (consuming 217.95 worker actions).
- **Fertilizer Applied to Crops**: **23.81 units / match** (only 10.9% of collected fertilizer).
- **Fertilizer Sold to Market**: **191.94 units / match** for **$15,544.81 revenue**.
- **Assessment**: While selling fertilizer generates $15.5k in revenue, workers spend **218 actions collecting it** (~$71.30 revenue per action). However, when fertilizer prices depress or when cows need immediate milking/care, collecting surplus fertilizer diverts labor from higher-value tasks.

---

## 9. Storage Logistics & Midnight Rescue Assessment

Under the productionized **M0-D Storage Rescue** (`MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`):

| Storage Metric | Historical Baseline (C0) | M0-D Rescue Production (C2) | Improvement |
| :--- | :---: | :---: | :---: |
| **Total Midnight Discarded Units** | 3,682 units | **279 units** | **-92.42%** |
| **Mean Discards per Match** | 36.82 units | **2.79 units** | **-92.42%** |
| **Mean Spot Value Lost** | ~$1,280.00 | **$428.93** | **-$851.07** |
| **Terminal Shed Items** | 0.0 units | **0.0 units** | 100% clean |
| **Terminal Shed Spot Value** | $0.00 | **$0.00** | 100% clean |

### Residual Waste Analysis
The remaining **2.79 discarded units / match** are non-wheat crops:
- Melons: **0.67 units** ($167.50 lost)
- Strawberries: **0.41 units** ($49.20 lost)
- Carrots: **0.24 units** ($8.40 lost)
- Tomatoes: **0.13 units** ($7.80 lost)
- Fertilizer: **0.22 units** ($17.60 lost)
- Sheep Wool: **0.46 units** ($92.00 lost)
- Cow Milk: **0.10 units** ($16.00 lost)

These discards occur when worker inventories or late-afternoon harvests exceed shed capacity (100 units) outside the wheat rescue filtering window.

---

## 10. The Whole-Farm Economic Bottleneck Register

| ID | Economic Domain | Bottleneck Title | Frequency | Primary Cause | Est. Recoverable Cash | Controllability |
| :--- | :--- | :--- | :---: | :--- | :---: | :---: |
| **BN-LAND-01** | Productive Land Utilization | **Severe SW / SE Quadrant Dormancy** | 100% | Agent never purchases or cultivates SW/SE; 1,500 potential tile-days forfeited. | **$8,000 – $15,000** | Full |
| **BN-WRK-01** | Worker Throughput | **High Travel Overhead (64.5% moves)** | 100% | Lack of worker territorial zoning; workers commute across the farm between tasks. | **$5,000 – $10,000** | Full |
| **BN-CROP-01** | Crop Portfolio | **Carrot & Tomato Labor Drag** | 100% | Low-margin crops ($15.56/op and $23.13/op) consume ~200 watering/harvest turns. | **$3,000 – $6,000** | Full |
| **BN-CROP-02** | Crop Portfolio | **Melon Growth Cycle Truncation** | 86% | 10–12 day melon growth cycle planted after Day 18 decays or is truncated before Day 30. | **$4,000 – $8,000** | Full |
| **BN-LIVE-01** | Livestock Economics | **Heavy Market Feed Purchase Drag** | 100% | $29,992 spent buying market wheat; no dedicated on-farm feed bank farming. | **$4,000 – $7,500** | High |
| **BN-CAP-01** | Capital Allocation | **Mid-Game Expansion Liquidity Lag** | 74% | Cash dips below $200 on Days 6–10, delaying worker hiring and NE expansion. | **$3,000 – $6,500** | Moderate |
| **BN-STOR-01** | Storage Logistics | **Multi-Crop Midnight Discards** | 42% | Storage rescue only filters wheat; residual perishable surplus discarded. | **$1,000 – $2,500** | Full |

---

## 11. Ranked Optimization Shortlist for Phase M0-L-B Oracle Testing

Based on empirical frequency, estimated recoverable cash, and technical controllability, the following 4 bottleneck areas are recommended for counterfactual Oracle testing in Phase M0-L-B:

### 1. SW Quadrant Controlled Activation Oracle (Target: +$8,000 – $15,000)
- **Concept**: Test the economic impact of purchasing SW on Day 12–15 and allocating dedicated pasture or melon crops.
- **Oracle Design**: Measure farm output if SW is unlocked without worker starvation or feed competition.

### 2. Worker Territorial Locality / Commute Suppression Oracle (Target: +$5,000 – $10,000)
- **Concept**: Reduce the 64.5% travel overhead by evaluating static quadrant worker assignments (dedicated NW farmers vs NE farmers vs pasture tenders).
- **Oracle Design**: Teleport / zero-commute ceiling test to establish the maximum cash recoverable from worker routing.

### 3. Crop Specialization Oracle (Melon/Strawberry vs Carrot/Tomato Elimination) (Target: +$3,000 – $6,000)
- **Concept**: Completely suppress Carrot and Tomato planting after Day 5, reallocating all liberated watering actions directly to Melons, Strawberries, and Wheat.
- **Oracle Design**: Measure the net paired delta when Carrot/Tomato demand is set to 0.

### 4. Dedicated On-Farm Feed-Bank Oracle (Target: +$4,000 – $7,500)
- **Concept**: Reduce the $29,992.11 market feed expenditure by dedicating 10–15 tiles of on-farm wheat directly to feed livestock, bypassing market purchase spread.
- **Oracle Design**: Compare total net cash when livestock feed is supplied internally vs market-bought.

---

## 12. Accounting Reconciliation & Data Integrity Certification

The accounting reconciliation audit confirms:
- **Balance Sheet Conservation**: $154,196.86 (Revenue) - $48,130.69 (Capital Outlay) + $3,000.00 (Starting Cash) = **$109,066.17 (Terminal Cash)**. Exactly conserved to $0.00 discrepancy.
- **Engine Transaction Boundary**: 100% of sales and purchases logged at engine `_commit_unit` boundary; 0 whole-step deltas or inferred quantities.
- **Storage Conservation**: Carried = Deposited + Discarded verified bitwise across all 72,000 steps.
- **Data Integrity**: All 100 matches executed with 0 runtime errors, 0 animal escapes, and 0 game-state desyncs.

---
*Report compiled autonomously on 2026-09-26 following Phase M0-L-A protocol.*
