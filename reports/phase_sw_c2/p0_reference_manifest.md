# Phase SW-C2: P0 Reference Manifest and Engine Verification

**Date:** 2026-09-28  
**Starting HEAD:** `ec16d96fa19efc5f7f7f33bb416ff9778bccb0d7`  
**Current Branch:** `experiment/sw-c2-workforce-coordinator`  
**Protected Canonical Production Commit:** `faa6cb99f66b2066e639806d0eabc72a0c7d7982`  
**Protected Production Submission SHA-256:** `E7FF7C5A4B91364C10898CB8A22E4680C9330F1E30171593DA2D1EED7DD4ED41` (`dist/submission.zip`)  
**Long-term Objective:** Reproducible mean final cash of at least **$130,000** without sacrificing safety or core incumbent production.

---

## 1. Environment & Engine Verification

- **Python Runtime:** Python 3.12.10 (win32)
- **Kaggle Environments:** Version 1.32.7
- **Engine Source:** `C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py`
- **Engine SHA-256:** `BC8A54879EF02C7EA64B8B333D6A976F0EA65C4949149D01F463F23BCCEE653E`

### Direct Engine Mechanics Probe Findings

1. **Terminal Step Boundary**:
   - `kaggriculture.py` lines 960-964: `if step >= cfg.episodeSteps - 2: for s in state: s.status = "DONE"`.
   - In a 720-step episode (`cfg.episodeSteps = 720`), `cfg.episodeSteps - 2 = 718`.
   - Agent is called and its actions are executed on Step 718 (Day 29, Hour 22).
   - Following step 718 execution, the environment sets `s.status = "DONE"`.
   - Agent is **NEVER called** on Step 719 (Day 29, Hour 23).
   - **Conclusion:** Step 718 (D29H22) is the final executable decision turn for both worker actions and market orders. Any plan relying on D29H23 is mechanically impossible.

2. **Turn Execution Ordering**:
   - In `interpreter()`:
     1. Unit actions (`_apply_unit_action`) for farmer and all existing hands.
     2. Market order processing (`_process_market`), executing atomic orders (`HIRE`, `BUY_LAND`) first, followed by unit lockstep for `SELL` and `BUY_*`.
     3. Town shop consumption (`_town_consume`).
     4. Plant decay check (`_decay_plants`).
     5. End-of-day rollover if `(step + 1) % 24 == 0` (`_end_of_day`).
   - **Conclusion:** Worker actions precede market settlement. Goods purchased or workers hired on turn $T$ cannot be utilized by workers until turn $T+1$.

3. **Morning Hiring Dynamics**:
   - HIRE orders submitted at Hour 0 are executed in `_process_market` at the conclusion of Hour 0.
   - Hands spawn on shed access tiles and are available to receive commands starting at Hour 1.
   - Workers cannot be assigned actions on Hour 0.

4. **Midnight Rollover & Worker Disappearance**:
   - At midnight (`_end_of_day`):
     - `_drop_inventories_to_shed()` transfers worker-held inventory to shed up to `shed_capacity` (100). Excess is dropped/discarded.
     - `farm["farmer"]` teleports back to spawn `(4, 4)`.
     - `farm["hands"] = []` (all hired hands disappear and must be rehired each day).
     - `farm["hires_today"] = 0` (cost curve resets).
     - `private["inventories"] = [{}]` (only farmer's empty inventory remains).

5. **Crop Yield Semantics (Melon & Non-ongoing Crops)**:
   - For non-ongoing crops (WHEAT, CARROT, MELON):
     - `window_start = (crop_data["max_yield_day"] + 1) // 2`. For Melon (`max_yield_day=12`), `window_start = 6`.
     - During days where `6 <= age_days <= 12`, watering increments `tile["yield_units"]` by +1 (+2 if fertilized), up to `max_yield = 6`.
     - Earliest harvest is allowed when `age_days >= first_yield_day` (Day 10 for Melon).
     - **Conclusion:** Melon yield is neither fixed at 2 nor fixed at 6. Yield equals the number of effective watered days within the maturity window $[6, 12]$ (capped at 6).

6. **Livestock Service & Escape Rules**:
   - Consecutive unfed count increments each day an animal is not fed.
   - If `consecutive_unfed >= 2` at midnight, the animal escapes permanently (structure remains).
   - Care bonus banks on days when the animal is BOTH cared and fed. Care bonus is redeemed on production days if fed.
   - Held yield caps at `max_held` (4 for goose, 6 for cow/sheep); production beyond cap is lost.

---

## 2. Historical Baseline Reference

From the pooled 40-pair tournament in Phase SW-C1:

| Historical Arm | Mean Final Cash | Std Dev | Notes |
|:---|---:|---:|:---|
| **Arm A (Canonical Production, SW OFF)** | **$113,368.88** | $9,836.51 | Incumbent reference |
| **Arm B (Frozen B3C, 8 Tiles)** | **$109,302.50** | $10,946.41 | Historical 8-tile control |
| **Arm C (Adaptive Control, Capped 8)** | **$109,302.50** | $10,946.41 | Exact 40/40 matched parity with Arm B |
| **Arm D (Adaptive Max 12)** | **$106,449.05** | $11,187.51 | -$2,853.45 vs Arm B |
| **Arm E (Adaptive Max 16)** | **$103,794.80** | $12,605.16 | -$5,507.70 vs Arm B |
| **Arm F (Adaptive Max 20)** | **$102,013.50** | $13,434.04 | -$7,289.00 vs Arm B |
| **Arm G (Adaptive Max 24)** | **$99,915.12** | $14,653.90 | -$9,387.38 vs Arm B |

---

## 3. P0-A Gate Verdict

- **Repository state:** Clean, verified HEAD `ec16d96fa19efc5f7f7f33bb416ff9778bccb0d7`, branched to `experiment/sw-c2-workforce-coordinator`.
- **Protected assets:** Canonical commit `faa6cb9` and submission artifact `dist/submission.zip` SHA-256 verified untouched.
- **Engine ground truth:** Probed and recorded with 100% precision.
- **P0-A Gate Status:** **PASSED**. Authorized to proceed to P0-B.
