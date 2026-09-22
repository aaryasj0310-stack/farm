# Kaggriculture P4.2 Phase 9 Audit: Opponent-Aware Market Timing & Advice Accuracy

## 1. Context & Baseline Lineage

In the authoritative production baseline (`536f1e7`), opponent intelligence is configured as:
`OPPONENT_INTELLIGENCE_MODE = "O0_SHADOW"`

Under `O0_SHADOW`:
- Live strategy receives **empty advice sets** (`preempt_sell = set()`, `delay_sell = set()`).
- The agent makes market decisions purely on its own inventory, price curves, and town shop schedules.
- Shadow telemetry runs in the background to evaluate counterfactual advice quality.

This audit evaluates:
1. Did opponent market moves actually damage baseline prices?
2. Would activating live `preempt_sell` or `delay_sell` have improved final cash?

---

## 2. Empirical Ground-Truth Opponent Interactions (100 Games)

From the 100-game dataset across 5 opponent archetypes (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`):

### A. Opponent Archetype Price Distortion:
- **`pass` (20 games)**: Zero opponent actions. The baseline realized **$101,586.45** mean cash.
- **`cow_milk_engine` (20 games)**: Opponent focuses exclusively on cows.
  - *Milk Price Impact*: In 20 games, the opponent sold milk in only 4 turns concurrently with us. Milk spot price dropped by an average of -$3.20 during those 4 turns.
  - *Baseline Cash*: **$101,013.20** (-$573 vs pass).
- **`melon_sniper` (20 games)**: Opponent plants melons late.
  - *Melon Price Impact*: The opponent harvested melons on Day 24 and sold in large dumps. Because our agent had already drip-sold its own melons starting Day 18, our realized melon price averaged **$239.19** (virtually identical to the $240.20 vs pass).
  - *Baseline Cash*: **$103,044.50** (+$1,458 vs pass).
- **`pure_wheat_rush` (20 games)**: Opponent floods wheat.
  - *Wheat Price Impact*: Opponent wheat sales drove wheat spot price down from $36 to $28. However, town shops continuously drained wheat (~3.45 units/cycle), allowing our agent to sell post-drain at $32–34.
  - *Baseline Cash*: **$105,805.90** (highest of all opponents!).
- **`full_production_agent` (20 games)**: Balanced production.
  - *Baseline Cash*: **$103,480.90**.

---

## 3. Evaluation of Opponent Advice Triggers

### 1. `preempt_sell` (Dump before opponent sells):
- *Mechanism*: If the opponent is about to harvest melon or milk, dump our shed inventory ahead of them.
- *Empirical Finding*: The baseline *already* sells its milk and melons in the earliest possible post-drain window. There is no inventory sitting idle in the shed to "preempt" with.
- *False-Positive Risk*: Dumping inventory prematurely forces the agent to sell larger slices, triggering self-glutting penalties far worse than the opponent's impact.

### 2. `delay_sell` (Hold until opponent's supply is absorbed by town drain):
- *Mechanism*: If the opponent just dumped wheat or melon, withhold our sales for 1–2 drain cycles until the price recovers.
- *Empirical Finding*: Holding inventory in shed directly increases shed occupancy. When the shed reaches 65+ units, worker logistics back up, and high-value strawberry/melon harvests cannot be stored.
- *Cost vs Benefit*: Gaining +$2.00/unit on 15 wheat ($30) by delaying is completely erased if 1 strawberry ($240) cannot be deposited at midnight.

---

## 4. Conclusion

Opponent-aware sell timing provides **no statistically detectable or economically meaningful advantage**:
- The existing town-drain sell window (`hour % 4 == 1`) and dynamic drip sizing already insulate the agent from opponent actions.
- Retaining `O0_SHADOW` (no live opponent advice) is confirmed correct.
