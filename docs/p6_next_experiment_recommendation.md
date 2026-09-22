# P6 Next Experiment Recommendation: P7 Storage Hygiene & Endgame Harmonization

## 1. Executive Summary & Epistemic Justification

The P6 Baseline System Bottleneck Audit demonstrated with mathematical closure ($\epsilon = 0.000000$) that the production baseline loses:
- **$6,026.53 / game** in shed overflow discards (Strawberries $2,267, Wool $1,047, Milk $1,014).
- **$1,456.30 / game** in unharvested mature products at season end.
- **450+ units of fake wheat churn** on Day 28, generating 136 artificial stockout events.

Crucially, **none of these losses require altering crop rotation schedules, buying new quadrants, or changing herd sizing**.
The failure of P5.1 proved that attempting crop rotations while the underlying storage and feed ledgers are unstable causes severe systemic collapse (-$1,020/game).

Therefore, the next experiment must be:
$$\mathbf{P7: \text{ Storage Hygiene \& Endgame Liquidation Harmonization}}$$

```
                       P7 CAUSAL RECOVERY ARCHITECTURE
  ┌────────────────────────────────────────────────────────────────────────┐
  │ 1. Pre-Midnight Shed Headroom Protection (Hours 20–22):                 │
  │    Liquidate excess fertilizer & surplus wheat when shed > 60 units.   │
  │    EXPECTED RECOVERY: +$3,500.00 – $4,500.00 / game                     │
  ├────────────────────────────────────────────────────────────────────────┤
  │ 2. Day 28–29 Feed Liquidation Harmonization:                           │
  │    Enforce unidirectional wheat orders; forbid simultaneous BUY/SELL;   │
  │    delay feed wheat dump until Day 29 Hour 18.                         │
  │    EXPECTED RECOVERY: +$1,000.00 – $2,000.00 / game                     │
  ├────────────────────────────────────────────────────────────────────────┤
  │ 3. Day 29 Endgame Harvest Sweeper:                                     │
  │    Extend pasture and high-value crop harvesting to Day 29 Hour 22.    │
  │    EXPECTED RECOVERY: +$800.00 – $1,200.00 / game                      │
  ├────────────────────────────────────────────────────────────────────────┤
  │ TOTAL INFERRED VALUE: +$5,300.00 to +$7,700.00 / game                   │
  │ TARGET FINAL CASH:   ~$106,300.00 to ~$108,700.00 / game               │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Hypothesis & Mechanistic Specification

### Hypothesis P7.1 (Shed Headroom Preservation)
> *By enforcing a pre-midnight shed flush at Hour 21 (selling down fertilizer and surplus wheat whenever shed occupancy exceeds 60 units), midnight discard events will drop by $\ge 80\%$, recovering at least +\$3,500/game in preserved high-value strawberries, wool, and milk without causing downstream inventory starvation.*

### Hypothesis P7.2 (Day 28 Desynchronization Fix)
> *By enforcing strict order exclusivity (if `SELL WHEAT` is active, suppress `BUY WHEAT` in the same hour) and reserving exact Day 29 feed requirements before liquidating remaining grain, the 450-unit wheat churn on Day 28 will drop to zero, completely eliminating the 136 stockout events and freeing 40+ market transaction slots.*

### Hypothesis P7.3 (Final Day Asset Harvesting)
> *By overriding the idle/pass behavior during Day 29 Hours 16–22 to dispatch workers to collect all mature in-pasture milk and wool, unharvested asset loss will decrease from \$1,456/game to < \$300/game.*

---

## 3. Implementation Blueprint for P7

1. **Module: `agent/market/order_builder.py`**:
   - Add invariant check: If any `SELL WHEAT` order is generated, strictly assert that `intents["buy_wheat"] = 0`.
   - Implement `Shed Headroom Gate`: If `ctx["hour"] in (20, 21, 22)` and `current_shed_load > 60`:
     - Force-queue `SELL FERTILIZER` and `SELL WHEAT` up to available market slots.

2. **Module: `agent/strategy/endgame_liquidator.py`**:
   - Restrict wheat liquidation:
     ```python
     # Retain strictly: remaining_animals * remaining_days feed units
     required_feed_wheat = animals_count * max(0, 30 - day)
     liquidatable_wheat = max(0, shed_wheat - required_feed_wheat)
     ```
   - Only dump `liquidatable_wheat`, never the survival feed envelope.

3. **Module: `agent/execution/task_scheduler.py`**:
   - On Day 29 Hours 18–22, inject high-priority `HARVEST` tasks for all pasture coordinates with `yield_units > 0`.

---

## 4. Experimental Design & Success Criteria

- **Panel**: 100 matched pairs (same 10 discovery seeds `96,401–96,410` $\times$ 5 opponents $\times$ 2 seats).
- **Control**: Baseline commit `536f1e7` ($101,035.79 mean cash).
- **Treatment**: Baseline + P7 Storage Hygiene & Harmonization.
- **Go / No-Go Decision Gate**:
  - **Go**: Mean paired cash delta $\ge +\$3,500.00 / \text{game}$ with $p < 0.01$ and zero increase in animal escapes.
  - **Iterate**: Mean paired delta between $+\$1,000$ and $+\$3,500$.
  - **No-Go**: Mean paired delta $< +\$1,000$ or increased stockout starvation.
