# Kaggriculture P5.1-C — Opponent Interaction & Market Competition Analysis

## 1. Executive Summary

This report evaluates how opponent behaviors interacted with the P5.1 Two-Cycle Carrot Rotation across all 5 benchmark opponents and both player seats (100 matched pairs, 200 live games).

### Key Takeaways:
1. **Universal Regression Across All Opponents**:
   - The Treatment produced a **negative mean paired delta against every single opponent archetype**:
     - `pure_wheat_rush`: **−$242.50 / game**
     - `pass`: **−$253.05 / game**
     - `melon_sniper`: **−$787.05 / game**
     - `cow_milk_engine`: **−$1,649.35 / game**
     - `full_production_agent`: **−$2,171.45 / game**
2. **Deficit Persists Against Zero-Action Opponent (`pass`)**:
   - Even when playing against `pass` (where the opponent submits zero actions, buys zero goods, sells zero goods, and never triggers town shop demand), Treatment still regressed by **−$253.05 / game**.
   - This empirically proves that the failure of P5.1 is an **internal systemic flaw** in the agent's resource allocation and shed logistics, not an artifact of market crowding or opponent interference.
3. **Severe Amplification Against Livestock Competitors**:
   - The deficit worsened drastically against opponents that also run livestock (`cow_milk_engine` −$1,649.35; `full_production_agent` −$2,171.45).
   - When opponents compete for town market wheat, market feed prices rise, dramatically amplifying the financial penalty of Treatment's forced feed wheat purchases (up to **−$755.20 / game** in feed purchases alone).

---

## 2. Cross-Opponent Performance Table

The table below presents the 100-pair matched results broken down by opponent archetype (20 games / 10 pairs each):

| Opponent Archetype | Control Mean ($) | Treatment Mean ($) | Paired Delta ($\Delta$) | Carrot Rev ($\Delta$) | Wheat Rev ($\Delta$) | Feed Purchases ($\Delta$) | Milk Rev ($\Delta$) | Wool Rev ($\Delta$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`pass`** | $102,156.55 | $101,903.50 | **−$253.05** | +$1,286.75 | −$1,111.45 | −$489.20 | −$814.05 | −$135.60 |
| **`pure_wheat_rush`** | $101,313.35 | $101,070.85 | **−$242.50** | +$1,258.05 | −$243.40 | −$540.40 | +$427.55 | −$797.20 |
| **`melon_sniper`** | $103,280.75 | $102,493.70 | **−$787.05** | +$1,734.10 | −$1,161.05 | −$467.50 | −$159.60 | −$573.45 |
| **`cow_milk_engine`** | $99,161.85 | $97,512.50 | **−$1,649.35** | +$1,933.35 | −$1,429.70 | −$547.10 | −$912.20 | −$537.00 |
| **`full_production_agent`** | $105,588.05 | $103,416.60 | **−$2,171.45** | +$1,369.55 | −$711.55 | −$755.20 | −$564.60 | −$685.00 |
| **PANEL AVERAGE** | **$102,300.11** | **$101,279.43** | **−$1,020.68** | **+$1,516.36** | **−$931.43** | **−$559.88** | **−$404.58** | **−$545.65** |

---

## 3. Analysis of Specific Opponent Dynamics

### 3.1 The `pass` Benchmark: Isolating Internal Mechanics
Against `pass`, the town market is completely uncontested. Every town shop that unlocks consumes only our goods. The market price curve is driven purely by our own supply.
- Even under these ideal, noise-free conditions, replacing wheat with carrots lost **−$1,111.45 in wheat revenue** and cost **−$489.20 in feed purchases**, while milk revenue plummeted **−$814.05**.
- This definitively rules out:
  - Adversarial price depression
  - Stolen shop capacity
  - Order priority race conditions
  - Opponent land interference

### 3.2 The `cow_milk_engine` Benchmark: Feed Market Squeeze
`cow_milk_engine` aggressively buys wheat to feed its own large dairy herd.
- When Treatment's local farm produced 41.84 fewer units of wheat, Treatment entered a market where wheat supply was already being actively drained by the opponent.
- Wheat prices surged, forcing Treatment to pay higher spot prices for feed wheat.
- Concurrently, because worker time was diverted into carrot maintenance, Treatment's cows missed crucial care and feed cycles, causing a **−$912.20 milk collapse**.

### 3.3 The `full_production_agent` Benchmark: Multi-Enterprise Friction
`full_production_agent` competes across multiple commodity markets.
- In this matchup, Treatment suffered its worst performance: **−$2,171.45 / game**.
- Treatment spent **−$755.20** on feed purchases and lost **−$1,249.60** across milk and wool.
- The high operational complexity of competing on all fronts punished the rigidity and transit overhead of the two-cycle carrot routine.

---

## 4. Seat Invariance Audit

The panel included an exact 50/50 seat balance (50 pairs as Seat 0 / Player 1, 50 pairs as Seat 1 / Player 2):
- **Seat 0 Mean Delta**: **−$1,104.12 / game**
- **Seat 1 Mean Delta**: **−$937.24 / game**
- The negative delta was consistent across both player positions. First-mover advantage in market order execution did not shield Treatment from regression.
