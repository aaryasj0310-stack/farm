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
        Wages & Feed Reserved, Slot Protection"]
        MKT_BRAIN["ARCH-MKT-02: MarketBrain
        Floor Hold, Carry Check, Drip Slicing"]
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
    PRICE_FC --> MKT_BRAIN
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
    E[P|d] table"]
    OPP["OpponentAdvice
    supply_adjustment, counter_pick"]
    BOOSTS["Shop Demand Boosts"]

    subgraph S1["Workforce & Cash Reservation"]
        HANDS["RULE-HIRE-01: get_target_hands(day)
        Day 0-5: 4 | Day 6-9: 8 | Day 10: 10 | Day 11+: 12"]
        HIRE_COST["FORM-HIRE-01: hire_total_cost(target)"]
        RESERVE["FORM-BUDGET-01: Cash Reservation
        money - wages - feed - base_reserve (300)"]
    end

    subgraph S2["Land Expansion Gate"]
        L_ROI["FORM-LAND-01: compute_land_roi()
        Marginal profit on +25 tiles"]
        L_OW["opportunity_window_factor()
        1.0 if day <= 25 else 0.0"]
        L_URG["compute_land_urgency()
        Deadline proximity (SW D11 / NE D6)"]
        L_GATE{"DEC-LAND-SW-01: should_buy_land()
        Money >= Total Req & ROI_adj > 0"}
    end

    subgraph S3["Livestock & Wheat Balancing"]
        WHEAT_PROJ["Project Wheat Tile Harvests"]
        HERD_CAP["FORM-HERD-01: Sustainable Herd Calc
        herd <= wheat_prod / (buffer * interval)"]
        ANIM_TGT["DEC-ANIM-01: get_animal_targets()
        Optimal terminal profit (C4 Cutoff D12)"]
        WHEAT_DEF["FORM-WHEAT-DEF: Wheat Deficit Check
        needed = herd * buffer; buy_wheat = needed - have"]
    end

    subgraph S4["Land Allocation & Portfolio Crop Scoring"]
        TILE_PART["Tile Partitioning
        NW/NE/SW soil vs Pasture/Coop vs Fallow"]
        CROP_COUNT["FORM-CROP-01: get_committed_crop_counts()
        live + planned + candidate"]
        CROP_SCORE["FORM-CROP-02: _crop_score()
        E[Revenue(I_eff)] - Costs / CycleDays"]
        CAP_CHECK{"DEC-CROP-CAP: Cap / Deadline Check
        CROP_TILE_CAPS & dynamic strawberry cap"}
        QUEUES["MacroPlan Queues:
        plant_queue, build_queue, place_queue"]
    end

    CTX --> HANDS --> HIRE_COST --> RESERVE
    CTX --> L_ROI
    FC --> L_ROI
    L_ROI --> L_GATE
    L_OW --> L_GATE
    RESERVE --> L_GATE
    L_URG --> RESERVE

    CTX --> WHEAT_PROJ --> HERD_CAP
    HERD_CAP --> ANIM_TGT
    RESERVE --> ANIM_TGT
    ANIM_TGT --> WHEAT_DEF

    CTX --> TILE_PART
    L_GATE -->|SW Unlocked| TILE_PART
    TILE_PART --> CROP_SCORE
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
        affordable_hires = min(k, money // fib)"]
        SURV_FEED["Survival Feed Wheat Reserved
        w_buyable = min(req, discretionary // unit_px)"]
        DISC_BUDGET["Discretionary Budget Partition
        Land ($2,000) -> Seeds (Melon/Straw/Wheat) -> Animals"]
        SLOT_ALLOC["FORM-SLOT-01: Slot Budgeting
        non_hire_needed = wheat + land + seeds
        max_hire_slots = max(4, 10 - non_hire_needed)"]
        H0_ORDERS["Hour 0 Market Orders:
        max_hire_slots x ['HIRE']
        1x ['BUY_LAND'] (guaranteed slot!)
        1x ['BUY_PRODUCT', 'WHEAT', n]
        Nx ['BUY_SEED', crop, n]"]
        H1_DEFER["Hour 1 Deferred Hiring:
        target_hands - hires_today x ['HIRE']"]
    end

    subgraph SELLS["Sell-Side Trading (MarketBrain / Endgame)"]
        SHED["Private Shed Inventory
        Melon, Straw, Milk, Wool, Egg, Wheat, Fert"]
        WIN_CHECK{"Hour in SELL_WINDOWS?
        [1, 5, 9, 13, 17, 21]"}
        SHED_CAP{"Shed Emergency?
        Shed >= 65 (soft cap)
        or H >= 22 & Shed > 88 (midnight)"}
        FLOOR_CHECK{"Floor Hold?
        Spot == $1 & days_left >= 5"}
        CARRY_CHECK{"Carry Check?
        E[P|d+3] > Spot + 2%"}
        DRIP_SIZE["FORM-DRIP-01: Drip Slicing
        Safe qty where marginal price >= keep_frac * spot"]
        MELON_CAP["RULE-MKT-03: Melon Season Cap
        sold_melons <= 150"]
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
    SHED_CAP -->|Urgency 1 or 2| DRIP_SIZE
    WIN_CHECK -->|Urgency 0| FLOOR_CHECK
    FLOOR_CHECK -->|Pass| CARRY_CHECK
    CARRY_CHECK -->|Pass| DRIP_SIZE
    DRIP_SIZE --> MELON_CAP --> SELL_ORDERS
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
        T100["Priority 100: Starving Animal Feed & Dying Plant Water"]
        T90["Priority 90: Decaying Crop Harvest (turns <= 1)"]
        T86["Priority 86: Feed Staging (PICKUP wheat from shed)"]
        T85["Priority 85: Production Day Animal Feed"]
        T84["Priority 84: Animal Placement (shed to pasture)"]
        T78["Priority 78: Structure Build (BUILD_PASTURE)"]
        T75["Priority 75: Plant & Water (immediate same-day watering)"]
        T75B["Priority 75: Fertilizer Collection"]
        T70["Priority 70: Bonus Window Water"]
        T65["Priority 65: Animal Care & Standard Harvest"]
        T20["Priority 20: Routine Weeding"]
    end

    subgraph DISPATCH["task_scheduler.assign_tasks()"]
        STICKY{"Unit Locked in
        _ACTIVE_MISSIONS?"}
        RESUME["Continue Pathfinding toward Target"]
        FILTER["Filter Reachable Eligible Units
        (e.g., must hold wheat for FEED)"]
        ZONING{"Within C2 Zonal Boundary?
        dist <= 12 Manhattan"}
        CLUSTERING["FORM-EXEC-01: Clustered Scoring
        Score = Priority - 3*Dist + ClusterBonus"]
        BEST_UNIT["Assign Best Scored Unit"]
        SET_STICKY["Register in _ACTIVE_MISSIONS"]
    end

    subgraph PATHFINDING["bfs_first_step()"]
        BFS["Breadth-First Search on 10x10 Grid"]
        STEP{"At Target?"}
        OP["Emit OP: WATER, FEED, HARVEST, CARE, PLANT, etc."]
        MOVE["Emit Direction: MOVE_NORTH, SOUTH, EAST, WEST"]
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

    TRY_MAIN{"Try Main Pipeline:
    _agent_decision(obs)"}
    PLAN_EXEC{"Planner / Dispatch
    Success?"}
    SURV_CTX["_survival_fallback_from_ctx(ctx)
    Rescue Feed > Water Dying > Harvest Decay"]
    SURV_RAW["_survival_fallback_raw(obs)
    Pure unparsed dictionary survival"]

    OBS --> GET_ST --> RESET_CHK
    RESET_CHK -->|Yes| RESET_EXEC --> TRY_MAIN
    RESET_CHK -->|No| TRY_MAIN

    TRY_MAIN --> PLAN_EXEC
    PLAN_EXEC -->|Success| NORMAL["Normal Action Dict Assembly"]
    PLAN_EXEC -->|Exception in Planner/Dispatch| SURV_CTX
    TRY_MAIN -->|Exception in State/Setup| SURV_RAW

    SURV_CTX --> FALL_ACT["Emit Survival Actions (_emergency_fallback = True)"]
    SURV_RAW --> FALL_ACT
    NORMAL --> ENGINE["Engine Execution"]
    FALL_ACT --> ENGINE
```
