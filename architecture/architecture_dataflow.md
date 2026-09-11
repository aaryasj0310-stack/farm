# Kaggriculture Runtime Architecture & Data-Flow Graph

> **Target Environment**: Kaggle Environments `kaggriculture`  
> **Source Package**: `submission/`  
> **Purpose**: Visualizes the complete closed-loop runtime pipeline from raw observation ingestion to engine action emission, state transitions, and persistent memory feedback.

---

## 1. End-to-End System Data-Flow

```mermaid
flowchart TD
    subgraph ENGINE_IN["Kaggle Engine Observation"]
        RAW_OBS["Engine Observation Dict (obs)
        day, hour, step, farms, market, town, private"]
    end

    subgraph STATE_LAYER["State Tracking & Parsing"]
        PARSER["ARCH-STATE-01: parse_observation()
        Structured Views: Farm, Market, Town, Private"]
        STATE_TRACK["ARCH-STATE-02: state_tracker.get_state()
        Episode Detection, Shop Delta, Drain Ledger"]
        MEM[("STATE-MEM-01: Persistent _STATE
        Drain Ledger, Opp Sales, Our Sales")]
    end

    subgraph OPP_LAYER["Opponent Modeling & Advisory"]
        OPP_MODEL["ARCH-STATE-03: Opponent Model
        snapshot, tile deltas, harvest schedule"]
        OPP_STATE[("STATE-OPP-SNAP / STATE-OPP-SHED
        Field Signatures & Shed Inventory")]
        OPP_ADV["ARCH-STRAT-02: Opponent Advisor
        supply_adj, preempt_sell, delay_sell"]
    end

    subgraph STRAT_LAYER["Strategic Planning Layer"]
        PRICE_FC["ARCH-STRAT-01: PriceForecast (W1)
        Expected Prices E[P|d], Quantiles, Tails"]
        SHOP_ADAPT["strategy.shop_adapter
        demand_boosts from Unlocked Shops"]
        EXP_PLAN["ARCH-STRAT-04: ExpansionPlanner
        Land ROI, Urgency, Buy Gate"]
        ANIM_PLAN["ARCH-STRAT-05: AnimalPlanner
        Optimal Herd Composition & Cutoff"]
        MACRO_PLAN["ARCH-STRAT-03: MacroPlanner (W2)
        Land Allocation, Crop Scoring, Herd Sizing"]
    end

    subgraph MARKET_LAYER["Market Planning & Compilation"]
        ORD_BUILD["ARCH-MKT-03: OrderBuilder
        Hire Acquisition & Feed Reserved, Slot Protection"]
        MKT_BRAIN["ARCH-MKT-02: MarketBrain
        Sell Windows, Shed Pressure,
        Melon Floor Hold/Drip,
        Non-Melon Phase Batches"]
        LIQUIDATOR["ARCH-STRAT-06: EndgameLiquidator
        D28-29 Final Inventory Dump"]
        MKT_COMP["MarketBrain.compose()
        Hour 0/1 Purchases First, Top 10 Cap"]
    end

    subgraph EXEC_LAYER["Execution & Dispatch Layer"]
        TASK_BUILD["ARCH-EXEC-01: build_tasks()
        12 Priority Tiers: Survival, Harvest, Feed, Plant"]
        TASK_ASSIGN["ARCH-EXEC-01: assign_tasks()
        Zonal Spillover, C6 Clusters, Sticky Missions"]
        STICKY_MEM[("STATE-STICKY: _ACTIVE_MISSIONS
        Multi-turn Worker Dispatches")]
        PATHFIND["ARCH-EXEC-02: bfs_first_step()
        Cardinal Grid Movement Moves"]
    end

    subgraph SAFETY_LAYER["Safety & Fallback Layer"]
        FAIL_TRAP{"Exception Caught in
        Strategy / Scheduler?"}
        CTX_FALLBACK["_survival_fallback_from_ctx()
        Emergency Rescue Feed & Water"]
        RAW_FALLBACK["_survival_fallback_raw()
        Direct Parsing Fallback"]
        DIAG_LOG[("STATE-DIAG-FALL: Fallback Diagnostic")]
    end

    subgraph ENGINE_OUT["Kaggle Engine Action Dict"]
        ACTION_DICT["Engine Action Dict
        farmer: [OP, ...]
        hands: [[OP, ...], ...]
        market: [[OP, ...], ...]"]
    end

    %% Data flow connections
    RAW_OBS --> PARSER
    RAW_OBS --> STATE_TRACK
    PARSER --> STATE_TRACK
    STATE_TRACK <--> MEM
    STATE_TRACK --> OPP_MODEL
    OPP_MODEL <--> OPP_STATE
    OPP_MODEL --> OPP_ADV
    SHOP_ADAPT --> MACRO_PLAN
    OPP_ADV --> MACRO_PLAN
    PRICE_FC --> MACRO_PLAN
    PRICE_FC --> EXP_PLAN
    EXP_PLAN --> MACRO_PLAN
    ANIM_PLAN --> MACRO_PLAN

    MACRO_PLAN -->|MacroPlan: queues & intents| FAIL_TRAP
    FAIL_TRAP -->|Normal Execution| TASK_BUILD
    FAIL_TRAP -->|Exception Caught| CTX_FALLBACK
    CTX_FALLBACK --> DIAG_LOG
    RAW_FALLBACK --> DIAG_LOG

    TASK_BUILD --> TASK_ASSIGN
    TASK_ASSIGN <--> STICKY_MEM
    TASK_ASSIGN --> PATHFIND
    PATHFIND --> ACTION_DICT

    MACRO_PLAN -->|intents: hire, land, seed, wheat| ORD_BUILD
    PARSER --> ORD_BUILD
    ORD_BUILD -->|purchase_orders| MKT_COMP

    PARSER --> MKT_BRAIN
    PRICE_FC -.->|Injected dependency unused by live sell path| MKT_BRAIN
    OPP_ADV --> MKT_BRAIN
    MKT_BRAIN -->|sell_orders (D0-27)| MKT_COMP
    LIQUIDATOR -->|sell_orders (D28-29)| MKT_COMP
    MKT_COMP -->|market: top 10 orders| ACTION_DICT

    CTX_FALLBACK -.->|Emergency Actions| ACTION_DICT
    RAW_FALLBACK -.->|Raw Survival Actions| ACTION_DICT

    ACTION_DICT -->|Turn T Executes| RAW_OBS
```

---

## 2. Strategic Planning Data-Flow (`MacroPlanner`)

```mermaid
flowchart TD
    CTX["Parsed Context (ctx)
    FarmView, MarketView, PrivateView"]
    FC["PriceForecast
    Exhaustive 8^8 Distribution"]
    OPP["OpponentAdvice
    supply_adjustment, counter_pick"]
    BOOSTS["Shop Demand Boosts"]

    subgraph S1["Workforce & Cash Reservation"]
        HANDS["RULE-HIRE-01: get_target_hands(day)
        Day 0-5: 4 | Day 6-9: 8 | Day 10: 10 | Day 11+: 12"]
        HIRE_COST["FORM-HIRE-01: Incremental hiring capital cost"]
        RESERVE["FORM-ANIM-BUDGET-01: Livestock Cash Reservation
        money - future_hire_cost - seed_reserve - land_reserve - base_reserve"]
    end

    subgraph S2["Land Expansion Gate & Intent Pipeline"]
        L_ROI["FORM-LAND-01: compute_land_roi()
        Marginal profit on +25 tiles (optimistic crop portfolio)"]
        L_OW["opportunity_window_factor()
        1.0 if day <= 25 else 0.0"]
        L_URG["compute_land_urgency()
        Deadline proximity (SW D11 / NE D6)"]
        L_GATE{"DEC-LAND-SW-01: should_buy_land()
        Money >= Total Req & ROI_adj > 0 & Labor Feasible & Payback Surplus > 0"}
        BUY_INTENT["MacroPlan.intents['buy_land'] = True"]
        ORD_BUY["OrderBuilder emits BUY_LAND (Hour 0)"]
        ENG_PROC["Engine Market Processing (Turn T)"]
        NEXT_OBS["Next Turn Observation (Turn T+1):
        farm.unlocked updated with SW"]
    end

    subgraph S3["Livestock & Wheat Balancing"]
        WHEAT_PROJ["Project Wheat Supply: shed + workers + planted + planned + affordable"]
        HERD_CAP["FORM-HERD-01: Authoritative Feed Capacity
        sustainable = floor(projected_wheat_supply / feeding_days_left)"]
        ANIM_TGT["DEC-ANIM-01: get_animal_targets(..., max_sustainable=sustainable)
        Strictly clamped by feed capacity (no ungrounded early-game exception)"]
        WHEAT_DEF["FORM-FEED-01: Wheat Buffer Purchase Need
        needed = animals * buffer; buy = min(needed - have, budget // 25)"]
    end

    subgraph S4["Land Allocation & Crop Engines"]
        TILE_PART["Tile Partitioning
        NW/NE Soil vs SW Dedicated Soil vs Pastures vs Portal"]
        SW_DEC["FORM-SW-WHEAT-01: sw_plant_decision()
        n_wheat = min(free, (deficit + 4) // 5); Remainder to CARROT (RULE-CROP-04)"]
        CROP_COUNT["FORM-CROP-01: get_committed_crop_counts()
        Mutated loop: live + planned, candidate + 1"]
        CROP_SCORE["FORM-CROP-02: _crop_score()
        Revenue Multipliers & Lifecycle Costs
        FORM-CROP-DRAIN-01 / FORM-CROP-INVENTORY-01"]
        CAP_CHECK["RULE-CROP-01 / 02 / 03A: Caps & Deadlines"]
        QUEUES["MacroPlan Queues:
        plant_queue, build_queue, place_queue"]
    end

    CTX --> HANDS
    HANDS --> HIRE_COST --> RESERVE

    CTX --> L_ROI
    FC --> L_ROI
    L_ROI --> L_GATE
    L_OW --> L_GATE
    RESERVE --> L_GATE
    L_GATE -->|Yes: set intent| BUY_INTENT
    BUY_INTENT --> ORD_BUY --> ENG_PROC --> NEXT_OBS
    NEXT_OBS -.->|Subsequent Turn Planning| CTX

    CTX --> WHEAT_PROJ --> HERD_CAP
    HERD_CAP -.->|Calculated but Uncoupled| ANIM_TGT
    RESERVE --> ANIM_TGT
    ANIM_TGT --> WHEAT_DEF

    CTX -->|farm.unlocked (already-owned quadrants)| TILE_PART
    TILE_PART -->|If SW in farm.unlocked: 15 Soil Tiles| SW_DEC
    SW_DEC --> QUEUES
    TILE_PART -->|NW / NE Soil Tiles| CROP_SCORE
    CROP_COUNT --> CROP_SCORE
    OPP --> CROP_SCORE
    BOOSTS --> CROP_SCORE
    FC --> CROP_SCORE
    CROP_SCORE --> CAP_CHECK
    CAP_CHECK --> QUEUES
```

---

## 3. Market Layer: Purchase & Sell Order Compilation

```mermaid
flowchart TD
    subgraph PURCHASES["Morning Purchases (Hour 0 & Hour 1)"]
        INTENTS["MacroPlan.intents
        hire, buy_land, buy_seed, buy_wheat, buy_animal"]
        ORD_BUILD["ARCH-MKT-03: OrderBuilder.build()"]
        MAND_HIRE["Mandatory Hire Cost Reserved
        Iteratively accumulate Fibonacci hire costs from farm.hires_today"]
        SURV_FEED["Survival Feed Wheat Reserved
        w_buyable = min(req, discretionary // unit_px)"]
        DISC_BUDGET["FORM-BUDGET-01: Discretionary Budget
        money - mandatory_hire_budget - reserve - survival_feed_budget
        Land ($2,000) -> Seeds -> Animals"]
        SLOT_ALLOC["FORM-SLOT-01: Slot Budgeting
        non_hire_needed = wheat + land + seeds
        max_hire_slots = max(4, 10 - non_hire_needed)"]
        H0_ORDERS["Hour 0 Market Orders (Priority Sequence):
        1. HIRE (up to max_hire_slots)
        2. BUY_PRODUCT WHEAT (slot-protected)
        3. BUY_LAND (slot-protected if affordable / kept)
        4. BUY_SEED (slot-protected)
        5. BUY_ANIMAL"]
        H1_DEFER["Hour 1 Deferred Hiring (main.py):
        recompute max(0, target_hands - hires_today)
        emit min(needed, 10) x HIRE orders
        (no explicit agent-side affordability check)"]
    end

    subgraph SELLS["Sell-Side Trading (MarketBrain / Endgame)"]
        SHED["Private Shed Inventory
        Melon, Straw, Milk, Wool, Egg, Wheat, Fert"]
        WIN_CHECK{"Hour in SELL_WINDOWS?
        [1, 5, 9, 13, 17, 21]"}
        SHED_CAP{"Shed Emergency?
        Shed >= 65 (relieves toward 55 this turn)
        or H >= 22 & Shed > 88 (midnight)"}
        PROD_BRANCH{"Product Check"}
        PROT_BRANCH["DRIP_PROTECTED_PRODUCTS (MELON, WOOL, MILK, STRAWBERRY):
        1. Hold at $1 floor (if normal / relief)
        2. FORM-DRIP-01: safe_drip_budget (P_keep = max(2, floor(spot * keep_frac)))
        3. MELON: Cap to MELON_SEASON_SALE_CAP (150)
        4. Update live I_mkt per slice"]
        OTHER_BRANCH["NON-PROTECTED Branch:
        1. If spot <= 1: urgency_score = 0.95 (priority boost)
        2. Phase batch_target: D0-5: 15, D6-8: 7, D9+: 4
        (Relief: max(bt, 10), Urg2/End: 20)"]
        SELL_ORDERS["Compiled Sell Orders:
        ['SELL', prod, qty]"]
    end

    subgraph COMPOSE["MarketBrain.compose()"]
        MERGE["Interleave Purchases & Sells
        Hour 0 & 1: Purchases First
        Other Hours: Sells First
        Cap at 10 Total Orders"]
        EMITTED["Final Emitted Market Orders
        sent to Kaggle Engine"]
    end

    INTENTS --> ORD_BUILD
    ORD_BUILD --> MAND_HIRE --> SURV_FEED --> DISC_BUDGET
    DISC_BUDGET --> SLOT_ALLOC --> H0_ORDERS
    H0_ORDERS --> MERGE
    H1_DEFER --> MERGE

    SHED --> WIN_CHECK
    SHED --> SHED_CAP
    SHED_CAP -->|Urgency 1 or 2| PROD_BRANCH
    WIN_CHECK -->|Urgency 0 Window Open| PROD_BRANCH
    PROD_BRANCH -->|Melon| MELON_BRANCH --> SELL_ORDERS
    PROD_BRANCH -->|Other Commodities| OTHER_BRANCH --> SELL_ORDERS
    SELL_ORDERS --> MERGE

    MERGE --> EMITTED
```

---

## 4. Execution Layer: Task Scheduling & Spatial Assignment

```mermaid
flowchart TD
    CTX_UNITS["Farmer (ID 0) & Hired Hands (IDs 1..N)
    Current positions, inventory (holding wheat/fert)"]
    TILES["10x10 Farm Tiles (TileView)
    is_plant, is_animal, watered, fed, yield_units"]
    PLAN_Q["MacroPlan Queues:
    plant_queue, build_queue, place_queue"]

    subgraph BUILD_TASKS["task_scheduler.build_tasks()"]
        T100["Priority 100: Survival WATER for Plants in Immediate Dehydration Danger"]
        T99["Priority 99: Animal Emergency FEED Rescue (consecutive_unfed >= 1)"]
        T90["Priority 90: Decaying Crop Harvest (turns <= 1)"]
        T87["Priority 87: Fertilizer Staging (PICKUP from shed)"]
        T86["Priority 86: Feed Staging (PICKUP wheat from shed)"]
        T85["Priority 85: Production Day Animal Feed"]
        T84["Priority 84: Animal Placement (shed to pasture)"]
        T78["Priority 78: Structure Build (BUILD_PASTURE)"]
        T76["Priority 76: Max Yield Day Bonus Water"]
        T75["Priority 75: Plant & Water / Fertilizer Collection"]
        T70["Priority 70: Bonus Water & Animal Harvest"]
        T65["Priority 65: Animal Care & Standard Harvest"]
        T60["Priority 60: Crop Fertilization (Straw/Tom/Wheat/Carrot) & Off-Feed"]
        T30["Priority 30: Routine Off-Window Water"]
        T20["Priority 20/35: Routine / Blocking Weed Dig"]
        T10["Priority 10/5/1: Idle Fallback (Fert Collect > Water > Dig > Port SW)"]
    end

    subgraph DISPATCH["task_scheduler.assign_tasks()"]
        STICKY{"Unit Locked in
        _ACTIVE_MISSIONS?"}
        RESUME["Continue Pathfinding toward Target"]
        FILTER["Filter Reachable Eligible Units
        (e.g., must hold wheat for FEED)"]
        ZONING{"Within C2 Zonal Boundary?
        dist <= 12 Manhattan (FORM-DIST-01) & No Diagonal SW<->NE"}
        CLUSTERING["FORM-EXEC-01: Clustered Scoring (C6_PRIORITY_BAND = 20)
        Score = -Prio + SpillPenalty(10) + 3*(Dist - ClusterBonus)"]
        BEST_UNIT["Assign Best Scored Unit"]
        SET_STICKY["Register in _ACTIVE_MISSIONS
        (Age <= 40 & NoProgress < 4)"]
    end

    subgraph PATHFINDING["task_scheduler.emit() / bfs_first_step()"]
        BFS["Breadth-First Search on 10x10 Grid"]
        STEP{"At Target?"}
        OP["Emit Tile Action: WATER, FEED, HARVEST, CARE, PLANT, etc."]
        MOVE["Emit Direction String: 'NORTH', 'SOUTH', 'EAST', 'WEST'"]
    end

    TILES --> BUILD_TASKS
    PLAN_Q --> BUILD_TASKS
    BUILD_TASKS --> DISPATCH
    CTX_UNITS --> DISPATCH

    DISPATCH --> STICKY
    STICKY -->|Yes| RESUME
    STICKY -->|No| FILTER
    FILTER --> ZONING
    ZONING --> CLUSTERING --> BEST_UNIT --> SET_STICKY
    RESUME --> PATHFINDING
    BEST_UNIT --> PATHFINDING

    PATHFINDING --> BFS --> STEP
    STEP -->|Yes| OP
    STEP -->|No| MOVE
```

---

## 5. Fail-Safe Closed Loop: Exception Recovery & Episode Reset

```mermaid
flowchart TD
    OBS["Kaggle Agent Step (obs)"]
    GET_ST["state_tracker.get_state(obs)"]
    RESET_CHK{"New Episode?
    day < last_day OR
    (day == 0 & hour == 0 & seen)"}
    RESET_EXEC["reset_memory()
    Fire Registered Reset Hooks"]

    subgraph DOMAIN_ISO["Domain-Isolated Turn Execution in main._agent_decision()"]
        TRY_STRAT{"Try Strategy & Execution:
        MacroPlanner & TaskScheduler"}
        TRY_PURCH{"Try Morning Purchases:
        Hour 0: OrderBuilder / Hour 1: Hires"}
        TRY_SELL{"Try Sell-Side Market:
        MarketBrain.sell_orders() / Endgame"}
        TRY_COMP{"Try Order Composition:
        MarketBrain.compose()"}
    end

    SURV_CTX["_survival_fallback_from_ctx(ctx)
    Rescue Feed > Water Dying > Harvest Decay"]
    DIAG_LOG[("STATE-DIAG-FALL: _LAST_FALLBACK_DIAGNOSTIC")]

    OBS --> GET_ST --> RESET_CHK
    RESET_CHK -->|Yes| RESET_EXEC --> TRY_STRAT
    RESET_CHK -->|No| TRY_STRAT

    TRY_STRAT -->|Success| TRY_PURCH
    TRY_STRAT -->|Exception| SURV_CTX
    SURV_CTX --> DIAG_LOG
    SURV_CTX --> TRY_PURCH

    TRY_PURCH --> TRY_SELL
    TRY_SELL --> TRY_COMP
    TRY_COMP --> ACTION_DICT["Emit Final Action Dict
    (farmer, hands, market, _emergency_fallback)"]
```
