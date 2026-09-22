# Kaggriculture P3.3-A — Physical Locality & Route Compaction Assignment Results

## Executive Summary

- **Treatment**: `P33_PHYSICAL_LOCALITY_ENABLED = True`, `P33_PHYSICAL_SWITCH_PENALTY = 6` (injected as a calibrated physical cross-quadrant continuity penalty with deadline feasibility escape hatch into Tier 2 regular task matching).
- **Authoritative Control Lineage**: [`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`](file:///d:/website%20project/kaggri%20ox) (Promoted P2.3 baseline).
- **Evaluation Design**:
  - Smoke testing: seeds **92,991–92,995** (10 matched cases, 0 errors).
  - Evaluation tournament: fresh seed block **93,001–93,050** (50 matched pairs $\times$ 2 seat configurations = **100 matched cases / 200 live games**).
  - 5 standard opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`).
- **Verdict**: **REJECT P3.3-A**.
  - Delta is statistical noise ($-\$17.79$/game, $p=0.9706$, median delta $\$0.00$, record 46W / 46L / 8T).
  - Movement reduction was negligible ($-0.5$ turns/game out of 4,755 movement turns), proving that the static modeled ~857 "avoidable" transit candidate is not addressable via candidate scoring adjustments within the existing C2/C6 architecture.

---

## Tournament Results (100 Matched Cases / 200 Games)

| Metric | Control Baseline (`536f1e7`) | Treatment (`P3.3-A`) | Paired Delta |
| :--- | :--- | :--- | :--- |
| **Final Season Score** | **\$103,209.97** | **\$103,192.18** | **-\$17.79/game** |
| **Median Paired Delta** | — | — | **+\$0.00/game** |
| **Standard Error** | — | — | **\$483.02** |
| **95% Confidence Interval** | — | — | **[-\$964.51, +\$928.93]** |
| **Paired $t$-statistic** | — | — | **$t = -0.0368$** |
| **$p$-value** | — | — | **$p = 0.9706$** |
| **Win / Loss / Tie Record** | — | — | **46W / 46L / 8T (46.0% Win Rate)** |

---

## Telemetry & Causal Chain Decomposition

| Dimension | Control Baseline | Treatment (P3.3-A) | $\Delta$ per Game |
| :--- | :--- | :--- | :--- |
| **Movement Turns** | 4,755.4 | 4,754.9 | **-0.5 turns/game** |
| **Idle / PASS Turns** | 438.4 | 443.2 | **+4.7 turns/game** |
| **Cross-Quadrant Moves** | 465.7 | 464.8 | **-0.9 moves/game** |
| **Productive Actions** | 2,023.9 | 2,020.5 | **-3.4 actions/game** |
| **Watering Actions** | 943.0 | 941.7 | **-1.3 actions/game** |
| **Missed Watering at EOD** | 139.2 | 139.4 | **+0.2 actions/game** |

---

## Monetization Accounting

- **Movement Turns Eliminated**: $+0.5$ turns/game (out of the modeled ~857 avoidable transit candidate).
- **Conversion Rate**: $-6.3962$ productive actions per eliminated transit turn.
- **Score Yield**: $-\$33.57$ per eliminated transit turn.
- **Causal Chain Audit**:
  $$\Delta \text{Movement} (-0.5) \rightarrow \Delta \text{Idle} (+4.7) \rightarrow \Delta \text{Productive Actions} (-3.4) \rightarrow \Delta \text{Missed Tasks} (+0.2) \rightarrow \Delta \text{Score} (-\$17.79)$$

---

## Causal Explanation: Why Did Physical Locality Yield Zero Transit Reduction?

1. **Existing C2 Zonal Partitioning Already Captures Local Affinity**:
   - The production baseline C2 zonal scheduler already assigns workers to home zones (`home_cands = [u for u in cands if home_quads[u] == target_quad]`).
   - Home-zone workers are evaluated *first* before any spillover candidate is considered.
   - In addition, C6 travel weighting ($3 \times \text{distance}$) already heavily disincentivizes assigning distant workers to tasks when nearby workers are available.
2. **Remaining Cross-Quadrant Transitions Are Structurally Exogenous**:
   - The 465.7 cross-quadrant transitions per game are not caused by loose tie-breaking in regular task matching.
   - They are driven almost entirely by:
     1. **Tier 1 Urgent Tasks**: Animal placement (carrying bought livestock to NW/NE pastures), emergency feed rescue, and decay harvesting bypass Tier 2 entirely.
     2. **Quadrant Workload Imbalances**: When one quadrant finishes its morning watering/harvest sweeps earlier than the other, workers legitimately spill over to prevent idling.
     3. **Shed Access Constraints**: Shed tiles are located at $(4,4)-(5,5)$ on the quadrant intersection; entering and leaving the shed naturally crosses quadrant boundaries.
3. **The Static ~857 "Avoidable Transit" Candidate Is Not Causally Addressable by Locality Scoring**:
   - The static diagnostic counted all non-minimal transit as "avoidable candidate".
   - However, within the constrained 2-quadrant layout, workers cannot reduce transit further without refusing necessary cross-quadrant work (spillover) or delaying shed deposits.
   - Penalyzing quadrant switching merely nudged a tiny fraction of edge assignments (0.5 turns/game), creating +4.7 idle turns where workers waited instead of helping across the boundary.

---

## Final Decision & Lineage State

- **Decision**: **REJECT P3.3-A**.
- **Lineage Integrity**: Authoritative baseline remains strictly [`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`](file:///d:/website%20project/kaggri%20ox).
- **Next Step**: Proceed to investigate **P3.3-B Shed Deposit Batching**, which addresses the second, distinct causal mechanism behind cross-map transit (delaying small, single-item deposits so workers can finish localized sweeps before returning to the shed).
