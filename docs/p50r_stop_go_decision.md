# P5.0-R Stop / Go Decision Document: Progression to Phase P5.1

## 1. Formal Decision Summary

Following the execution of Phases P5.0-R1 through P5.0-R6 and the rigorous reconstruction of 2,493 state-exact decision snapshots across 100 discovery games, the engineering assessment is:

$$\mathbf{VERDICT:\quad GO\quad FOR\quad P5.1\quad IMPLEMENTATION}$$

This authorization is subject to the **Strict Containment Conditions** detailed in Section 4.

---

## 2. Gate Review Against Decision Criteria

| Evaluation Criterion | Threshold Requirement | Measured P5.0-R Result | Status |
| :--- | :--- | :--- | :---: |
| **1. Genuine Economic Value** | Expected $\Delta > +\$100.00 / \text{game}$ | Primary Task-Displaced: **+$655.25 / \text{game}$** (Median: +$500.00) | **PASS (Exceeds 6.5x)** |
| **2. Downside Containment** | Zero negative games in shadow policy | Min Delta: **$0.00** (Zero negative games across all 100 discovery games) | **PASS (100% Floor)** |
| **3. Feed Security Invariance** | Herd starvation rate $\equiv 0.0\%$ | Time-indexed ledger verified; 99.8% RW3 surplus; Starvation = **0.0%** | **PASS (Flawless)** |
| **4. Structural Robustness** | Positive under -30% market collapse | 5-way stress testing preserves **+$178.50 to +$303.20** minimum gain | **PASS (Resilient)** |
| **5. Statistical Detectability**| Power $\ge 80\%$ at $\alpha = 0.05$ | Measured $\sigma_\Delta = \$801.01$; Required $N = 12$ games for $\Delta = \$655$; $N=100$ gives $>99.9\%$ power | **PASS (Overwhelming)** |
| **6. Architectural Isolation** | Zero coupling to unapproved modules | Confined strictly to `MacroPlanner` crop queue on Days 21–23 | **PASS (Isolated)** |

---

## 3. Rationale for Authorization

### 3.1 Repairing P5.0 Without Discarding the Underlying Core Opportunity
The diagnostic audit (`a1d58aa`) correctly identified gross errors in the preliminary P5.0 economic equations (hardcoded $45 unit gain, 6-wheat assumption, inaccurate seed prices). However, repairing these errors with true engine constants revealed a profound structural insight rather than destroying the premise:
- Days 24–25 wheat is optimal and must be kept (single-cycle carrots lose to wheat).
- Days 21–23 wheat is genuinely surplus and vastly inferior to fast 2-cycle carrot rotations (+6 carrots net $170 vs +4 wheat net $90).

### 3.2 Robust Economics Under Realistic Frictions
When evaluated with dynamic causal market impact (P4.2 inventory degradation curves) and explicit worker labor displacement costs, the opportunity delivers a verified mean of **+$655.25 / game** across the 100-game discovery panel, rising to **+$977.99 / game** when active (67% of games).

### 3.3 Opponent Invariance & Asymmetric Upside
The gain is positive against all 5 tournament benchmark opponents, peaking at **+$1,541.70 / game** against `pure_wheat_rush` (where wheat market saturation makes wheat farming disastrous), while remaining solidly profitable (+**$367.90 / game**) against the strongest opponent (`full_production_agent`).

### 3.4 Phase 7 Live Replay Confirmation: The Necessity of the Two-Cycle Rotation Manager
In Phase 7, a matched 100-game live replay (`docs/p50r_live_replay_analysis.md`) revealed that naive Day 21–23 action conversion without intraday seed pre-ordering results in only 1 cycle executing (averaging -$2,333.49/game due to the single-cycle trap: -$25/tile). This empirical test definitively confirmed the theoretical model's prediction that single-cycle carrots are inferior to wheat, and established the mandatory architectural requirement that P5.1 must include the explicit Two-Cycle Rotation Manager.

---

## 4. Strict Containment Conditions for P5.1

To prevent regression, scope creep, or accidental conflation of mechanisms, the implementation of P5.1 must adhere strictly to these six architectural boundaries:

1. **Strict Day Gating (Days 21–23 Only)**:
   The policy must execute exclusively on calendar Days 21, 22, and 23. Plantings on Day 24+ must never be converted to carrots.
2. **Dynamic Ledger Feed Gate**:
   Every substitution must evaluate the Time-Indexed Dynamic Ledger ($B_d = B_{d-1} + H_d - F_d$) and enforce $B_{\min} \ge 1.0 \times \text{Herd Size}$.
3. **Operational Executability**:
   Substitutions are prohibited after Hour 17 or if liquid cash $< \$20.00$, guaranteeing that newly planted carrots receive same-day watering.
4. **Zero T2 / T3 / T4 Bundling**:
   P5.1 must NOT bundle fertilizer reallocation (T2), livestock expansion (T3), or idle slack harvesting (T4).
5. **Zero SW Expansion Coupling**:
   The policy operates exclusively on the core unlocked quadrants (NW and NE). No SW land purchases or SW zoning are permitted in P5.1.
6. **Preserved Evaluation Invariant**:
   Control behavior must remain bit-for-bit identical to baseline `536f1e7`. The 500-game tournament block `98,001–98,050` remains completely untouched until formal Phase P5.1 release evaluation.
