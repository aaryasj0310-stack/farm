# Phase B1-R3: SW Purchase Retry Real-Engine Verification Report

## 1. Diagnostic Overview & Configuration

- **Execution Command**: `python scripts/verify_sw_purchase_retry_engine.py`
- **Evaluated Commit SHA**: `709c6def9d8052a7598be0fbd375e6faf25b4913`
- **Kaggle Environments Version**: `1.32.7`
- **Python Version**: `3.12.10`
- **Platform**: `Windows-11-10.0.26200-SP0`
- **Evaluated Configuration**:
  - Seed: `96502` (previously consumed discovery seed)
  - Opponent: `pure_wheat_rush`
  - Seat: `0`
  - Mode: `TREATMENT` (corrected experimental SW tranche controller)
  - Episode Steps: `720` (full 30-day season)

---

## 2. Complete Purchase Lifecycle Verification

The engine trajectory dynamically captured every turn's pre-action state, agent decisions, emitted orders, and post-action engine observations.

The complete sequence genuinely occurred:

```text
Step 222 (Day 9, Hour 6):
Planner approves SW purchase -> OrderBuilder drops BUY_LAND (discretionary cash $1966.0 < $2,000 land price)
↓
Controller remains in active retry state (sw_purchase_approved=True, no permanent lockup)
↓
Step 226 (Day 9, Hour 10):
Cash reaches $3261.0 (discretionary $2961.0 >= $2,000)
BUY_LAND emitted in final action (Retry #4)
↓
Engine processes BUY_LAND: deducts $2,000, updates farm.unlocked_quadrants to ['NW', 'NE', 'SW']
Purchase confirmed: cash after = $761.0
↓
Step 233 (Day 9, Hour 17):
Tranche becomes operational (1 SW tiles planted)
↓
Step 719: Match completes successfully. Final Cash: $100,233.00.
```

---

## 3. Authoritative Event Record Table

| Step | Day:Hour | Cash Before | Reserve | Discretionary Cash | Approval | Requested | Emitted | Unlocked Before | Unlocked After | Cash After | Drop Reason | Confirmed | Retry # |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 222 | D9:H6 | $2266.0 | $300.0 | $1966.0 | True | False | False | False | False | $2266.0 | budget | False | 0 |
| 223 | D9:H7 | $2266.0 | $300.0 | $1966.0 | True | False | False | False | False | $2266.0 | budget | False | 1 |
| 224 | D9:H8 | $2266.0 | $300.0 | $1966.0 | True | False | False | False | False | $2266.0 | budget | False | 2 |
| 225 | D9:H9 | $2266.0 | $300.0 | $1966.0 | True | False | False | False | False | $3261.0 | budget | False | 3 |
| 226 | D9:H10 | $3261.0 | $300.0 | $2961.0 | True | True | True | False | True | $761.0 | None | True | 4 |

---

## 4. Key Verification Findings

1. **Approval Does Not Equal Purchase**:
   At Step 222, `controller_approval` was `True`, but `purchase_order_in_final_action` was `False`. SW remained `LOCKED` in engine observations (`unlocked = ['NW', 'NE']`).
2. **Failed Orders Do Not Cause Permanent Lockup**:
   Unlike the uncorrected B1 implementation where an initial drop suppressed all future retries, the corrected state machine retried at Step 226 as soon as cash reached $3261.0.
3. **No Premature Planting**:
   Zero SW tiles were planted while SW remained `LOCKED`. Planting began exclusively after engine confirmation, at Step 233.
4. **Engine & Strategy Invariants**:
   No assertion errors or fatal exceptions occurred. The match executed to full 720-step completion with final cash of $100,233.00.
