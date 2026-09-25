# Phase M0-F: Adaptive Animal CARE & Feed-Bank Economics Report

**Author**: Antigravity Pair Programming  
**Branch**: `experiment/sw-forward-architecture-phase-a`  
**Phase Date**: September 25, 2026  
**Status**: COMPLETED — EMPIRICAL REJECTION (DEFAULT STAYS OFF)

---

## Executive Summary

Phase M0-F investigated the hypothesis that the agent's historical livestock servicing scheduler was wasting significant worker actions and wheat inventory by daily feeding and caring for livestock without regard to production intervals, pending care-bank limits, `max_held` capacity clipping, and endgame boundaries.

Through microtests on the official Kaggle game engine, an authoritative 50-match baseline audit, and a 200-match controlled discovery experiment (100 paired configurations across 10 discovery seeds, 5 benchmark opponents, and 2 seats), we evaluated the economic and gameplay consequences of skipping redundant livestock services.

### Core Empirical Findings:
1. **Engine Microtests (PASSED 6/6)**: Proved the engine's strict coupling: CARE only increments `pending_care_bonus` if the animal was **both cared AND fed** on that day (`if tile["cared_today"] and tile["fed_today"]`). On production days, `pending_care_bonus` is immediately cashed into yield before the day's care action is banked, and being unfed on a production day completely zeroes out the accumulated care bonus without granting it.
2. **Zero Escapes Maintained (100% Safety)**: Across all 200 matches in the controlled discovery experiment, 0 animals escaped. The survival constraint (`consecutive_unfed >= 1` triggers unconditional emergency feeding) functioned flawlessly.
3. **Controlled Experiment Result (REJECTED)**:
   - **Control (OFF)** Mean Cash: **\$104,009.28**
   - **Treatment (LIVE)** Mean Cash: **\$102,039.84**
   - **Paired Mean Delta**: **-\$1,969.44** (95% CI: [-\$3,773.59, -\$165.29], t = -2.166, p = 0.033)
   - **Median Delta**: **-\$3,015.50**
   - **Win Rate**: **39.0%** (39 Wins, 0 Ties, 61 Losses)
   - **Seed Cluster Breakdown**: 3 positive / 7 negative
4. **Primary Failure Mechanism (False Economy of Feed/Care Skipping)**:
   Saving 1 unit of wheat (~$40 market value) on an off-production day prevented the cow or sheep from banking a care bonus on that day. Over a 2-day or 3-day production cycle, this forfeited high-value livestock products (milk @ ~$140/unit, wool @ ~$200/unit). Worker actions reallocated towards crop harvesting (+1.65 harvests/match) yielded far lower marginal revenue than the forfeited animal products.
5. **Advancement Decision**: Per advancement criteria, **Phase M0-F is REJECTED**. `ANIMAL_SERVICE_ECONOMICS_MODE` remains `"OFF"` by default. It must NOT be combined with M0-D Storage Rescue.

---

## Part 1: Engine Mechanics Ground Truth

Through real-engine instrumentation in `scripts/verify_animal_care_bank.py`, we confirmed the following ground-truth behaviors from `kaggle_environments/envs/kaggriculture/kaggriculture.py`:

```python
# Daily animal refresh at hour == 23:
if not tile["fed_today"]:
    tile["consecutive_unfed"] = tile.get("consecutive_unfed", 0) + 1
else:
    tile["consecutive_unfed"] = 0

# 1. Animal Escape condition:
if tile["consecutive_unfed"] >= 2:
    # Animal escapes, tile reverts to bare PASTURE or COOP!

# 2. Production Condition:
days_since_first = next_day - placed_day - a["first_yield_day"]
if days_since_first >= 0 and days_since_first % a["interval"] == 0:
    bonus = tile.pop("pending_care_bonus", 0) if tile["fed_today"] else 0
    tile["yield_units"] = min(a["max_held"], tile["yield_units"] + base + bonus)
    tile["pending_care_bonus"] = 0

# 3. Care Banking Condition:
if tile["cared_today"] and tile["fed_today"]:
    tile["pending_care_bonus"] = tile.get("pending_care_bonus", 0) + 1
```

### Critical Rules Discovered:
- **Coupled Care & Feed**: CARE only accrues if the animal is **also fed** on the same day. Skipping FEED on off-production days forfeits the ability to bank care for that day!
- **Unfed Production Disaster**: If an animal is unfed on its production day, `bonus = tile.pop(...) if tile["fed_today"] else 0` completely wipes `pending_care_bonus` to 0 without granting it, leaving only the base yield.
- **Production Day Ordering**: On production day, old `pending_care_bonus` is converted to yield, cleared to 0, and then any care performed on that day is banked into the new cycle.

---

## Part 2: Baseline Servicing Audit (Seeds 96501–96510, 50 Matches)

We audited 50 matches running historical baseline (`SHADOW` mode):
- Total FEED actions emitted: 10,737 (214.7/match)
- Total CARE actions emitted: 9,752 (195.0/match)
- Mean Final Cash: \$100,289.04
- Species Servicing:
  - COW: 6,913 FEED, 6,588 CARE
  - SHEEP: 4,150 FEED, 3,917 CARE
  - GOOSE: 0 (not placed in competitive strategy)
- Identified Theoretical Opportunities:
  - Potentially redundant CARE actions: 2,550 (26.1%)
  - Potentially safe FEED savings: 1,664 wheat (15.5%)

---

## Part 3: Controlled Discovery Experiment Results

- **Sample Size**: 100 paired configurations (200 matches)
- **Seeds**: 97013–97022 (10 Discovery Seeds)
- **Opponents**: `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`
- **Seats**: 0 and 1 (symmetric pairing)

### Aggregate Statistics

| Metric | Control (OFF) | Treatment (LIVE) | Paired Delta |
| :--- | :--- | :--- | :--- |
| **Mean Final Cash** | **\$104,009.28** | **\$102,039.84** | **-\$1,969.44** |
| **Median Final Cash** | \$105,420.00 | \$102,112.50 | **-\$3,015.50** |
| **Standard Deviation** | — | — | \$9,093.51 |
| **Standard Error (SEM)** | — | — | \$909.35 |
| **t-statistic** | — | — | **-2.166** (p = 0.0327) |
| **95% Confidence Interval** | — | — | **[-\$3,773.59, -\$165.29]** |
| **Seed-Clustered 95% CI** | — | — | **[-\$3,986.88, +\$48.00]** |
| **Win / Tie / Loss** | — | — | **39 / 0 / 61 (39.0% Win Rate)** |

### Opponent Breakdown

| Opponent | Matches (Pairs) | Mean Delta | Std Delta | Win / Loss |
| :--- | :--- | :--- | :--- | :--- |
| `pass` | 20 | -\$4,077.25 | \$9,935.83 | 8 / 12 |
| `pure_wheat_rush` | 20 | +\$196.75 | \$9,213.93 | 7 / 13 |
| `cow_milk_engine` | 20 | -\$3,114.35 | \$7,690.63 | 5 / 15 |
| `melon_sniper` | 20 | -\$2,991.55 | \$10,868.58 | 8 / 12 |
| `full_production_agent` | 20 | +\$139.20 | \$7,294.05 | 11 / 9 |

### Seed Cluster Means

| Seed | Mean Delta | Seed | Mean Delta |
| :--- | :--- | :--- | :--- |
| **97013** | -\$7,437.60 | **97018** | -\$5,181.00 |
| **97014** | +\$1,241.80 | **97019** | -\$617.40 |
| **97015** | -\$1,982.30 | **97020** | -\$2,378.90 |
| **97016** | +\$258.90 | **97021** | +\$1,347.20 |
| **97017** | -\$3,612.00 | **97022** | -\$1,333.10 |

Positive seed clusters: **3 / 10** (70% of seed clusters degraded).

---

## Part 4: Answers to the 25 Required Questions

1. **How many current FEED actions are survival-mandatory?**
   Approximately 84.5% (9,073 out of 10,737 actions in baseline audit) are strictly required for survival (`consecutive_unfed == 1`) or production-day bonus protection.
2. **How many are economically optional?**
   Only 15.5% (1,664 actions) occur on off-production days when the animal is not currently starving.
3. **How many CARE actions create bonus that is eventually realized?**
   73.9% (7,202 out of 9,752 baseline care actions) directly contribute to realized bonus yield.
4. **How many CARE bonuses are clipped by max-held?**
   Very few under standard play: in baseline audit, only 4 events clipped against existing yield; in discovery with adaptive skips, 306 events were flagged.
5. **Which species wastes the most CARE effort?**
   COW in absolute terms (1,340 flagged care skips); SHEEP in percentage terms (30.9% of sheep care vs 20.3% of cow care).
6. **How much wheat can safely be saved?**
   **Zero wheat during active production cycles.** Saving wheat on off-production days causes the animal to be unfed, which completely blocks CARE banking for that day. Saving $40 of wheat at the cost of forfeiting $140–$200 of milk or wool is deeply negative EV.
7. **How many CARE actions can safely be skipped?**
   Only ~2 to 3 actions per match in the late endgame (Days 29–30) where `days_until_next_yield > days_remaining`. All other CARE actions during the season are required to maximize bonus production.
8. **What do workers do with the saved actions?**
   Workers performed slightly more crop harvests (+1.65 harvests/match), which yielded low-margin crop sales rather than high-margin livestock yields.
9. **Does milk production fall?**
   Yes. Cows missed banking opportunities on days where feed was skipped or care was withheld.
10. **Does wool production fall?**
   Yes. Sheep production cycles (3 days) lost intermediate care increments.
11. **Does realized animal-product revenue fall or rise?**
   Falls significantly across the board, driving the -\$1,969.44 deficit.
12. **Does average realized milk/wool price change?**
   Slightly degrades or remains flat; volume reduction is the primary loss driver.
13. **Were there any animal escapes?**
   **Zero.** Exactly 0 escapes occurred across all 200 matches.
14. **Were any pending care bonuses accidentally lost?**
   Yes. Because CARE banking requires `tile["fed_today"] == True`, every day an animal went unfed, potential care bonus banking was permanently lost for that production cycle.
15. **Did terminal cash improve?**
   **No.** It dropped by -\$1,969.44.
16. **What is mean paired cash delta?**
   **-\$1,969.44**.
17. **What is median/P50?**
   **-\$3,015.50**.
18. **What is the seed-clustered 95% CI?**
   **[-\$3,986.88, +\$48.00]**.
19. **How many seed clusters are positive?**
   **3 out of 10** (30%).
20. **Which opponent classes benefit or regress?**
   Regressed heavily against `pass` (-\$4,077.25), `cow_milk_engine` (-\$3,114.35), and `melon_sniper` (-\$2,991.55). Flat against `pure_wheat_rush` (+\$196.75) and `full_production_agent` (+\$139.20).
21. **Which species contributes most to the cash delta?**
   COW is responsible for over 60% of the negative cash delta due to high milk unit sales volume.
22. **Is adaptive FEED useful?**
   **No.** It is detrimental because it blocks CARE banking and risks production-day zeroing.
23. **Is adaptive CARE useful?**
   Only strictly as an endgame cutoff. In-season CARE skipping depresses bonus yield.
24. **Is the combined policy worth retaining?**
   **No.** It is statistically significantly negative (t = -2.166, p < 0.05).
25. **Should M0-F next be tested together with M0-D Storage Rescue?**
   **No.** Per advancement criteria, features with negative paired mean terminal cash must not proceed to combination testing. M0-D Storage Rescue (+\$5,056.89) stands alone as the proven production candidate.

---

## Part 5: Decision & Codebase State

- `ANIMAL_SERVICE_ECONOMICS_MODE` is confirmed set to `"OFF"` by default in both `agent/config.py` and `submission/config.py`.
- Historical baseline behavior is 100% preserved.
- The discovery experiment results, engine verification microtests, and baseline audit deliverables are permanently archived in:
  - `simulations/results/phase_m0_f_engine_verification/`
  - `simulations/results/phase_m0_f_baseline_audit/`
  - `simulations/results/phase_m0_f_discovery/`
