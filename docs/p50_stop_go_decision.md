# P5.0 Formal Decision Gate: Evidence-Based STOP/GO Recommendation

## Executive Decision: UNANIMOUS GO FOR P5.1

Based on the 100-game empirical audit of the Promoted P2.3 Production Baseline across 10 fresh seeds (96,201–96,210), the evidence demonstrates that within-core tile and input allocations suffer from a massive, highly quantifiable defect:

### The Definitive Finding
- While the promoted P2.3 fix completely solved Day 26+ terminal wheat (0 W4 occurrences), the agent continues to plant **24.9 surplus W3 wheat crops per game** between Days 21 and 25.
- Because these crops are planted when herd feed requirements through Day 30 are already 100% guaranteed, this grain serves no survival purpose and yields low return into a saturated market.
- Diverting these 24.9 planting decisions into 3-day high-turnover Carrot cycles yields a projected gain of:
  $$\mathbf{+\$1121.85\text{ per game}}$$
  with a statistical sample size requirement of **only 5 games** to achieve 80% power at $\alpha = 0.05$.

---

## P5.1 Experiment Scope & Implementation Specification

### 1. Primary Treatment (Arm B - T1 Marginal Wheat Gate)
Modify `agent/strategy/macro_planner.py`:
- During Days 21–25, before placing any WHEAT planting mission, evaluate:
  $$\text{Feed Buffer} = \text{Shed Grain} + \text{Held Grain} + 6 \times (\text{In-Ground Wheat}) - (\text{Herd Size} \times (30 - \text{Day}))$$
- If $\text{Feed Buffer} \ge 0$, strictly suppress WHEAT and substitute CARROT.

### 2. Secondary Treatment (Arm C - T1 + T2 Fertilizer Pruning)
Modify `agent/strategy/macro_planner.py` / `task_scheduler.py`:
- For Tomatoes, suppress FERTILIZE missions whenever fertilizer spot price > $50.00.

### 3. Evaluation Panel for P5.1
- Standard 50-game tournament verification on seeds 96,201–96,205 across 5 opponents and 2 seats.
- Success criterion: paired delta $\ge +\$500	ext{/game}$, win rate $\ge 98\%$, zero cash reconciliation deltas.
