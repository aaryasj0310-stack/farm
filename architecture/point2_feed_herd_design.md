# Point 2 — Feed/Herd Sustainability Final Design

Baseline commit:

`547357a91d22260435e961dedc24f292e846e713`

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

# 7. Feed pricing

Use the authoritative live buffered wheat purchase-price machinery established in Point 1.

Near-term market purchases should use the current executable buffered wheat price.

Remaining-lifetime feed funding should use a conservative wheat replacement-price assumption.

Do not reintroduce hard-coded `$25` feed affordability in:

* DynamicHerdPlan;
* ArmC purchase logic;
* animal_planner feed reserve;
* the new feasibility evaluator.

The implementation should expose which price assumption funded each reservation.

Astra review should not be interpreted as requiring optimistic future-price forecasts.

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

# 13. Storage and execution

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

If execution certainty cannot be established, fail closed for expansion.

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

# Final architectural rule

A livestock candidate is admissible only when:

```text
existing herd remains protected

AND

candidate purchase cash is available

AND

next-4-day feeding is physically/execution feasible

AND

remaining feeding obligation is conservatively funded

AND

housing/serviceability rules pass

AND

marginal economic value passes
```

No speculative future production, candidate revenue, or hypothetical land may be used to manufacture the resources that certify the candidate.
