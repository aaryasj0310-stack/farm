Commit audited: 547357a91d22260435e961dedc24f292e846e713

Purpose:
Document Point 2 Step 1–3 findings before architecture review/implementation.

1. Current architecture
   - compute_authoritative_feed_capacity()
   - min(100, affordable_wheat)
   - season-long sustainable_herd_size
   - DynamicHerdPlan max_sustainable cap
   - live ArmC feed reserve
   - animal_planner feed reserve
   - marginal livestock feed-cost model

2. Verified problems
   - capital insensitivity
   - $10k vs $100k example
   - candidate animals blocked before marginal EV evaluation
   - future wheat timing collapsed into scalar supply
   - speculative planned_yield credit
   - multiple inconsistent feed-feasibility definitions

3. Required invariants
   - existing-herd survival remains strict
   - post-Day12 physical-empty-housing rule unchanged
   - protected feed remains higher priority than land/optional feed
   - no speculative SW feed credit
   - no circular candidate self-financing

4. Proposed architecture
   - split existing-herd survival from marginal expansion feasibility
   - shared rolling feed/cash feasibility evaluator
   - start with 4-day hard horizon
   - prefix/day-by-day wheat timing
   - real/committed wheat + executable market purchases only
   - existing animals get first claim
   - same evaluator used by DynamicHerdPlan and live BUY_ANIMAL
   - marginal_livestock_valuator remains the profitability layer

5. Open questions for Astra
   - 4-day vs dynamic 4–6 day horizon
   - safe future cash receipts
   - whether/when candidate-generated receipts may count
   - repeated market wheat purchase modeling
   - shed turnover/order constraints
   - simpler alternatives