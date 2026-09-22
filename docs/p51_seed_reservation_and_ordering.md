# Kaggriculture P5.1 — Seed Reservation & Market Ordering Architecture

## The 10-Order Market Slot Bottleneck

In the Kaggle Agriculture engine, `MAX_MARKET_ORDERS = 10`.
Every morning at Hour 0, the production agent typically compiles:
- **3 to 4 HIRE orders** (high morning priority to expand workforce)
- **6 to 8 SELL orders** (shed soft-cap relief and high-value product realization: Milk, Wool, Strawberry, Fertilizer)

This immediately consumes 9 to 12 potential market slots. 
In the P5.0-R provisional replay, Cycle 2 pre-ordered seeds were simply appended to `plan.intents["buy_seed"]["CARROT"]`. 
However, in `central_planner.py`:
```python
planned_today = sum(1 for pos, c in macro_plan.plant_queue if c == crop)
needed_today = max(0, planned_today - seeds_on_hand)
if needed_today > 0:
    priority_class = P1_URGENT  # urgency 1.0
else:
    priority_class = P2_STRATEGIC  # urgency 0.5
```
Because Cycle 1 carrots were still in the ground at Hour 0, `plant_queue` had 0 carrots. Consequently:
- `planned_today = 0`
- `needed_today = 0`
- Priority assigned: `P2_STRATEGIC` (urgency 0.50).

Meanwhile, ordinary shed soft-cap relief sales were assigned `P2_STRATEGIC` with **urgency 0.60**.
Under `central_planner` sorting, urgency 0.60 ranks ahead of urgency 0.50. The 7 sell orders + 3 hire orders filled all 10 slots, and `BUY_SEED CARROT` was **completely dropped**!

---

## P5.1 Solution: Replant-Aware Priority Promotion

Under `P51_T1_TWO_CYCLE_CARROT_ENABLED`:
1. At Hour 0 of Days 24–26, `MacroPlanner` queries `TwoCycleRotationManager.get_c2_maturing_today_count(day)`.
2. For each maturing tile, 1 CARROT seed is requested in `buy_seed["CARROT"]`, and `plan.p51_carrot_replant_today` is incremented.
3. In `central_planner.py` (`_classify_purchase`), `planned_today` for CARROT includes `p51_carrot_replant_today`:
   ```python
   try:
       from config import get_p51_t1_two_cycle_carrot_enabled
       if get_p51_t1_two_cycle_carrot_enabled() and crop == "CARROT":
           p51_replant = getattr(macro_plan, "p51_carrot_replant_today", 0)
           planned_today += p51_replant
   except Exception:
       pass
   ```
4. This yields `needed_today = maturing_today - seeds_on_hand > 0`, immediately promoting the purchase order to:
   - **Priority Class**: `P1_URGENT`
   - **Urgency**: `1.0`
5. At Hour 0, `purchases_first = True`. `P1_URGENT` purchase orders are evaluated before any `P2_STRATEGIC` sell orders, guaranteeing that `BUY_SEED CARROT` is placed in the top 10 market slots.
6. The carrot seeds arrive in private inventory at Hour 1, ready for immediate planting when Cycle 1 is harvested intraday.
