# Kaggriculture P3.2 — Animal Care Engine Semantics Audit

## 1. Ground Truth Engine Implementation

From `kaggle_environments/envs/kaggriculture/kaggriculture.py`:

```python
ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}
```

### The CARE Action (`op == "CARE"`)
- Handled at `kaggriculture.py:524-530`:
  ```python
  if op == "CARE":
      if not (isinstance(tile, dict) and "animal" in tile):
          return
      if tile["cared_today"]:
          return
      tile["cared_today"] = True
      return
  ```
- **Rule 1**: `CARE` can only execute **once per animal per day**. Subsequent care actions on the same tile are dropped as invalid/no-op.
- **Rule 2**: `CARE` does **not** immediately produce product into inventory or onto the tile. It merely sets the boolean flag `tile["cared_today"] = True`.

---

## 2. End-of-Day Animal Refresh (`_daily_refresh_animals`)

At the conclusion of Hour 23 of `current_day` (where `next_day = current_day + 1`):

```python
def _daily_refresh_animals(farm, day):
    ...
    next_day = day + 1
    ...
    # Step A: Feed & Starvation check
    if tile["fed_today"]:
        tile["consecutive_unfed"] = 0
    else:
        tile["consecutive_unfed"] += 1
    if tile["consecutive_unfed"] >= 2:
        farm["tiles"][y][x] = {"kind": ANIMALS[tile["animal"]]["structure"]}
        continue

    # Step B: Scheduled Production check
    a = ANIMALS[tile["animal"]]
    days_since_first = next_day - tile["placed_day"] - a["first_yield_day"]
    if days_since_first >= 0 and days_since_first % a["interval"] == 0:
        base = 1
        bonus = tile.pop("pending_care_bonus", 0) if tile["fed_today"] else 0
        tile["yield_units"] = min(a["max_held"], tile["yield_units"] + base + bonus)
        tile["pending_care_bonus"] = 0

    # Step C: Care Bonus Accumulation
    if tile["cared_today"] and tile["fed_today"]:
        tile["pending_care_bonus"] = tile.get("pending_care_bonus", 0) + 1

    tile["fertilizer_available"] = True
    tile["fed_today"] = False
    tile["cared_today"] = False
```

---

## 3. The 6 Critical Structural Invariants of Animal Care

### Invariant 1: Feed Dependency for Care Bonus Banking
`tile["pending_care_bonus"]` is incremented **only if both** `tile["cared_today"]` AND `tile["fed_today"]` are True (Line 829).
> [!IMPORTANT]
> If an animal is cared for but **not fed** today, the CARE action is **completely wasted** ($0 bonus banked).

### Invariant 2: Feed Dependency on Production Day
When a production event triggers on `next_day`, the banked bonus is applied **only if** `tile["fed_today"]` is True on the production day (Line 826).
> [!WARNING]
> If an animal was cared for on prior days, but is **unfed on the production day**, the entire banked care bonus is wiped to 0 without creating any yield! Base yield of 1 is still granted, but the banked care multipliers vanish.

### Invariant 3: The Execution Order Paradox (Pre-Production vs Post-Production)
In `_daily_refresh_animals`:
1. Line 823–828: Production executes **first** using `tile.pop("pending_care_bonus", 0)`.
2. Line 829–830: Today's care bonus is banked **second** into `tile["pending_care_bonus"]`.
> [!NOTE]
> On the day immediately preceding a production event (e.g. Day 7 for a Day 8 Cow production), `pending_care_bonus` was accumulated during the animal's growth or prior cycle. Today's care adds +1 for the **subsequent** cycle, NOT the immediate morning's production.

### Invariant 4: Maximum Held Product Capacity (`max_held = 6`)
Tile product accumulation is strictly capped at `max_held = 6` (Cows and Sheep).
$$\text{tile["yield\_units"]} = \min(6, \text{existing} + \text{base} + \text{bonus})$$
If a Cow already holds 4 Milk, and triggers a production event with base 1 + bonus 2 = 3:
$\min(6, 4 + 3) = 6$. The 7th unit is **permanently destroyed**.
If an animal already holds 6 units, any care bonus realized before a `HARVEST` action produces **$0 incremental value**.

### Invariant 5: Production Cycles & Bonus Caps
- **Cow**: `interval = 2`. Between successive production events, there are exactly 2 care opportunities.
  - Maximum banked bonus per cycle = 2.
  - Maximum output per cycle = 1 (base) + 2 (care) = 3 Milk ($480).
- **Sheep**: `interval = 3`. Between successive production events, there are exactly 3 care opportunities.
  - Maximum banked bonus per cycle = 3.
  - Maximum output per cycle = 1 (base) + 3 (care) = 4 Wool ($800).
- **Goose**: `interval = 1`. In baseline production config, `CARE_GEESE = False` (`want_care = t.animal != "GOOSE"`). Goose care is intentionally disabled because $50 egg value does not justify labor.

### Invariant 6: Terminal Season Cutoff (Day 29 / 30)
The competition season ends at Day 29 Hour 23. Any production occurring at Day 30 refresh is unharvestable.
- The **last harvestable production day** is **Day 29**.
- Any CARE performed on an animal whose next production day $\ge 30$ has **exact marginal value = $0.00**.
- Specifically: **No animal CARE on Day 29 can ever produce harvestable product.**
