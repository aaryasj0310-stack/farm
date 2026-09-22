# Kaggriculture P5.1 — Held-Out Formal Tournament Evaluation Protocol

## 1. Protocol Pre-Registration Overview
This document pre-registers the formal evaluation protocol for **P5.1: Two-Cycle Carrot Rotation Implementation** against the authoritative production baseline (`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`).

Following scientific integrity requirements, the tournament evaluates the isolated P5.1 treatment on a strictly held-out panel of environment seeds that have remained untouched throughout discovery and development.

---

## 2. Experimental Design

### 2.1 Treatment vs Control
- **Control**: Baseline commit `536f1e7` (`P51_T1_TWO_CYCLE_CARROT_ENABLED = False`).
- **Treatment**: Isolated P5.1 Treatment (`P51_T1_TWO_CYCLE_CARROT_ENABLED = True`).
- **Identical Invariants**:
  - Exact same seeds, engine configuration, and opponent implementations.
  - Same core farm zoning (SW block protected for livestock).
  - Exact same hiring schedule, livestock acquisition schedule, crop planting caps, and market order policies.
  - The sole behavioral difference is substituting eligible Day 21–23 wheat plantings on NW+NE core tiles with two consecutive carrot rotations under sequential feed safety guarantees.

### 2.2 Evaluation Panel
- **Seed Range**: `98,001` through `98,050` (50 seeds).
- **History**: Strictly untouched across P4.x, P5.0, P5.0-R, and P5.1 discovery.
- **Opponent Pool** (5 distinct agents):
  1. `pass` (No-op environment baseline)
  2. `pure_wheat_rush` (Aggressive crop rush)
  3. `cow_milk_engine` (Livestock compounding engine)
  4. `melon_sniper` (High-value late cash crop strategy)
  5. `full_production_agent` (Complete competitive production baseline)
- **Seat Balancing**: Both Seat 0 (P0) and Seat 1 (P1) tested for every (seed, opponent) pair.
- **Sample Size**:
  $$\text{Total Scenarios} = 50 \text{ seeds} \times 5 \text{ opponents} \times 2 \text{ seats} = 250 \text{ matched pairs}$$
  $$\text{Total Live Games} = 250 \times 2 = 500 \text{ full simulation games}$$

---

## 3. Success & Acceptance Criteria

To achieve formal tournament validation and promotion to default production, the treatment must satisfy all of the following conditions simultaneously:

1. **Positive Net Cash Delta**:
   $$\overline{\Delta \text{Money}} = \frac{1}{N} \sum_{i=1}^N (\text{Money}_{\text{treat}, i} - \text{Money}_{\text{ctrl}, i}) > 0$$
2. **Statistical Significance**:
   - Paired two-tailed t-test or Wilcoxon signed-rank test on $\Delta \text{Money}$ achieving $p < 0.05$.
   - Lower bound of 95% Confidence Interval > \$0.
3. **Zero Livestock Starvation**:
   $$\text{Starvation Rate}_{\text{treat}} = 0.0\% \quad (0 \text{ animals starved across all 250 treatment games})$$
4. **Competitive Win Rate Non-Inferiority**:
   $$\text{Win Rate}_{\text{treat}} \ge \text{Win Rate}_{\text{ctrl}}$$
5. **Execution Reliability**:
   - Cycle 2 completed rate $\ge 90\%$ of physically planted Cycle 1 candidates.
   - Zero Day 23 planting-day watering dropouts.

---

## 4. Pre-Registered Stopping Rules (Early Abort)

To prevent resource waste and guard against catastrophic failure modes, the tournament runner implements automated early stopping:

1. **Livestock Starvation Trigger**:
   - If any animal in the treatment condition reaches $\ge 2$ consecutive unfed days, the tournament terminates immediately with a **FATAL ABORT** and automatic **REJECT**.
2. **Underperformance Threshold**:
   - If after $N \ge 50$ completed matched pairs, the running cumulative mean cash delta drops below $-\$500.00/\text{game}$, the tournament halts with an **EARLY STOPPING** flag.

---

## 5. Execution Runner

The executable script implementing this exact protocol has been generated and validated:
- Script: [`simulations/experiments/run_p51_formal_tournament.py`](file:///d:/website%20project/kaggri%20ox/simulations/experiments/run_p51_formal_tournament.py)
- Results Output: `simulations/experiments/results/p51_formal_tournament_summary.json`
- Max Parallel Workers: 8 worker processes (`ProcessPoolExecutor`)
- Status: Ready for automated deployment upon formal approval.
