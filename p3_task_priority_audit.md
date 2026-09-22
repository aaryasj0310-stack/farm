# Kaggriculture P3.5 — Scheduler Task-Priority Conflicts Audit

## 1. Executive Summary
This document audits the task-priority ranking system in `agent/execution/task_scheduler.py` and `agent/config.py`. It details where static priority bands create severe **economic inversions**—specifically where low-margin routine tasks preempt high-value, time-critical tasks—and calculates the exact dollar losses caused by each conflict.

---

## 2. The Current Scheduler Priority Map

| Priority Band | Numeric Value | Task Class | Economic Value / Unit | Execution Deadline | Dynamics |
| :--- | :---: | :--- | :---: | :---: | :--- |
| **Urgent Survival** | **100** | Plant water (consec unwatered=1) | $60–$1,000 (Prevents death) | Hour 23 EOD | Dynamic (escalates on danger) |
| **Decay Harvest** | **90** | Harvest overripe one-time crop | $25–$250 | Immediate | Dynamic (only triggers *after* decay starts!) |
| **Delivery Pressure**| **88** | Product deposit (held inv full) | Unblocks inventory | Hour 23 | Dynamic |
| **Feed Staging** | **86** | Pick up wheat from shed | Enables feeding | Hour 18 | Static |
| **Production Feed** | **85** | Feed livestock on prod day | $50–$200 + care bank | Hour 23 EOD | Static / Escalating |
| **Place Animal** | **84** | Place newly purchased animal | Lifetime yield | Hour 23 | Static |
| **Build Structure** | **78** | Build planned pasture/coop | Unblocks animal | Hour 23 | Static |
| **Fertilizer Collect**| **75** | Collect fertilizer from animal | $100 | Hour 23 EOD | Static |
| **Plant & Water** | **75** | Plant seed on empty tile | Full crop lifetime | Hour 12 preferred | Static |
| **Bonus Water** | **70** | Water crop in bonus window | +$25–$60 (+1 unit yield) | Hour 23 EOD | Static |
| **Product Delivery** | **68** | Deposit animal/crop goods | Unlocks cash/shed | Hour 23 | Static |
| **Care Animal** | **65** | Care for cow/sheep/goose | **+$50–$160 (care multiplier)**| Hour 23 EOD | Static |
| **Standard Harvest** | **65** | Harvest ripe mature crop | **$100–$250 (Full crop value)**| **Max Yield Day** | **Static (CRITICAL FLAW)** |
| **Fertilize Crop** | **60** | Apply fertilizer to plant | +$50–$120 | Hour 23 | Static |
| **Weed Dig** | **20** | Dig weed or fallow obstacle | Fallow tile cleanup | Flexible | Static |

---

## 3. The Three Major Priority Conflicts & Measured Losses

### Conflict 1: Standard Harvest (65) vs. Bonus Water (70) & Fert Collect (75)
- **The Defect**: When a crop reaches maturity (e.g. Wheat on Day 4 with 6 units = $150, or ripe Strawberry with 2 units = $120), its harvest task is assigned priority **65**.
  - `PRIORITY_BONUS_WATER` is **70** (marginal value: +1 unit of Wheat = $25).
  - `PRIORITY_FERT_COLLECT` is **75** ($100 value, can be collected anytime before midnight).
  - `PRIORITY_PLANT_AND_WATER` is **75**.
- **The Failure**: Workers choose to water young crops or collect fertilizer while ripe mature crops sit in the field. When the turn runs out at hour 23, the ripe crop enters Day 5 without being harvested and **decays** by 1 unit.
- **The Delay Trap**: The crop only escalates to `PRIORITY_DECAY_HARVEST = 90` *after* it has already suffered its first decay tick!
- **Direct Measured Loss**: **$6,031.80/game in crop decay** + delayed tile re-use.

### Conflict 2: Animal Care (65) vs. Bonus Water (70)
- **The Defect**: Animal care banks +1 yield multiplier for the animal's next harvest:
  - Caring a Cow produces +1 Milk = **$160.00**.
  - Caring a Sheep produces +1 Wool = **$200.00**.
  - Caring a Goose produces +1 Egg = **$50.00**.
- **The Failure**: `PRIORITY_CARE_ANIMAL` is hardcoded to **65**, sitting below `PRIORITY_BONUS_WATER = 70` (+1 unit wheat = $25). On busy days, workers water wheat beds while cows and sheep miss daily care.
- **Direct Measured Loss**: **$3,926.00/game in lost care yield multipliers**.

### Conflict 3: Fertilizer Collection (75) Preempting Urgent Daily Tasks
- **The Defect**: `COLLECT_FERTILIZER` is set to priority **75**, higher than bonus watering (70), animal care (65), and standard harvesting (65).
- **The Failure**: Fertilizer can be picked up at any hour of the day without penalty as long as it is done before midnight. Prioritizing fertilizer collection in the morning hours (Hours 4–10) pulls workers away from the morning watering sweep and delays crop harvesting.
- **Direct Measured Loss**: Contributes heavily to the **$9,630.95/game in missed watering bonuses**.

---

## 4. Summary of Priority Conflict Losses

| Priority Conflict | Inversion Mechanism | Directly Measured Loss / Game |
| :--- | :--- | :---: |
| **Standard Harvest (65) vs Water (70) / Fert (75)** | Ripe crops left to decay while young crops watered | **$6,031.80** |
| **Animal Care (65) vs Bonus Water (70)** | High-value milk/wool care sacrificed for low-value wheat water | **$3,926.00** |
| **Fertilizer Collect (75) vs Morning Care/Harvest** | Early fert collection displaces morning watering sweep | **~$2,500.00** (subset of water loss) |
| **Combined Measured Priority Inversion Loss** | — | **$12,457.80/game** |
