# P6.1-C Final Outcome Verdict & Recommendation (Corrected)

## 1. Formal Decision & Classification

### Mechanism Verdict: **MECHANISM NO-GO**
The physical mechanism designed in P6.1 — *Shed-Overflow Prevention via Pre-Midnight Storage Hygiene* — is a definitive **NO-GO**:
- Discard Reduction Target: **$\ge 70.0\%$** (reduce discards to $<12$ units/game).
- Discard Reduction Achieved: **$2.80\%$** (reduced discards from 42.08 to 40.90 units/game, saving only 1.18 units).
- **Failure Cause**: Fundamental physical decoupling between shed inventory and worker backpacks in the simulation engine. The items causing midnight overflow reside in field backpacks, which the engine's market processor cannot sell. Pre-midnight shed sales were idle in 43.9% of windows and only sold 7.57 times per 30-day game.

### Strategic Treatment Recommendation: **TREATMENT ITERATE (NO-GO ON MECHANISM, PIVOT TO P6.2)**
The P6.1 implementation must **remain disabled** (`P61_PRE_MIDNIGHT_STORAGE_HYGIENE_ENABLED = False`). It must not be promoted to production or merged into baseline.

---

## 2. Downgrading Unsupported Claims to Hypotheses

P6.1-C-R corrected several overbroad narrative claims made in previous drafts:
1. *Claim: "Intraday worker deposits are permanently unviable due to 30+ step transit costs."* $\to$ **REFUTED**. Under actual 10×10 geometry, maximum round-trip distance is 16 steps, and average distance is 4 steps. Opportunistic deposits (0 extra steps) and end-of-day deposits (0 return steps) are highly viable.
2. *Claim: "Discards are structurally unavoidable."* $\to$ **DOWNGRADED TO HYPOTHESIS**. Discards were unavoidable *under P6.1's market-only policy*, but can be prevented if workers deposit high-value goods before midnight.
3. *Claim: "Feed-buffer preservation has an independent positive compounding effect."* $\to$ **VALIDATED AS NARROW ARBITRAGE (+$17.69/game)**. Retaining wheat on-farm avoids purchasing retail feed wheat from the store, but does not compound exponentially.

---

## 3. Comparison of Candidate Next Experiments for P6.2

| Candidate Experiment | Mechanism & Evidence | Expected Net Benefit | Recommendation |
| :--- | :--- | :---: | :---: |
| **Candidate A: Opportunistic Near-Shed Deposit-and-Sell** | Workers adjacent to shed or in inner core deposit high-value goods (Melon, Strawberry, Milk, Wool) for same-turn market sale; workers at H22 deposit before midnight despawn. Supported by committed `MarketBrain` deposit logic. | **High (+$1,500 to +$3,000/game)** | **SELECTED (RECOMMENDED)** |
| **Candidate B: Independent Wheat-Reserve Optimization** | Isolate the 48-unit feed wheat buffer into a standalone policy without storage hygiene selling. | **Low (+$15 to +$30/game)** | **REJECTED (Too Narrow)** |
| **Candidate C: Market Timing / Price Protection Against FPA** | Prevent uncoordinated selling that depresses town market prices against competing bots like FPA. | **Moderate (+$500 to +$1,000/game)** | **SECONDARY FOLLOW-UP** |
| **Candidate D: No Further Operational Intervention** | Abandon storage and inventory optimization. | **$0.00** | **REJECTED (Viable opportunities exist)** |

### Final P6.2 Recommendation:
**Proceed to Candidate A: Opportunistic Near-Shed Deposit-and-Sell**.
Focus exclusively on allowing workers carrying high-value produce who are adjacent or near shed access (`dist <= 2` tiles, or at Hour 22 end-of-day) to execute `PLACE` into the shed, unlocking same-turn market sale.
