# Point 2 — Feed/Herd Sustainability Final Design

Baseline commit:

`547357a91d22260435e961dedc24f292e846e713`

Frozen Phase-A baseline commit:

`484244083aea694af29459995546d120e7063194`

This document incorporates the Step 1–3 Sol audit and subsequent Astra architectural critique.

## Objective

Replace the capital-insensitive scalar `sustainable_herd_size` expansion veto with one shared candidate-specific feed/cash feasibility model while preserving strict survival protection for animals already owned.

This redesign must not weaken:

* existing-herd survival priority;
* protected-feed market priority;
* livestock economic profitability checks;
* physical housing constraints;
* species/herd caps;
* livestock cutoff rules;
* the post-Day-12 rule that only physically built, currently empty, compatible, unreserved housing authorizes a new animal.

Point 2 must remain independent of speculative SW ownership or future SW production.

---

# 1. Remove the scalar expansion authority

The following pattern must no longer be the authoritative expansion gate:

```python
projected_feed_supply = (
    wheat_on_hand
    + planted_yield
    + planned_yield
    + min(100, affordable_market_wheat)
)

sustainable_herd_size = (
    projected_feed_supply // feeding_days_left
)
```

`max_sustainable` must no longer prevent a candidate from reaching candidate-specific feed feasibility and marginal economic evaluation.

Do not simply increase or remove the `100` constant while keeping the existing scalar architecture.

The old scalar may temporarily remain for diagnostics during migration, but it must not remain an independent veto after the new evaluator becomes authoritative.

---

# 2. One authoritative FeedFeasibility evaluator

Introduce one shared resource-feasibility component used by:

1. `DynamicHerdPlan` for provisional forward animal/infrastructure decisions.
2. Live `BUY_ANIMAL` execution immediately before purchase authorization.

Conceptual interface:

```python
evaluate_feed_feasibility(
    current_state,
    shadow_state,
    candidate_species=None,
    horizon_days=4,
)
```

It should return structured diagnostics including at least:

```python
{
    "feasible": bool,
    "existing_herd_feasible": bool,

    "near_term_wheat_required": int,
    "near_term_market_wheat_required": int,

    "remaining_feed_units": int,
    "remaining_feed_cash_reserved": float,

    "minimum_wheat_slack": float,
    "minimum_cash_slack": float,

    "blocking_day": Optional[int],
    "blocking_reason": Optional[str],

    "timeline": [...],
}
```

Exact names may differ, but semantic information must remain available.

---

# 3. Existing herd always receives first claim

Before considering any new animal:

1. Calculate upcoming feed obligations for animals already owned.
2. Reserve physically available wheat required for them.
3. Account for deterministic secured wheat arrivals occurring before each feeding deadline.
4. Reserve required market-wheat purchases/cash for any remaining unavoidable shortfall.

If the existing herd baseline is infeasible:

```text
block all livestock expansion
```

but do not suppress the survival response.

Instead:

```text
preserve wheat
preserve feed-purchase cash
emit protected-feed intent
prioritize feeding/staging
```

Resources reserved for current animals remain unavailable to:

* candidate animals;
* optional feed buffering;
* land;
* seeds;
* discretionary purchases;
* wheat selling.

---

# 4. Two different horizons with different meanings

Do not use a 4-day pass as sufficient lifetime purchase authorization.

Use:

## Operational horizon

Default:

```text
4 days
```

because `FEED_WHEAT_BUFFER_DAYS = 4` bridges the wheat production cycle.

Within this horizon, feasibility must be concrete and timing-aware.

For every feeding deadline:

```text
cumulative wheat physically usable by deadline
>=
cumulative feed obligation by deadline
```

Allowed near-term supply:

* current shed wheat;
* worker-carried wheat;
* physically planted wheat with deterministic harvest timing;
* market wheat that can be purchased and stored/delivered before the deadline.

A harvest occurring after a feeding deadline cannot cover that earlier obligation.

## Remaining-lifetime funding horizon

For a candidate animal, calculate remaining feeding obligations through the end of its applicable feeding lifetime/season.

The portion beyond the hard operational horizon does not need to exist physically today.

However, its conservative replacement cost must already be fundable/reserved from non-speculative available capital.

Therefore:

```text
4-day horizon
= physical + execution feasibility

remaining lifetime
= funding feasibility
```

This prevents a candidate from passing four days and becoming financially impossible on Day 5.

---

# 5. Hard-feasibility cash policy

Version 1 must use:

```text
observed spendable cash
```

as the authoritative funding source.

Do not count unrealized revenue from:

* the candidate animal;
* existing animals;
* future fertilizer;
* future crops;
* future expected product sales;
* hypothetical market timing;
* unexecuted sale orders.

Those revenues remain available to profitability models.

Once revenue actually appears in a subsequent observation, it becomes ordinary observed cash and may fund subsequent expansion.

This deliberately sacrifices some aggressive reinvestment for safety and architectural clarity.

---

# 6. Candidate-generated revenue cannot bootstrap candidate feasibility

Do not allow:

```text
buy animal
→ future output
→ expected sale
→ expected cash
→ future feed
→ therefore animal is feasible
```

Candidate-generated revenue receives zero credit in hard admission feasibility.

It remains fully eligible inside:

```text
marginal_livestock_valuator
```

for deciding whether the animal is economically worthwhile.

Similarly, unrealized future output from previously purchased animals is not hard funding until it actually settles into observed cash.

---

# 7. Feed pricing & lifetime WHEAT funding policy (`engine_stress_bound_v1`)

Use the authoritative live buffered wheat purchase-price machinery established in Point 1 for current executable wheat:

```python
estimate_wheat_buy_price(ctx)
```

Near-term market purchases inside the 4-day operational physical window must continue to use this current executable buffered wheat price.

## Lifetime WHEAT funding policy freeze

The Phase-A evaluator temporarily used:

```text
conditional_current_buffered_price
```

for lifetime funding telemetry. That was acceptable for Phase-A shadow diagnostics, but it must NOT become the authoritative Phase-B funding policy.

### Engine ground truth mechanics
The game engine pricing rules are:
```text
WHEAT base price = $25
MARKET_I0 = 10,000
scarcity shape = sqrt
T = 400
below_target = 0.80
WHEAT_BUY_PRICE_BUFFER = 1.10
```

Future lifetime feed funding must use the frozen policy:

```text
engine_stress_bound_v1
```

This is a **conservative planning stress bound**, NOT a mathematically adversarial maximum. Do NOT describe it as a guaranteed maximum future market price.

### Policy definition

For remaining-lifetime feed funding beyond the 4-day operational physical window, derive:

```text
stressed_wheat_inventory =
    current_observed_wheat_market_inventory
    - worst_case_remaining_town_wheat_drain
    - our_committed_future_market_feed_requirement
    - opponent_wheat_stress_allowance
```

Then evaluate the stress price:

```text
stress_raw_price =
    market_price("WHEAT", stressed_wheat_inventory)

stress_buffered_price =
    ceil(stress_raw_price * WHEAT_BUY_PRICE_BUFFER)

lifetime_wheat_price =
    max(
        current_executable_buffered_wheat_price,
        stress_buffered_price,
    )
```

where `current_executable_buffered_wheat_price = estimate_wheat_buy_price(ctx)`.

### 7A. Town WHEAT stress

Use actual engine mechanics:
* For shops already unlocked: use their actual shop identities and project their remaining WHEAT consumption across remaining episode hours.
* For shop instances not yet unlocked up to the engine maximum: assume every future shop instance consumes WHEAT (deliberately pessimistic).
* Include the remaining town-center WHEAT drain over the remaining episode turns.
* The calculation must dynamically depend on the current day/hour and remaining season rather than using one global constant.
* Document that this is an engine-derived worst-case town-demand bound.

### 7B. Our own WHEAT stress

Use the future market WHEAT requirement of the full currently committed herd/resource ledger.
It must include:
```text
existing-herd future market feed requirement
+
all previously accepted candidate reservations
+
the candidate currently being evaluated
```

Do NOT price each candidate independently against the original WHEAT market state.
After candidate #1 is accepted:
```text
candidate #1 increases our future WHEAT stress
→ recompute the stress price
→ candidate #2 is evaluated against that updated residual ledger
```
This is mandatory for sequential candidate admission.

### 7C. Opponent WHEAT stress

Use a conservative but bounded v1 rule:
```text
observed_opponent_feed_liability =
    currently observed opponent placed animals
    × remaining applicable feed days
```
Then:
```text
opponent_wheat_stress_allowance =
    max(
        observed_opponent_feed_liability,
        our_committed_future_market_feed_requirement,
    )
```

Do NOT assume unlimited malicious opponent WHEAT buying.
Do NOT assume speculative future opponent livestock expansion.
The purpose is to model plausible competitive WHEAT pressure while keeping the bound operationally useful.

### 7D. Explicit classification & terminology

Document this exact distinction:
```text
engine_stress_bound_v1
= conservative planning stress bound
!= hard mathematical maximum
```
The true engine price can exceed it under sufficiently adversarial future market depletion.
Therefore:
* New observations must rebuild/reprice the ledger on every turn.
* Phase C must revalidate actual purchases before live `BUY_ANIMAL` execution.
* Do not call lifetime funding "guaranteed."
* Use terminology such as:
  ```text
  stress-funded
  conservatively funded under engine_stress_bound_v1
  ```

### 7E. Worked example: sequential repricing under stress bound

*(Note: The following numbers are illustrative to demonstrate sequential ledger progression; they are not engine-guaranteed outputs).*

For the engine WHEAT pricing parameters (base = 25, I0 = 10,000, T = 400, below_target = 0.80, below_func = "sqrt"):
```text
amp = below_target × base / sqrt(T) = 0.80 × 25 / sqrt(400) = 20 / 20 = 1.0
market_price("WHEAT", inventory) ≈ 25 + sqrt(10,000 - inventory) [for inventory < 10,000 before integer rounding]
```

```text
Assume at Day 10, Hour 0:
current_observed_wheat_market_inventory = 9,500
worst_case_remaining_town_wheat_drain = 1,200
our_committed_future_market_feed_requirement (existing herd) = 200
observed_opponent_feed_liability = 300
opponent_wheat_stress_allowance = max(300, 200) = 300

Baseline stress state before candidates:
stressed_inventory_0 = 9,500 - 1,200 - 200 - 300 = 7,800
raw price = 25 + sqrt(10,000 - 7,800) = 25 + sqrt(2,200) ≈ 71.90
stress_raw_price_0 ≈ $72 (engine integer quote)
stress_buffered_price_0 = ceil(72 × 1.10) = $80.00
lifetime_wheat_price_0 = max(current_executable_buffered_price, $80.00) = $80.00

Candidate #1 (COW):
- Needs 18 lifetime feed units beyond operational window.
- Evaluated at lifetime price $80.00 → feed hold = 18 × $80 = $1,440.00.
- Purchase cash and feed cash available → candidate #1 feasible.
- Candidate #1 accepted and committed:
  our_committed_future_market_feed_requirement rises from 200 to 218 (+18).
  opponent_wheat_stress_allowance = max(300, 218) = 300.

Candidate #2 (COW) evaluation:
- our_committed_future_market_feed_requirement is now 218.
- Candidate #2 would add another 18 units (total 236).
- stressed_inventory_1 = 9,500 - 1,200 - 236 - 300 = 7,764.
- raw price = 25 + sqrt(10,000 - 7,764) = 25 + sqrt(2,236) ≈ 72.29
- stress_raw_price_1 ≈ $72 (engine integer quote)
- stress_buffered_price_1 = ceil(72 × 1.10) = $80.00 (or higher if cumulative drain lowers inventory further).
- Candidate #2 is evaluated against the updated residual cash balance ($original - purchase_cost_1 - feed_hold_1) at the updated stress price ($80.00+).
- Sibling candidates never reuse original cash or ignore prior candidates' market impact.
```

---

# 8. Sequential candidate admission

Dynamic herd planning must evaluate candidates sequentially against one mutable shadow resource ledger.

Conceptually:

```python
ledger = build_baseline_resource_ledger(...)

protect_existing_herd(ledger)

while capacity_remains:

    candidates = rank_by_marginal_EV(...)

    for candidate in candidates:
        feasibility = evaluate_incremental_candidate(
            ledger,
            candidate,
        )

    choose highest-value feasible candidate

    reserve:
        purchase cash
        candidate feed funding
        near-term wheat
        housing
        service capacity

    update ledger

    repeat
```

Each accepted candidate consumes resources before the next candidate is considered.

Never evaluate multiple candidate additions independently against the same original cash/wheat pool.

This prevents double spending.

---

# 9. Profitability remains separate

`marginal_livestock_valuator` remains the authoritative economic layer.

Feed feasibility answers:

> Can we safely support this animal?

Marginal livestock valuation answers:

> Is supporting this animal economically worthwhile?

Both must pass.

Feed purchase cost appearing in feasibility is an affordability/reservation test.

Feed cost appearing in marginal EV is an economic opportunity cost.

Do not add the same feed expenditure twice inside the EV calculation.

---

# 10. Physical housing remains separate

Preserve species/herd/housing limits.

In particular:

> After the normal Day-12 livestock cutoff, a new animal may be purchased only if a physically built, currently empty, compatible, unreserved pasture already exists for it.

Dynamic, queued, planned, candidate, reserved, or future pasture capacity gives zero late-purchase credit.

Point 2 must not weaken or reinterpret this invariant.

---

# 11. Do not credit speculative production

Hard feed feasibility must not gain resources because the candidate decision itself causes new planning.

Never allow:

```text
larger herd target
→ larger planned wheat target
→ larger feed capacity
→ larger herd target
```

Version 1 should not count:

* unowned SW;
* hypothetical SW activation;
* empty dirt;
* planned-but-not-physically-planted wheat;
* hypothetical future seed purchases;
* future target-driven crop reallocations.

Only independently secured resources may certify expansion.

Point 3 may later supply hypothetical SW scenarios to the same evaluator for counterfactual analysis, but they must not become current-state resources before ownership/activation.

---

# 12. Repeated market wheat purchases

Remove the arbitrary lifetime `100 wheat` expansion-credit ceiling.

Instead model market wheat purchases as dated expenditures against one shared declining cash balance.

For each required purchase:

```text
cash must exist before purchase
storage must exist when wheat arrives
market order must be executable
feed must be deliverable before deadline
```

Do not repeatedly calculate affordability from the original wallet.

Cash already reserved/spent for an earlier future feed obligation is unavailable to later candidates.

A later sale, harvest, consumption, or storage release cannot retroactively make an earlier purchase feasible.

---

# 13. Storage, execution, and execution-confidence policy

A positive abstract wheat balance alone is insufficient.

Near-term hard feasibility must account for relevant execution constraints:

* shed capacity at acquisition time;
* current partial day/hour;
* market-order availability;
* required worker pickup/staging;
* ability to deliver feed before daily deadline;
* protected feed cannot be displaced by optional market actions.

Reuse existing scheduler/serviceability information where practical.

Do not build a second complete task scheduler inside the feed evaluator.

## Execution-confidence policy freeze

The execution-confidence policy must strictly distinguish **Phase B forward planning** from **Phase C live purchasing**. This distinction is required because `DynamicHerdPlan` executes during macro planning before the final real scheduler assignment snapshot exists.

### Phase B — DynamicHerdPlan forward planning
In Phase B:
* `execution_confidence` is diagnostic and provisional information.
* It is NOT an independent veto by itself.
* A candidate must still be rejected for concrete hard failures such as:
  ```text
  existing_herd_feasible = False
  insufficient_cash
  shed_capacity
  feed_deadline failure
  late_hour_purchase
  other explicit hard feed/resource failure
  ```
* But `execution_confidence = "guarded"` or `execution_confidence = "conditional"` alone must NOT reject a Phase-B forward-planning candidate.
* If:
  ```text
  feed feasibility passes (cash, physical 4-day, lifetime stress funding)
  +
  candidate economics passes (positive marginal EV, housing hurdle)
  ```
  then Phase B may provisionally include the candidate in `DynamicHerdPlan` and record diagnostic status:
  ```text
  execution_status = "provisional_guarded"
  ```
* Reason: Phase B plans infrastructure and forward herd shape. It does NOT authorize the final engine `BUY_ANIMAL`.

### Phase C — Live BUY_ANIMAL execution
Phase C must fail closed when current-day existing-herd feed execution remains unresolved.

**Frozen rule:**
```text
IF unfed_placed_today > 0:

    IF execution_snapshot is absent
    OR execution_confidence != "high":

        reject new BUY_ANIMAL
```
Use an explicit rejection reason such as:
```text
feed_execution_unverified
```
or:
```text
feed_execution_not_verified
```

Existing-herd survival actions must continue normally. Do NOT suppress protected wheat purchases or FEED recovery merely because livestock expansion is blocked.

If `unfed_placed_today == 0`:
* Guarded/conditional execution confidence alone does NOT need to veto a new animal.
* The new animal is treated as an unplaced commitment and does not create a current-day physical FEED obligation.
* All other gates must still pass:
  * feed/cash feasibility
  * housing/serviceability
  * marginal economic value
  * market order capacity
  * actual purchase cash
  * post-Day12 physical-pasture invariant

### Worked execution example: Phase B vs Phase C

```text
Scenario: Day 10, Hour 8. 2 cows currently unfed on pasture. Worker is currently harvesting; feed pickup scheduled later today.
execution_confidence = "guarded".

Phase B (DynamicHerdPlan):
- Feed feasibility passes (plenty of cash, 4-day wheat secured, stress funding covered).
- Candidate EV positive.
- execution_confidence is "guarded".
→ Result: Provisional candidate accepted into DynamicHerdPlan; records execution_status = "provisional_guarded".
→ Forward pasture planning may plan housing for future expansion.
→ No BUY_ANIMAL order is emitted here.

Phase C (OrderBuilder live purchase revalidation):
- Candidate COW evaluated for live BUY_ANIMAL execution.
- unfed_placed_today = 2 (> 0).
- execution_confidence = "guarded" (!= "high").
→ Result: BUY_ANIMAL rejected with reason = "feed_execution_unverified".
→ Protected wheat order proceeds; worker completes feed delivery.
→ Livestock purchase fails closed until current herd feeding is verified.
```

---

# 14. DynamicHerdPlan integration

Replace:

```python
target_cap = min(
    herd_cap,
    max_sustainable,
)
```

as the primary feed authority.

DynamicHerdPlan should still respect:

* global herd cap;
* species caps;
* cutoff;
* housing/serviceability;
* marginal economic hurdle.

But each prospective animal should now be admitted only after candidate-specific feed/cash feasibility succeeds.

DynamicHerdPlan's result is provisional forward demand, not permission to bypass live execution checks.

---

# 15. Live purchase revalidation

Immediately before actual animal purchase, rerun the same authoritative feed/cash feasibility model using the latest observation and already-known turn commitments.

This catches:

* cash consumed by other actions;
* changed wheat inventory;
* failed expected purchases;
* newly consumed storage;
* changed feed needs;
* changed housing state.

Do not assume that a DynamicHerdPlan approval permanently reserves reality.

If the live check fails:

```text
do not buy the candidate
```

Existing-herd survival actions continue normally.

---

# 16. Observation reconciliation

Every new observation is authoritative.

Do not carry forward intended:

* wheat purchases;
* animal purchases;
* crop harvests;
* sale proceeds;
* feed deliveries

as if they executed successfully.

Rebuild/reconcile the resource ledger from observed state plus explicitly maintained same-turn reservations.

---

# 17. Required regression properties

The implementation must include tests proving:

1. Same Day-10 zero-wheat state with `$10k` vs `$100k` no longer produces the same artificial feed ceiling solely because of a 100-wheat cap.
2. Increasing genuinely usable cash never decreases candidate feed feasibility.
3. Increasing usable wheat never decreases feasibility.
4. Increasing wheat purchase price never increases feasibility.
5. Earlier secured wheat arrival is never worse than the same arrival later.
6. Wheat arriving after a feeding deadline cannot rescue that earlier deadline.
7. Hypothetical unplanted SW wheat gives zero hard-feasibility credit.
8. Planned-but-unsecured wheat gives zero hard-feasibility credit.
9. Existing animals receive resources before candidate animals.
10. An infeasible existing-herd baseline blocks expansion while still preserving/triggering survival actions.
11. Candidate-generated future revenue gives zero admission credit.
12. Unrealized existing-animal revenue gives zero admission credit.
13. A feed-feasible animal may still be rejected by negative marginal EV.
14. A profitable animal may still be rejected by feed/cash infeasibility.
15. Two candidates cannot independently reserve the same wheat/cash.
16. Repeated market purchases consume one declining cash balance.
17. Shed capacity is respected at each acquisition point, not only final state.
18. Four-day operational safety alone cannot authorize an unfunded remaining-lifetime feed obligation.
19. Live purchase revalidation can reject a previously provisional candidate.
20. Post-Day12 physical-empty-housing invariant remains unchanged.

---

# 18. Migration approach

Implement incrementally.

Phase A:

* Add resource-ledger/evaluator in shadow/diagnostic mode.
* Compare against current `sustainable_herd_size`.
* Do not change live decisions.

Phase B:

* Make candidate-specific feed feasibility authoritative in DynamicHerdPlan.
* Keep old scalar metric telemetry-only.

Phase C:

* Use same evaluator for live ArmC animal purchases.
* Remove duplicate `$25 × 3/4-day` feed gates once equivalent safety tests pass.

Phase D:

* Remove obsolete scalar expansion authority and dead compatibility paths only after full regression/live-season validation.

Do not change all feed logic in one uncontrolled rewrite.

---

# Final authority map & architectural rules

## Authority Map

```text
FeedFeasibility
    = physical feed + cash funding authority

engine_stress_bound_v1
    = lifetime funding stress-price policy

MarginalLivestockValuator
    = candidate profitability authority

DynamicHerdPlan
    = sequential provisional herd/infrastructure planner

TaskScheduler
    = physical worker execution authority

OrderBuilder / Phase-C live revalidation
    = final purchase enforcement

Observation
    = next-turn truth
```

## Final architectural rule

A livestock candidate is admissible only when:

```text
existing herd remains protected

AND

candidate purchase cash is available

AND

next-4-day feeding is physically/execution feasible

AND

remaining feeding obligation is conservatively funded under engine_stress_bound_v1

AND

housing/serviceability rules pass

AND

marginal economic value passes
```

No speculative future production, candidate revenue, or hypothetical land may be used to manufacture the resources that certify the candidate.

## Core Architectural Invariant

> A larger herd target must never create the feed resources used to justify that larger herd target.
