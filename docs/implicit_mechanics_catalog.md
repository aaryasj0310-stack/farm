# Kaggriculture: Exhaustive Implicit Mechanics Catalog

> **Purpose**: Every non-obvious, implicit, or edge-case mechanic in the game rules that can be exploited for advantage over a naive player. Each entry cites the exact rule, the derived mechanic, and the tactical application.

---

## Category 1: Planting & Watering Edge Cases

### 1.1 The Day-0 Planting Death Trap
**Rule**: *"A new seed starts with `consecutive_unwatered = 1` — the planting day itself counts as the first missed day."*

**Mechanic**: The moment you PLANT, the counter is already at 1. If you don't WATER on the same day, end-of-day bumps it to 2 → instant weed. There is **no grace period**.

**Exploit**: You MUST water on planting day. This means planting and watering the same tile costs 2 turns (PLANT + WATER), not 1. Plan your action budget accordingly. A farmer standing on a tile can plant turn N, water turn N+1 — but this also means **you cannot plant-and-walk-away** on the last turn of a day.

**Anti-opponent**: If you see your opponent plant late in the day (turn 20-23), check if they have time to water. If they planted on turn 23 and can't water, that seed dies tonight. You can infer wasted resources.

---

### 1.2 The Skip-Day Watering Survival Window
**Rule**: *"Plants must be watered/fed a minimum of every other day... two consecutive days [unwatered] → weed."*

**Mechanic**: Once a plant has been watered (counter = 0), it survives one missed day (counter goes to 1), but dies on two consecutive misses (counter hits 2). This means you can water **every other day** and the plant survives.

**Exploit**: On action-constrained days, you can safely skip watering half your farm. Water group A today, group B tomorrow. This cuts watering labor by 50%. 

**Cost**: You forfeit the bonus yield for one-time crops during skipped days in their bonus window. This is acceptable for mature crops past their bonus window, or for keeping crops alive during action-capped late-game.

---

### 1.3 The Simultaneous Planting Conflict
**Rule**: *"If you try to plant too many in a specific turn, none are planted — ie if you have 1 melon seed, but two units do the PLANT MELON command."*

**Mechanic**: If farmer + hand(s) both issue PLANT for the same seed type on the same turn, and you don't have enough seeds, **ALL** planting actions for that seed type fail — not just the extras. It's all-or-nothing.

**Exploit**: Never assign PLANT of the same crop type to multiple units on the same turn unless you're certain you have enough seeds. If you have 3 wheat seeds, you can safely assign 3 units to PLANT WHEAT simultaneously, but not 4.

---

### 1.4 Water Is a Daily No-Op After First
**Rule**: *"This only needs to be done once per day, and subsequent waterings on the same day are a no-op."*

**Mechanic**: You can safely issue WATER commands without checking `watered_today` — redundant waterings are harmless no-ops that consume the action but have no negative side effect.

**Exploit**: In simple agent designs, you can blanket-WATER every tile your farmer walks over without worrying about double-watering. The action is wasted, but there's no penalty. This simplifies pathfinding logic significantly.

---

### 1.5 Bonus Window Start Formula
**Rule**: *"Starting at half the plant's `max_yield_day` rounded up, watering during the bonus window will add one unit per day."*

**Mechanic**: The bonus window start is `ceil(max_yield_day / 2)`:
- Wheat: `ceil(4/2)` = Day 2
- Carrot: `ceil(3/2)` = Day 2
- Melon: bonus window is ages 6–12 (explicitly stated)

**Exploit**: You gain nothing from watering before the bonus window except keeping the plant alive. For action-economy, you could skip-day water before the bonus window opens (keeping the plant alive at half the labor), then switch to daily watering once the bonus window starts.

---

## Category 2: Harvest & Decay Timing Exploits

### 2.1 Decay Happens Every Other TURN, Not Day
**Rule**: *"Once a plant has hit its maximum lifespan, the total yield available on the plant will reduce by 1 every other turn until it hits 0."*

**Mechanic**: Decay is per-**turn**, not per-day. With 24 turns/day, a plant with 6 yield_units decays to 0 in just 12 turns (half a day). You have a **very narrow window** to harvest decaying crops.

**Exploit**: One-time crops reach max lifespan one day after `max_yield_day`. For wheat (max_yield_day=4), decay starts on day 5. If you don't harvest by mid-day 5, your yield is halved. By end of day 5, it's a weed. **Always harvest on max_yield_day or the day after, early in the day.**

**Math**:
- Wheat: 4 yield units (unfert) → decays turn-by-turn from day 5, turn 0. Gone by day 5, turn 8.
- Melon: 6 yield units → decays from day 11, turn 0. Gone by day 11, turn 12.

---

### 2.2 Ongoing Crops Have a Hidden Lifespan
**Rule**: *"Tomato and Strawberry are ongoing but not indefinite: production is capped at 4 scheduled yields."* *"Ongoing crops start decay one day after their cumulative production count reaches max_yield."*

**Mechanic**: Tomato produces at ages 8, 9, 10, 11 (4 yields). After age 11, decay starts on day 12. Strawberry produces at ages 10, 12, 14, 16 (4 yields, every other day). After age 16, decay starts on day 17.

**Exploit**: Both ongoing crops eventually become weeds. This means they are **not** indefinite like animals. A tomato tile is occupied for ~12 days before dying. A strawberry tile for ~17 days. Plan replanting schedules accordingly.

**Critical**: The decay timer starts based on **cumulative production count**, not whether you harvested. If you forget to harvest a tomato for 4 days, it produces 4 times internally, hits its cap, and starts decaying — with all 4 units still sitting on the tile potentially unharvested.

---

### 2.3 Harvest Always Yields At Least 1
**Rule**: *"Each harvest action will yield at least one unit of the crop."*

**Mechanic**: Even a completely neglected one-time crop (planted and never watered during the bonus window) still yields 1 unit when harvested at its first yield day. The minimum harvest is 1, never 0.

**Exploit**: In a pinch, you can plant-and-forget cheap crops (wheat at $10 seed) and harvest 1 unit ($25 base) for a guaranteed $15 profit per tile, even with zero bonus watering. This is the floor ROI.

---

### 2.4 The $1 Floor Inventory Freeze
**Rule**: *"If the sell price has been driven down to $1 (the price floor), the unit is still purchased but is not added to market inventory."*

**Mechanic**: When you sell at the $1 floor, the market **does not gain inventory**. This means continued selling at $1 does NOT further depress prices. The inventory stays frozen.

**Exploit**: If you've crashed a premium product to $1, town consumption still drains the frozen inventory, eventually pulling the price back up. You can crash a product deliberately, then wait for town to drain it, and sell again at a higher price later. This is a form of **market cycling**.

**Anti-opponent**: If your opponent is bulk-selling melons and crashing to $1, their sales don't add to inventory. Once they stop, town consumption raises the price back up. You can then sell your melons at the recovered price.

---

## Category 3: Animal Lifecycle Mechanics

### 3.1 Animal Grace Period (vs. Plant Death Trap)
**Rule**: *"A newly placed animal starts with `consecutive_unfed = 0`, so it survives its first day unfed."*

**Mechanic**: Animals start at 0 unfed counter. Plants start at 1 unwatered counter. **Animals are more forgiving on placement day.** You can place an animal and not feed it until the next day without it escaping.

**Exploit**: You can place an animal late in the day without worrying about feeding. The animal survives overnight. Feed it first thing the next morning.

---

### 3.2 CARE-Banking Yield Multiplication
**Rule**: *"If the animal was both fed AND cared for that day, `pending_care_bonus` increments by 1."* *"On a scheduled production day, if the animal is fed, the entire banked bonus is added to that production's yield."*

**Mechanic**: The CARE bonus accumulates over every fed+cared day between productions, and is paid out in full on the next production.

**Exact Math by Animal**:
- **Goose** (produces daily): You can CARE for 0 days between productions. Max bonus per yield = 0. CARE is essentially useless for geese — they produce every day, so there's never time to bank a bonus. **Skip CARE on geese entirely.**
- **Cow** (produces every 2 days): You can CARE on 1 off-day between productions. Max bonus = 1. Yield = 1 + 1 = 2 milk per production.
- **Sheep** (produces every 3 days): You can CARE on 2 off-days. Max bonus = 2. Yield = 1 + 2 = 3 wool per production.

**Exploit**: CARE is most valuable for sheep (triples output) and cows (doubles output), but **completely useless for geese**. Don't waste actions caring for geese.

---

### 3.3 The max_held Cap Trap
**Rule**: *"`pending_care_bonus` is capped indirectly by the per-animal `max_held` cap on `yield_units`."*

**Mechanic**: Goose max_held = 4, Cow max_held = 6, Sheep max_held = 6. If `yield_units` is already at max_held, new production doesn't add more. The care bonus is wasted if it would push yield_units past the cap.

**Exploit**: **Harvest animals before they hit max_held.** For a goose (daily production, max_held 4), if you don't harvest for 4 days, production on day 5 is wasted. For a cow with care bonus, if yield_units is already 5 and production adds 2 (1 base + 1 care), it caps at 6 — you lose 1 unit.

**Critical rule**: Harvest frequently from animals, especially geese.

---

### 3.4 Unfed Production Day — Base Still Produced, Bonus Lost
**Rule**: *"If the animal is unfed on the production day, the base 1 unit is still produced, but the banked bonus is not applied and the bank resets to 0."*

**Mechanic**: Missing a single feed on a production day doesn't kill your animal (it needs 2 consecutive misses to escape), but it **destroys all accumulated CARE bonus**. The base 1 unit still produces, but days of CARE-banking are wasted.

**Exploit**: If you've been caring for a cow for 10 days to bank a massive bonus, missing the feed on production day wipes the entire bank. **Feeding on production days is the single highest-priority action for animals with care bonuses.**

---

### 3.5 Fertilizer Is Non-Accumulating
**Rule**: *"Uncollected fertilizer does not accumulate, so an animal left alone for five days still yields 1 unit."*

**Mechanic**: Each animal has exactly 1 fertilizer available at any time (set at end-of-day). If you don't collect it, the next day's fertilizer replaces it — you don't get 2.

**Exploit**: You must COLLECT_FERTILIZER every day per animal to maximize fertilizer income. Missing a day = permanent loss of 1 fertilizer ($100 at base price). This is a hidden "tax" on every unfed or unvisited animal.

---

### 3.6 Animals Produce Fertilizer Regardless of Care
**Rule**: *"Every surviving animal makes 1 [fertilizer] available at the end of each day, whether or not it was fed or cared for."*

**Mechanic**: Even starving, uncared-for animals produce fertilizer. As long as they haven't escaped (consecutive_unfed < 2), they generate 1 fertilizer/day.

**Exploit**: In the absolute worst case, you can intentionally neglect an animal for 1 day (it won't escape), skip all other actions, and just COLLECT_FERTILIZER for $100/day of free income. This is the animal's guaranteed minimum economic output.

---

## Category 4: Fertilizer Optimization

### 4.1 Fertilizer Only Applies on Watered Days
**Rule**: *"The bonus only applies on days the plant is also watered (basic needs first)."*

**Mechanic**: If you fertilize but don't water, the fertilizer day is consumed but the bonus is **wasted**. You paid for 3 days of fertilizer but got 0 benefit on unwatered days.

**Exploit**: ALWAYS water before or on the same day you fertilize. Never skip a watering day during the 3-day fertilizer window. The fertilizer timer counts down regardless of watering.

---

### 4.2 Fertilizer Timing for One-Time Crops
**Rule**: Fertilizer doubles the per-day yield bonus (+2 instead of +1 per watered day in the bonus window).

**Optimal Timing Math**:
- **Wheat** (bonus window days 2-4, 3 days): Fertilize on Day 1 (applies days 2, 3, 4). You get +2/day for all 3 bonus days = 6 extra units. But max yield is 6 (fertilized), base 1 → total 7 capped at 6. **Fertilize day 1, covers entire window.**
- **Carrot** (bonus window days 2-3, 2 days): Fertilize day 1 → covers days 2-3 (+2×2=4 extra). Max yield 4. Base 1 + 4 = 5 capped at 4. **Fertilize day 1.**
- **Melon** (bonus window ages 6-12): Fertilize day 5 → covers days 6, 7, 8 (+2×3=6 extra). Base 1 + 6 = 7 capped at 6. **Reach cap on day 8 instead of 10. Save 2 days.**

**Exploit**: For wheat and carrot, one fertilizer maximizes yield. For melon, one fertilizer shaves 2 days off the cycle, freeing the tile for replanting sooner.

---

### 4.3 Ongoing Crop Fertilizer — Day-of-Production Only
**Rule**: *"The base yield is 1 per scheduled production. If the plant is fertilized AND watered that day, yield is doubled to 2."*

**Mechanic**: For tomato and strawberry, fertilizer only matters on the **exact day of production**. Fertilizing the day before or after is wasted.

**Exploit**: 
- Tomato produces days 8, 9, 10, 11. Fertilize on day 7 → covers days 8, 9, 10 (3 of 4 productions doubled).
- Strawberry produces days 10, 12, 14, 16. Fertilize on day 9 → covers days 10, 11, 12. Only 2 of 4 productions doubled (day 10 and 12). Fertilize again on day 13 → covers 14, 15, 16. Gets days 14 and 16.

**Key insight**: Strawberry requires **2 fertilizers** to double all 4 productions. Tomato only needs **1**.

---

## Category 5: Shed & Inventory Tricks

### 5.1 Seeds Have No Shed Cap
**Rule**: *"Seeds live in a separate slot and are never picked up... Limited to 100 items, excluding seeds."*

**Mechanic**: Seeds are completely separate from the 100-item shed cap. You can buy unlimited seeds without worrying about shed overflow.

**Exploit**: On turn 0, buy 50 wheat seeds at $500. They sit in the seed slot, consuming zero shed space. Your shed remains at 0/100 for produce.

---

### 5.2 Seeds Are Globally Available
**Rule**: *"Seeds are automatically available to all Farmers / Farm Hands."*

**Mechanic**: When you BUY_SEED, the seeds are instantly available to ALL your units. The farmer doesn't need to visit the shed to distribute seeds to hands. Any farmer or hand can PLANT immediately.

**Exploit**: Buy seeds via market order and have a hand in a remote quadrant PLANT on the same turn. No pickup or transport needed.

---

### 5.3 The Main Farmer Overnight Carry
**Rule**: *"Farmer and hired farm hands drop their inventory at the end of the day in the shed (if there is room)."*

**Mechanic**: At end-of-day, all inventories dump into the shed. If the shed is full (100 items), the overflow is discarded.

**However**: The main farmer persists between days. If the farmer's inventory is dropped into a full shed, items are lost. But the rule says "if there is room" — if there's no room, does the farmer keep items? This needs verification against the engine, but the rules say "Anything that doesn't fit is discarded — overflow is lost."

**Important clarification**: Both farmer and hand inventories are force-dumped at end-of-day. **You cannot hold items on the farmer overnight.** The farmer's inventory is emptied into the shed, and overflow is discarded. This is a hard constraint.

**Exploit**: Sell items from the farmer's inventory BEFORE end-of-day to avoid hitting the shed cap. Use `PLACE` into the shed during the day only if there's room. Never let the shed hit 100 if you have unsold items on units.

---

### 5.4 DROP vs PLACE for Shed Management
**Rule**: DROP dumps **entire** inventory into shed. PLACE moves up to `n` of a specific item.

**Mechanic**: DROP is all-or-nothing. PLACE is surgical. If your shed has 95 items and the farmer has 10, DROP adds 5 and discards 5. PLACE lets you selectively deposit the 5 most valuable items.

**Exploit**: Never use DROP when the shed is near capacity. Use PLACE to carefully select which items to store and which to keep for immediate selling.

---

### 5.5 Selling Directly From Shed (No Pickup Needed)
**Rule**: Market SELL orders sell from the shed directly. *"Sell N units of a single item to the market."*

**Mechanic**: SELL market orders consume items from the shed. You don't need to PICKUP items from the shed and then sell — the market action accesses the shed directly.

**Exploit**: This is massive for action economy. You can sell items every turn via market orders without the farmer ever visiting the shed. Harvesting → DROP at shed → SELL via market order next turn. The farmer never needs to physically handle the selling.

---

## Category 6: Spatial & Movement Exploits

### 6.1 Locked Tile Passability
**Rule**: *"Locked tiles are passable: a unit may move onto and across unbought quadrants."*

**Mechanic**: You can walk through unbought quadrants as shortcuts. The only restriction is you can't perform tile actions (PLANT, WATER, etc.) on locked tiles.

**Exploit**: Use the locked NE, SW, SE quadrants as pathways to reach the shed from any direction, even before buying them. A farmer in the far NW can cut through the locked NE quadrant to reach the eastern shed-adjacent tile.

---

### 6.2 Shed Access From Locked Tiles
**Rule**: *"The exception is the shed actions PICKUP, DROP, and PLACE-into-shed, which work from any shed-access tile even while that tile is locked."*

**Mechanic**: The four shed-adjacent tiles (4,4), (5,4), (4,5), (5,5) are one in each quadrant. Three of them start locked. **But shed actions work from locked tiles.**

**Exploit**: You don't need to buy NE/SW/SE to access the shed from those sides. A hand spawning at (5,4) in the locked NE quadrant can immediately DROP items into the shed. This saves $7,000 in land purchases for shed access alone.

---

### 6.3 Farm Hand Spawn Prediction
**Rule**: *"A hired hand appears orthogonally adjacent to the shed in a free space following NWSE... Spawn placement ignores whether the tile is locked."*

**Mechanic**: Hands spawn at (4,4), (5,4), (4,5), (5,5) in NW→NE→SW→SE order, preferring empty tiles, then least-occupied tiles.

**Exploit**: Since the main farmer starts at (4,4), the first hand spawns at (5,4) (NE, locked). The second hand at (4,5) (SW, locked). The third at (5,5) (SE, locked). You can predict exactly where each hand will appear and pre-plan their first action. Hands on locked tiles can immediately move to the unlocked NW quadrant (1-2 moves) or perform shed actions directly.

---

### 6.4 Co-Occupation
**Rule**: *"Farmer/Farm Hand CAN occupy the same space."*

**Mechanic**: Multiple units can stack on the same tile. There's no blocking or collision.

**Exploit**: You can have the farmer and 3 hands all stand on the same tile to perform different actions. For example, all 4 units on a single shed-adjacent tile: farmer DROPs, hand 1 PICKUPs, hand 2 PLACEs, hand 3 moves away. No movement conflict overhead.

---

### 6.5 Edge-of-Board Movement No-Op
**Rule**: *"Moves off the edge of the board are no-ops."*

**Mechanic**: Moving NORTH from y=0 or SOUTH from y=9 does nothing. No error, no penalty — just a wasted action.

**Exploit**: Safe to issue movement commands without bounds-checking. But this also means the board edges are dead ends for pathfinding — plan routes to avoid bouncing off walls.

---

## Category 7: Market Microstructure

### 7.1 Concurrent One-at-a-Time Processing
**Rule**: *"Orders are processed concurrently across players, one unit at a time."*

**Mechanic**: If Player A queues `SELL WHEAT 10` and Player B queues `SELL WHEAT 10`, the engine processes: A sells 1 wheat, B sells 1 wheat, then 2 wheat are added to market → price shifts. Repeat. Both players get the **same price** for each round.

**Exploit**: You cannot "undercut" your opponent by selling first within the same turn. You both get the same price per unit. However, if your order is shorter (1 unit vs. 10 units), you finish earlier and your remaining market order slots process your next orders while the opponent is still selling wheat.

---

### 7.2 Market Order Slot Limit (10 Orders/Turn)
**Rule**: *"Each turn you can submit up to `maxMarketOrdersPerTurn` (default 10) market actions; any orders past that limit are silently dropped."*

**Mechanic**: You get exactly 10 market order slots per turn. Excess orders are silently discarded — no error, no feedback.

**Exploit**: 10 slots is a LOT. In a single turn you can: BUY_SEED WHEAT 25, BUY_SEED MELON 5, BUY_ANIMAL GOOSE 2, SELL WHEAT 50, SELL EGG 10, SELL FERTILIZER 5, HIRE, HIRE, HIRE, BUY_LAND. That's 10 orders executing a complex economic plan in one turn.

**Key insight**: A single SELL order can sell N units — it's not 1 order per unit. `SELL WHEAT 50` is 1 order, not 50. So 10 order slots is nearly unlimited for practical purposes.

---

### 7.3 The Buy Price vs Sell Price Asymmetry
**Rule**: *"The buy price is quoted at the post-buy inventory and the sell price is quoted at the pre-sell inventory."*

**Mechanic**: 
- When you SELL, you get the price BEFORE the sale adds to inventory.
- When you BUY_PRODUCT, you pay the price AFTER the purchase removes from inventory (higher price since less inventory).

**Exploit**: An immediate buy-then-sell of the same item nets exactly $0. But if town consumption has drained inventory between your sell and your buy, you can profit from the price difference. **Buy wheat when the market is glutted (cheap), sell when town has consumed and price is elevated.**

---

### 7.4 BUY_PRODUCT Is Severely Restricted
**Rule**: *"Only WHEAT and FERTILIZER can be bought from the market via BUY_PRODUCT."*

**Mechanic**: You can sell any product, but you can only BUY wheat and fertilizer back. Eggs, milk, wool, carrots, tomatoes, strawberries, melons — once sold, they're gone from your inventory.

**Exploit**: This means the only way to get wheat for animal feed without growing it is to BUY_PRODUCT WHEAT from the market. If wheat prices spike (many animals, not enough growers), feeding animals becomes expensive. **Wheat has dual demand: player-sold commodity AND player-consumed feed.** This creates a natural price floor for wheat.

---

### 7.5 Money Runs Out Mid-Order
**Rule**: *"If a player runs out of money mid-order, the order is stopped."*

**Mechanic**: If you queue `BUY_SEED WHEAT 100` but only have $500, the engine buys 50 seeds ($10 each) and then stops. No error — partial fulfillment.

**Exploit**: You can safely queue large orders without worrying about overdraft. The engine handles it gracefully. Queue `BUY_SEED WHEAT 999` and the engine buys as many as you can afford.

---

### 7.6 Town Consumption Happens AFTER Player Actions
**Rule**: Turn processing order: *"2. Player actions → 3. Market actions → 4. Town buy actions."*

**Mechanic**: Your sells/buys process first, THEN town consumption reduces inventory. This means if you sell product, you get the pre-town-consumption price. Town consumption then lowers inventory, raising the price for the NEXT turn.

**Exploit**: The ideal timing is to sell on the turn AFTER town consumption (which raised prices), not on the turn OF town consumption (because town hasn't consumed yet).

**Town consumption frequency**: 
- Town center: every 24 turns (once per day, on the last turn of the day)
- Shops: every 4 turns (6× per day)

**Practical exploit**: Shop consumption happens on turns 0, 4, 8, 12, 16, 20. Sell premium goods on turns 1, 5, 9, 13, 17, 21 — right AFTER shop consumption lowers inventory and raises prices.

---

## Category 8: Turn Processing Order Exploits

### 8.1 Simultaneous Action Processing
**Rule**: *"Player actions — record the actions taken by each player (happening simultaneously)."*

**Mechanic**: Both players' farmer/hand actions happen simultaneously. If both farmers stand on the same tile and both issue HARVEST, both harvest. If both issue WATER on the same tile... wait, they have separate farms. But within your own farm, if farmer and hand are on the same tile, both can act on it in the same turn.

**Exploit**: A farmer and hand on the same crop tile: farmer HARVESTS, hand WATERS (if needed for the next cycle). Two actions on one tile in one turn. Maximizes throughput per tile per turn.

---

### 8.2 Market-Then-Farm Update Ordering
**Rule**: Processing: *"Market actions → ... → Farm update — add new plants/animals to the farm."*

**Mechanic**: When you BUY_SEED, the seed is available to PLANT on the **same turn**. Market orders process before farm state updates.

**Exploit**: On turn 0, you can issue: `market: [["BUY_SEED", "WHEAT", 25]]` and `farmer: ["PLANT", "WHEAT"]`. The seed purchase resolves first, then the plant action uses the purchased seed. **Buy and plant on the same turn.** This saves a full turn of setup.

---

### 8.3 HIRE Resolves Immediately
**Rule**: HIRE is a market order. Market orders process before player actions update.

**Mechanic**: If you HIRE on turn 0, the hand appears immediately and can act on turn 1. But can the hand act on the SAME turn it's hired? Based on the processing order, market actions (including HIRE) resolve, then player actions execute. Since the hand didn't exist when player actions were submitted, it likely **cannot** act on its hiring turn.

**Exploit**: HIRE on the first turn of the day (turn 0 of the day). The hand acts on all remaining 23 turns. HIRE on the last turn (turn 23) means the hand acts on 0 turns before being dismissed at end-of-day. **Always HIRE at the start of the day.**

---

## Category 9: Information Asymmetry

### 9.1 Full Farm Visibility, Hidden Shed
**Rule**: *"Players are unable to see the state of the other's shed, but can see the state of their opponent's farm."*

**Mechanic**: You can see EVERYTHING about the opponent's farm: tiles (crops, ages, watered status, yield_units), farmer/hand positions, money, unlocked quadrants, hires_today. But you CANNOT see their shed contents.

**Exploitable information**:
- `yield_units` on opponent's tiles → know exactly how much they'll harvest
- `watered_today` → know if they're neglecting crops (will die soon)
- `fertilized_until_day` → know if they're investing in premium yields
- `money` → know if they can afford land/animals/seeds
- `hires_today` → know their action capacity for the day
- `farmer` and `hands` positions → predict their movements and which tiles they'll service

---

### 9.2 Market Inventory Inference
**Rule**: Market inventory and prices are shared/visible.

**Mechanic**: You can watch the market inventory change between turns. If market wheat inventory drops by 5 and you didn't buy any, you know the opponent bought 5 wheat (or town consumed it). By tracking town consumption schedules, you can compute exactly what the opponent bought/sold.

**Exploit**: Build a turn-by-turn market ledger. Track `delta_inventory = current_inv - previous_inv`. Subtract known town consumption. The remainder is the opponent's net buy/sell activity. You can reconstruct their entire trading strategy without seeing their shed.

---

### 9.3 Opponent Money Is Visible
**Rule**: `money` is in the public farm dict.

**Mechanic**: You can see the opponent's exact bank balance every turn.

**Exploit**: If the opponent has $0, they can't buy seeds, animals, or land. You can freely expand knowing they can't compete. If they suddenly spend $4,000 (SE quadrant unlock), you know they're expanding and can prepare for increased competition on specific products.

---

## Category 10: Farm Hand Economics

### 10.1 Fibonacci Cost Resets Daily
**Rule**: *"Hire cost is `farmHandCostMult * fib(n)` where n is the number of hires already made today... resets at the start of each day."*

**Mechanic**: The Fibonacci counter resets every day. Yesterday's 5 hires don't make today's first hire more expensive. First two hires are always $1 each.

**Exploit**: **Hire 3-4 hands EVERY day.** Cost: 1+1+2+3 = $7/day for 4 extra workers. Over 30 days = $210 total for 4 workers every day. This is absurdly cheap. A naive player who doesn't hire is leaving 3-4× action throughput on the table.

---

### 10.2 Hands Vanish at End-of-Day
**Rule**: *"At the end of the day all hands drop inventory at the farm and disappear."*

**Mechanic**: Hands are temporary. Any items they carry are force-dumped into the shed at end-of-day. If the shed overflows, the hand's items are lost.

**Exploit**: Ensure hands drop their inventory at the shed (via DROP action) BEFORE end-of-day. Don't let the automatic end-of-day dump discard items. Send hands back to the shed on turns 20-22 to manually DROP, then their end-of-day dump has nothing to lose.

---

### 10.3 Hand Spawn on Locked Tiles
**Rule**: *"Spawn placement ignores whether the tile is locked."*

**Mechanic**: Hands can spawn on locked tiles adjacent to the shed. They're not stuck — locked tiles are passable, so they can walk to unlocked tiles immediately.

**Exploit**: A hand spawning on (5,4) in the locked NE can reach (4,4) in the unlocked NW in 1 turn. Plan for this 1-turn transit cost. Alternatively, the hand can perform shed actions (DROP, PICKUP, PLACE) from the locked tile immediately — saving the transit turn entirely.

---

## Category 11: Weed Mechanics

### 11.1 Weeds Only Spawn on Empty UNLOCKED Tiles
**Rule**: *"Weeds have a chance of spawning on any empty cells on the farm."* *"weedSpawnChance: 0.005 per-tile probability on empty unlocked tile."*

**Mechanic**: Weeds only spawn on empty, unlocked tiles. Locked tiles and occupied tiles are immune.

**Exploit**: If you want to minimize weed spawns, keep tiles occupied (with crops, animals, or even intentionally uncleared dead crops). An empty tile is a weed target. A tile with a growing plant is safe.

**Counterintuitive**: Having fewer unlocked tiles actually helps. Don't buy land you aren't going to use — more empty unlocked tiles = more weeds = more DIG actions wasted.

---

### 11.2 Weed Probability Math
**Mechanic**: 0.5% per empty unlocked tile per day. With 25 tiles (1 quadrant) and 10 empty, expected weeds = 0.05/day. With 100 tiles (all quadrants) and 50 empty, expected weeds = 0.25/day ≈ 1 weed every 4 days.

**Exploit**: Weed pressure is negligible in the early game (few empty tiles), but scales with unlocked empty tiles. Budget ~1 DIG action every 4 days per empty quadrant. This is a nearly invisible cost.

---

## Category 12: Turn-Exact Timing Mechanics

### 12.1 Shop Consumption Tick Schedule
**Rule**: Shops consume every 4 turns. Town center every 24 turns.

**Mechanic**: Shop ticks happen on turns `t % 4 == 0` (turns 0, 4, 8, 12, 16, 20 of each day). Town center ticks on `t % 24 == 0` (turn 0 of each day — first turn only).

**Exploit**: The exact turn you sell matters. Sell on turn 1 (right after shop+town consumption on turn 0) to get the best price. Sell on turn 3 (right before the next shop consumption) and you sell at a slightly worse price that would have been better 1 turn later.

---

### 12.2 Market Prices Update AFTER Your Turn
**Rule**: *"Market refresh — modify the price of items on the market based on sells from previous turn."*

**Mechanic**: The price you see in your observation reflects the PREVIOUS turn's market state. Your current turn's sells haven't been priced into the observation yet.

**Exploit**: When you see a high price in `obs["market"]["prices"]`, that price reflects inventory BEFORE this turn's activity. If you sell this turn, you get the pre-sell inventory price (which is what's displayed). This is good — the price you see is the price you get for your first unit sold.

---

### 12.3 End-of-Day Processing Chain
**Mechanic**: At the end of each day (turn 23 processing):
1. Inventories dumped to shed (overflow discarded)
2. Plant watering checked (consecutive_unwatered incremented or reset)
3. Animal feeding checked (consecutive_unfed incremented or reset)
4. Animal care bonus banked (if fed AND cared)
5. Animal fertilizer set (1 per surviving animal)
6. Plant/animal death check (counter ≥ 2 → weed/escape)
7. Weed spawn on empty unlocked tiles
8. All hands dismissed

**Exploit**: Knowing this exact order lets you optimize the last few turns of each day. On turn 23, your WATER/FEED actions still count for that day's check. You have until the very last turn to keep things alive.

---

## Summary: Top 10 Most Impactful Mechanics

| Rank | Mechanic | Impact |
|---|---|---|
| **1** | Seeds globally available + buy-and-plant same turn | Saves setup turns massively |
| **2** | Sell directly from shed via market (no PICKUP needed) | Eliminates transport overhead |
| **3** | Skip-day watering survival | Cuts watering labor by 50% |
| **4** | CARE is useless for geese, crucial for sheep | Saves 1 action/day per goose |
| **5** | Shed access from locked tiles | Saves $7k in land costs |
| **6** | Decay is per-TURN not per-day | 12 turns to harvest decaying crops, not 24 |
| **7** | $1 floor doesn't add to market inventory | Enables market cycling strategy |
| **8** | Farm hands cost $7/day for 4 workers | 4× action throughput for nearly free |
| **9** | Opponent farm is fully visible | Complete information for counter-strategy |
| **10** | Shop consumption ticks every 4 turns | Sell timing within the day matters |
