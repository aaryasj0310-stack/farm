# Phase M0-D-R1: Clean Committed-Code Reproduction & Provenance Freeze Report

## Executive Summary

Phase M0-D-R1 successfully executed a **100% bit-for-bit perfect reproduction** of the Phase M0-D Storage Rescue discovery experiment from clean committed code at commit `1f9b44f0ad6dcdd06a75998f9491ed7a15169342`.

Across all 100 paired cells (200 matches) on consumed discovery seeds 97013–97022:
- **Exact Control Cash Matches:** **100 / 100 (100.0%)** ($0.00 max difference)
- **Exact Treatment Cash Matches:** **100 / 100 (100.0%)** ($0.00 max difference)
- **Exact Paired Delta Matches:** **100 / 100 (100.0%)** ($0.00 max difference)
- **Mean Paired Cash Delta:** **+\$5,056.89**
- **Median Paired Cash Delta (P50):** **+\$5,012.00**
- **Head-to-Head Win Rate vs Control:** **84.0%** (84 Wins, 0 Ties, 16 Losses)
- **95% Clustered CI (10 seed clusters):** **[+\$2,504.43, +\$7,609.35]** (strictly positive)
- **All 10 Seed Cluster Means Positive:** **10 / 10 (100.0%)**
- **Authoritative Discard Reduction:** **-92.4%** (3,682 units destroyed in C0 reduced to 279 units in C2)
- **Base-Price Value Preserved:** **+\$2,938.45 / match**
- **Contemporaneous Spot Value Preserved:** **+\$4,542.16 / match**
- **Feed Safety:** **0 / 659 feed floor violations**, **0 animal escapes**
- **Order Cap Headroom:** **0 / 659 rescue orders blocked** by the 10-order cap; **100% executed** in the engine.

All results and artifacts are now cryptographically, procedurally, and authoritatively tied to committed code.

---

## 1. Provenance Audit & Committed SHA Verification

### 1.1 Original M0-D Provenance Discrepancy
In Phase M0-D, the experiment was executed while working tree edits were staged in memory prior to creating the final experiment commit. Consequently, the M0-D manifest recorded parent commit `32d9d91536a02a320f829c026aa03d0b4404bf57` instead of the commit containing the treatment implementation (`1f9b44f0ad6dcdd06a75998f9491ed7a15169342`).

### 1.2 M0-D-R1 Freeze & Cryptographic Verification
Phase M0-D-R1 resolved this ambiguity by freezing the committed code and running a fresh, from-scratch 200-match matrix under clean working tree conditions.

- **Evaluated Commit SHA:** `1f9b44f0ad6dcdd06a75998f9491ed7a15169342`
- **Preceding Commit:** `8b7e2589c72a258dd10e492f60f5e381154f74eb` (Authoritative Audit)
- **Working Tree Cleanliness:** Verified clean before execution.
- **Source Code Parity:** Full SHA-256 hashes recorded in [`source_hashes.json`](file:///d:/website%20project/kaggri%20ox/simulations/results/phase_m0_d_r1_reproduction/source_hashes.json):
  - `agent/config.py` $\equiv$ `submission/config.py` (`046ca75381590569...`)
  - `agent/main.py` $\equiv$ `submission/main.py` (`069e572154fdeb2c...`)
  - `agent/execution/midnight_storage_controller.py` $\equiv$ `submission/execution/midnight_storage_controller.py` (`8484169bfedcbc6f...`)

---

## 2. Bit-for-Bit Reproduction Metrics

Every configuration `(seed, opponent, seat)` was evaluated in a clean process pool and compared directly against original M0-D match records:

| Reproduction Metric | Target | Observed | Result |
| :--- | :---: | :---: | :---: |
| **Exact Control Cash Matches** | 100 / 100 | **100 / 100 (100.0%)** | **PERFECT** |
| **Exact Treatment Cash Matches** | 100 / 100 | **100 / 100 (100.0%)** | **PERFECT** |
| **Exact Paired Delta Matches** | 100 / 100 | **100 / 100 (100.0%)** | **PERFECT** |
| **Max Control Cash Difference** | \$0.00 | **\$0.00** | **PERFECT** |
| **Max Treatment Cash Difference** | \$0.00 | **\$0.00** | **PERFECT** |
| **Max Delta Difference** | \$0.00 | **\$0.00** | **PERFECT** |

The simulation engine, environment seeding, and agent decision tree proved 100% deterministic. Not a single cent of discrepancy was observed across 200 matches.

---

## 3. Authoritative Economic & Storage Reproduction

### 3.1 Financial Performance Reproduction

| Metric | Original M0-D | Clean Rerun (M0-D-R1) | Discrepancy |
| :--- | :---: | :---: | :---: |
| **CONTROL Mean Cash** | \$104,009.28 | **\$104,009.28** | \$0.00 |
| **RESCUE Mean Cash** | \$109,066.17 | **\$109,066.17** | \$0.00 |
| **Mean Paired Delta** | +\$5,056.89 | **+\$5,056.89** | \$0.00 |
| **Median Paired Delta (P50)** | +\$5,012.00 | **+\$5,012.00** | \$0.00 |
| **Head-to-Head (W / T / L)** | 84 / 0 / 16 (84.0%) | **84 / 0 / 16 (84.0%)** | 0 |
| **10th / 25th Percentile** | -\$2,063.30 / +\$2,157.75 | **-\$2,063.30 / +\$2,157.75** | \$0.00 |
| **75th / 90th Percentile** | +\$6,761.00 / +\$12,664.30 | **+\$6,761.00 / +\$12,664.30** | \$0.00 |
| **Cluster Standard Error ($SE_{cl}$)** | \$1,128.33 | **\$1,128.33** | \$0.00 |
| **95% Clustered CI** | [+\$2,504.43, +\$7,609.35] | **[+\$2,504.43, +\$7,609.35]** | \$0.00 |

### 3.2 Seed Cluster Means (10 / 10 Strictly Positive)

| Seed | Control Mean Cash | Treatment Mean Cash | Paired Cash Delta |
| :---: | :---: | :---: | :---: |
| **97013** | \$104,115.30 | \$109,230.00 | **+\$5,114.70** |
| **97014** | \$101,659.10 | \$111,629.30 | **+\$9,970.20** |
| **97015** | \$108,610.10 | \$112,927.90 | **+\$4,317.80** |
| **97016** | \$107,314.10 | \$111,474.20 | **+\$4,160.10** |
| **97017** | \$105,420.90 | \$110,093.10 | **+\$4,672.20** |
| **97018** | \$105,404.90 | \$110,868.90 | **+\$5,464.00** |
| **97019** | \$97,931.20 | \$110,161.70 | **+\$12,230.50** |
| **97020** | \$101,677.30 | \$103,700.00 | **+\$2,022.70** |
| **97021** | \$101,744.10 | \$103,094.70 | **+\$1,350.60** |
| **97022** | \$106,215.80 | \$107,481.90 | **+\$1,266.10** |

---

## 4. Corrected Inventory-Value Terminology & Spot Valuation

In original Phase M0-D, the valuation of discarded products used fixed `PRODUCT_BASE_PRICES` (e.g., Wheat=\$25, Strawberry=\$120, Melon=\$250), which was inaccurately labeled as "spot value".

Phase M0-D-R1 rectifies this by explicitly measuring two distinct metrics:
1. **Base-Price Value:** Evaluated at static base prices:
   $$\text{Base Value Discarded} = \sum_{p} \text{discarded}(p) \times \text{BasePrice}(p)$$
2. **Actual Contemporaneous Spot-Price Value:** Evaluated at exact market quotes `obs.market["prices"][p]` immediately prior to the midnight drop:
   $$\text{Actual Spot Value Discarded} = \sum_{p} \text{discarded}(p) \times P_{\text{market}}(p)$$

### Comparison of Discard Valuation

| Valuation Method | Control (C0) Loss / Match | Treatment (C2) Loss / Match | Preserved Value / Match |
| :--- | :---: | :---: | :---: |
| **Base-Price Valuation** | \$3,214.15 | \$275.70 | **+\$2,938.45** |
| **Contemporaneous Spot-Price Valuation** | \$4,875.29 | \$333.13 | **+\$4,542.16** |

**Crucial Insight:** Because late-season produce (especially strawberries, wool, and milk) often traded well above base price when market inventories were tight, the true contemporaneous spot-market value destroyed by the engine in C0 averaged **\$4,875.29 per match**. The storage rescue mechanism preserved **+\$4,542.16 per match** in real spot value, which directly explains the observed **+\$5,056.89** gain in terminal cash.

---

## 5. Rescue Lifecycle & Order Cap Verification

Across all 100 treatment matches (2,400 turns):
- **Rescue Opportunities Identified:** 659 events (averaging 6.59 events / match).
- **Rescue Orders Requested:** 659 orders.
- **Rescue Orders Blocked by 10-Order Cap:** **0** (in 100% of events, `len(market) < 10` before rescue).
- **Rescue Orders Emitted in Action:** 659 orders.
- **Rescue Orders Executed in Engine:** **659 orders (100.0% execution success rate)**.
- **Total Surplus Wheat Sold:** 6,323 units (mean 63.23 units / match, ~9.59 units per order).
- **Order Timing & Mechanism:** Orders are emitted at Hour 23. In `_process_market`, the engine deductions occur atomically and farm cash is credited. Immediately afterward in `_end_of_day`, worker carried inventories deposit into the newly vacated capacity without overflowing.

---

## 6. Feed Safety & Livestock Health

To verify that selling surplus wheat at Hour 23 never compromised herd sustenance, every treatment turn was audited for feed constraints:
- **Safety Rule Enforced:** $\text{shed\_wheat} \ge \max(10, \text{animal\_count} \times 2)$.
- **Total Feed Floor Audits:** 659 checks immediately post-rescue.
- **Feed Floor Violations:** **0 / 659 (0.0%)**.
- **Animal Escapes:** **0** across all 100 treatment matches.
- **Max Consecutive Unfed Turns:** **1** (engine escape requires $\ge 2$).
- **Verdict:** Herd safety remained 100% uncompromised.

---

## 7. Losing Pair Reproduction (16 / 16 Exact)

All 16 negative configurations reproduced with exact bit-for-bit deltas:
- **Seed 97016 vs `cow_milk_engine` (Seats 0 & 1):** Delta -\$8,368 and -\$8,668 (exact match).
- **Seed 97020 vs `melon_sniper` (Seat 1):** Delta -\$6,285 (exact match).
- **Seed 97022 vs `melon_sniper` (Seat 1):** Delta -\$6,070 (exact match).
- **Seed 97021 vs `cow_milk_engine` (Seats 0 & 1):** Delta -\$5,315 and -\$5,610 (exact match).
- **Severe Losses (< -\$5,000):** Exactly 6 pairs, identical to original discovery.

---

## 8. Explicit Final Answers to Required Questions

1. **Was M0-D originally run from an uncommitted working tree?**
   Yes. In M0-D, the simulation ran while rescue changes were in the working tree, which caused the manifest to log parent commit `32d9d915...` prior to the rescue commit `1f9b44f0...`.
2. **Does clean committed SHA `1f9b44f...` reproduce the original CONTROL results?**
   **Yes, 100 / 100 matches identical** (\$0.00 max diff).
3. **Does it reproduce the original RESCUE results?**
   **Yes, 100 / 100 matches identical** (\$0.00 max diff).
4. **How many of the 100 paired deltas match exactly?**
   **100 / 100 (100.0%)**.
5. **What is the clean-rerun mean paired cash delta?**
   **+\$5,056.89**.
6. **What is the clean-rerun median/P50 delta?**
   **+\$5,012.00**.
7. **What is the clean-rerun win/tie/loss record?**
   **84 Wins / 0 Ties / 16 Losses (84.0% win rate)**.
8. **What is the clean-rerun seed-clustered 95% CI?**
   **[+\$2,504.43, +\$7,609.35]** ($SE_{cl} = \$1,128.33$, $df=9$, $t_{crit} \approx 2.262$).
9. **Are all 10 seed-cluster means still positive?**
   **Yes, 10 / 10 (100.0%)** (ranging from +\$1,266.10 to +\$12,230.50).
10. **Is the 92.4% discard reduction reproduced?**
    **Yes, exactly 92.4%** (3,682 units in C0 $\to$ 279 units in C2; 3,403 units saved).
11. **What is the corrected base-price value preserved?**
    **+\$2,938.45 / match**.
12. **What is the actual contemporaneous spot-price value preserved?**
    **+\$4,542.16 / match** (\$4,875.29 in C0 $\to$ \$333.13 in C2).
13. **How many rescue orders were requested?**
    **659 orders**.
14. **How many were present in the final market action?**
    **659 orders**.
15. **How many actually executed?**
    **659 orders (100.0%)**.
16. **Were any rescue orders blocked by the 10-order cap?**
    **No (0 blocked)**. Headroom was available in 100% of opportunities.
17. **Were there any feed-floor violations?**
    **No (0 / 659 violations)**.
18. **Were there any animal escapes caused by rescue?**
    **No (0 escapes)** across all 100 matches.
19. **Do the original losing pairs reproduce?**
    **Yes, all 16 losing pairs reproduced with exact identical cash and deltas**.
20. **Is the +\$5k effect now cryptographically/procedurally tied to committed code?**
    **Yes**. Executed from clean committed SHA `1f9b44f0ad6dcdd06a75998f9491ed7a15169342` with full source hashes and exact provenance verification.
21. **Should `96521–96540` now be consumed for fresh confirmation?**
    **YES**. All reproduction criteria, safety invariants, and provenance requirements are fully satisfied.

---

## 9. Final Advancement Gate Verdict

```text
============================================================
PHASE M0-D-R1 ADVANCEMENT GATE: PASSED
- Clean Committed Reproduction: SUCCESS (100/100 exact)
- Economic Delta: +$5,056.89 mean / +$5,012.00 median
- Seed-Clustered 95% CI: [+$2,504.43, +$7,609.35]
- Discard Reduction: 92.4% (3,682 -> 279 units)
- Feed Safety: 100% maintained (0 violations, 0 escapes)
- Provenance Ambiguity: FULLY RESOLVED
VERDICT: AUTHORIZED TO PROCEED TO FRESH CONFIRMATION (96521–96540)
============================================================
```
