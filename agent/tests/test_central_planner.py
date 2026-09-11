"""Unit and regression tests for CentralPlanner (Phase 3 — Candidate Expansion & Hardened Arbitration).

Verifies:
1. Priority classes P0..P4 hierarchy and deterministic ranking.
2. Candidate set expansion: 8 purchases + 7 sells (15 total), selecting top 10 with excess rejected as slot_cap.
3. MarketBrain exposes full candidate set without 6-slot premature clamping.
4. OrderBuilder exposes all affordable purchases without 10-slot premature drop.
5. Structural validation: malformed candidate rejected as invalid_order without crashing remaining candidates.
6. Proposal identity: deterministic unique IDs (purchase:i, sell:i) tracked through lifecycle.
7. Multiset & proposal ID conservation: multiplicity preserved (multiple HIRE orders never collapse).
8. Capacity-aware execution ordering: tight shed + incoming purchase triggers sell-first execution.
9. Upstream purchase tier ordering strictly preserved within purchase subset.
10. Shed emergency overrides hour 0 purchase priority (P0 sells beat P2 purchases).
11. Feed starvation wheat buy (P0) beats normal profit sells (P3).
12. Hard conflict resolution: P0 feed wheat buy rejects concurrent wheat sell with conflict_with_feed_requirement.
13. Non-conflicting wheat sell: allowed when wheat buy is not critical starvation deficit.
14. Deduplication of accidental duplicate ["BUY_LAND"]: second land buy rejected as duplicate.
15. Day 29 purchase block: BUY_SEED, BUY_LAND, BUY_ANIMAL, BUY_PRODUCT FERTILIZER rejected with endgame_purchase_block.
16. Day 29 wheat buy exception: BUY_PRODUCT WHEAT is NOT blanket blocked on Day 29.
17. Day 29 final liquidation: sells classified as P0_CRITICAL.
18. Invariant: execution reordering never alters the selected proposal set (multiset & proposal_id equality).
19. Invariant: accepted proposal preserves original order payload exactly.
20. Invariant: len(accepted_orders) + len(rejected_orders) == total_candidates.
21. Fallback path: unexpected exception inside CentralPlanner falls back to MarketBrain.compose.
22. Telemetry diagnostics: purchase_candidates, sell_candidates, slot_pressure, upstream_truncation_detected, change_reasons.
23. Crowded cross-engine pressure scenarios:
    - Scenario A: 5 hires/seeds/feed + 3 animal/land + 7 sells
    - Scenario B: critical feed wheat + near-deadline land + animals + shed-pressure sells + normal sells
    - Scenario C: Day 29 + 10 liquidation sells + 4 invalid/non-payoff purchases
    - Scenario D: shed almost full + BUY_ANIMAL + BUY_PRODUCT + multiple sells
24. Full simulation integration with live engine observation.
"""
from __future__ import annotations

from collections import Counter
import copy
import pytest
from config import MAX_MARKET_ORDERS, SHED_CAPACITY, SHED_SOFT_CAP
from market.market_brain import MarketBrain
from market.order_builder import OrderBuilder
from strategy.central_planner import (
    CentralPlanner,
    legacy_compose_market,
    P0_CRITICAL,
    P1_URGENT,
    P2_STRATEGIC,
    P3_NORMAL,
    P4_DISCRETIONARY,
)


class MockTile:
    def __init__(self, pos=(0, 0), is_animal=False, kind="SOIL"):
        self.pos = pos
        self.is_animal = is_animal
        self.kind = kind


class MockFarm:
    def __init__(self, n_animals=0, money=3000):
        self.unlocked = ["NW"]
        self.money = money
        self.tiles = [MockTile(is_animal=True) for _ in range(n_animals)]
        self.hands = []
        self.hires_today = 0

    def iter_tiles(self):
        return iter(self.tiles)


class MockMarket:
    def __init__(self, inventory=None):
        self.inventory = dict(inventory or {"WHEAT": 10000, "MELON": 10000, "CARROT": 10000, "TOMATO": 10000,
                                            "STRAWBERRY": 10000, "EGG": 10000, "MILK": 10000, "WOOL": 10000,
                                            "FERTILIZER": 10000})


class MockPrivate:
    def __init__(self, shed=None, seeds=None):
        self.shed = dict(shed or {})
        self.seeds = dict(seeds or {})


class MockMacroPlan:
    def __init__(self, plant_queue=None, intents=None, diagnostics=None):
        self.plant_queue = plant_queue or []
        self.intents = intents or {}
        self.diagnostics = diagnostics or {}


class MockOppAdvice:
    def __init__(self, preempt_sell=None, delay_sell=None):
        self.preempt_sell = preempt_sell or []
        self.delay_sell = delay_sell or []


class TestCentralPlannerPhase3:
    def setup_method(self):
        self.cp = CentralPlanner()

    # ------------------------------------------------------------------
    # 1. Priority Hierarchy and Deterministic Ranking
    # ------------------------------------------------------------------
    def test_priority_hierarchy_ranking(self):
        """P0 beats P1, P1 beats P2, P2 beats P3, P3 beats P4 regardless of source."""
        ctx = {"hour": 0, "day": 1, "farm": MockFarm(n_animals=2), "private": MockPrivate(shed={"WHEAT": 0})}
        buys = [
            ["BUY_PRODUCT", "FERTILIZER", 2],  # P3
            ["BUY_ANIMAL", "COW", 1],          # P2
            ["HIRE"],                           # P1
            ["BUY_PRODUCT", "WHEAT", 4],        # P0
        ]
        sells = [
            ["SELL", "CARROT", 5],              # P4 (off window at hour 0 without pressure)
        ]
        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)

        # Selection ranks strictly by priority class P0 > P1 > P2 > P3 > P4
        by_selection = sorted(diag["accepted_details"], key=lambda c: c["selection_rank"])
        kinds = [c["kind"] for c in by_selection]
        assert kinds == ["feed_wheat", "hire", "animal", "fertilizer", "sell"]
        assert by_selection[0]["priority_class"] == P0_CRITICAL
        assert by_selection[1]["priority_class"] == P1_URGENT
        assert by_selection[2]["priority_class"] == P2_STRATEGIC
        assert by_selection[3]["priority_class"] == P3_NORMAL
        assert by_selection[4]["priority_class"] == P4_DISCRETIONARY

        # Under slot pressure (cap=3), P0, P1, P2 survive while P3 and P4 are dropped
        orders_3, diag_3 = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=3)
        assert len(orders_3) == 3
        accepted_kinds_3 = {c["kind"] for c in diag_3["accepted_details"]}
        assert accepted_kinds_3 == {"feed_wheat", "hire", "animal"}
        rejected_kinds_3 = {c["kind"] for c in diag_3["rejected_details"]}
        assert "fertilizer" in rejected_kinds_3
        assert "sell" in rejected_kinds_3

    # ------------------------------------------------------------------
    # 2. Candidate Set Expansion: 8 Buys + 7 Sells
    # ------------------------------------------------------------------
    def test_candidate_set_expansion_arbitration(self):
        """CentralPlanner receives all 15 candidates and selects exactly top 10 by priority."""
        ctx = {"hour": 1, "day": 5, "farm": MockFarm(0), "private": MockPrivate()}
        sell_details = {"urgency": 0}  # normal sell window (P3)

        # 8 purchase proposals (P1 hires, P2 seeds/animals)
        buys = [
            ["HIRE"],
            ["HIRE"],
            ["BUY_SEED", "CARROT", 2],
            ["BUY_SEED", "TOMATO", 2],
            ["BUY_SEED", "WHEAT", 4],
            ["BUY_ANIMAL", "COW", 1],
            ["BUY_ANIMAL", "SHEEP", 1],
            ["BUY_PRODUCT", "FERTILIZER", 2],
        ]
        # 7 sell proposals (P3 normal profit sales)
        sells = [
            ["SELL", "WHEAT", 5],
            ["SELL", "CARROT", 4],
            ["SELL", "TOMATO", 3],
            ["SELL", "STRAWBERRY", 2],
            ["SELL", "MELON", 1],
            ["SELL", "EGG", 4],
            ["SELL", "MILK", 3],
        ]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, sell_details, cap=10)

        assert diag["total_candidates"] == 15
        assert diag["purchase_candidates"] == 8
        assert diag["sell_candidates"] == 7
        assert diag["final_selected"] == 10
        assert diag["slot_pressure"] is True
        assert len(orders) == 10
        assert len(diag["rejected_orders"]) == 5
        assert diag["rejection_reasons"].get("slot_cap") == 5

    # ------------------------------------------------------------------
    # 3. MarketBrain Candidate Exposure with max_slots=None
    # ------------------------------------------------------------------
    def test_market_brain_untruncated_proposals(self):
        """MarketBrain with max_slots=None does not clamp to 6 slots when stock exists across products."""
        ctx = {
            "day": 5, "hour": 1,  # normal sell window
            "farm": MockFarm(0),
            "private": MockPrivate(shed={
                "WHEAT": 20, "CARROT": 20, "TOMATO": 20, "STRAWBERRY": 20,
                "MELON": 20, "EGG": 20, "MILK": 20, "WOOL": 20, "FERTILIZER": 20
            }),
            "market": MockMarket(),
        }
        brain = MarketBrain(None)
        orders, details = brain.sell_orders(ctx, max_slots=None)

        # Should generate proposals for many products (> 6), not artificially clamped to 6
        assert len(orders) >= 7, f"Expected >=7 sell proposals, got {len(orders)}"
        assert details.get("upstream_truncation") is False

    # ------------------------------------------------------------------
    # 4. OrderBuilder Candidate Exposure with max_slots=None
    # ------------------------------------------------------------------
    def test_order_builder_untruncated_proposals(self):
        """OrderBuilder with max_slots=None emits all affordable purchases without 10-order cap."""
        ctx = {
            "day": 1, "hour": 0,
            "farm": MockFarm(0, money=10000),  # plenty of money
            "private": MockPrivate(shed={}),
            "market": MockMarket(),
        }
        builder = OrderBuilder()
        intents = {
            "hire": 6,
            "buy_wheat": 10,
            "buy_seed": {"WHEAT": 5, "CARROT": 5, "TOMATO": 5, "STRAWBERRY": 5},
        }
        orders, ledger = builder.build(ctx, intents, max_slots=None)

        # 6 hires + 1 wheat + 4 seeds = 11 orders (exceeds 10)
        assert len(orders) >= 11, f"Expected >=11 orders, got {len(orders)}"
        assert ledger.get("upstream_slots_limited") is False

    # ------------------------------------------------------------------
    # 5. Structural Proposal Validation (Fails Closed per Candidate)
    # ------------------------------------------------------------------
    def test_malformed_proposals_rejected_without_crashing_planner(self):
        """Malformed proposals are rejected individually as invalid_order without breaking valid candidates."""
        ctx = {"hour": 0, "day": 1}
        buys = [
            ["HIRE"],                               # valid
            ["INVALID_OPCODE", 123],                # invalid opcode
            ["BUY_SEED", "UNKNOWN_CROP", 5],        # unknown crop
            ["BUY_ANIMAL", "COW", -2],              # negative quantity
            ["BUY_SEED", "MELON", 3],               # valid
        ]
        sells = [
            ["SELL", "WHEAT", 0],                   # zero quantity
            ["SELL", "UNKNOWN_PROD", 4],            # unknown product
            ["SELL", "CARROT", 5],                  # valid
            [],                                     # empty list
        ]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)

        # Valid orders: ["HIRE"], ["BUY_SEED", "MELON", 3], ["SELL", "CARROT", 5]
        assert len(orders) == 3
        assert ["HIRE"] in orders
        assert ["BUY_SEED", "MELON", 3] in orders
        assert ["SELL", "CARROT", 5] in orders

        # 6 invalid candidates rejected
        assert diag["rejection_reasons"].get("invalid_order") == 6
        assert "invalid_order_filter" in diag["change_reasons"]

    # ------------------------------------------------------------------
    # 6. Proposal Identity Lifecycle Tracking
    # ------------------------------------------------------------------
    def test_proposal_identity_tracking(self):
        """Every proposal receives a deterministic proposal_id tracked through accepted/rejected details."""
        ctx = {"hour": 0, "day": 1}
        buys = [["HIRE"], ["BUY_SEED", "WHEAT", 2]]
        sells = [["SELL", "MELON", 1]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=2)
        # 3 candidates, cap=2 -> 2 accepted, 1 rejected
        accepted_ids = [c["proposal_id"] for c in diag["accepted_details"]]
        rejected_ids = [c["proposal_id"] for c in diag["rejected_details"]]

        assert len(accepted_ids) == 2
        assert len(rejected_ids) == 1
        all_ids = set(accepted_ids + rejected_ids)
        assert all_ids == {"purchase:0", "purchase:1", "sell:0"}

    # ------------------------------------------------------------------
    # 7. Multiset & Proposal ID Conservation Invariant
    # ------------------------------------------------------------------
    def test_multiset_and_proposal_id_conservation(self):
        """Multiple identical orders preserve multiplicity and match multiset before/after reordering."""
        ctx = {"hour": 0, "day": 1}
        buys = [["HIRE"], ["HIRE"], ["HIRE"], ["HIRE"]]
        sells = [["SELL", "MELON", 2]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)

        # Multiplicity must NOT collapse
        hire_count = sum(1 for o in orders if o == ["HIRE"])
        assert hire_count == 4

        # Proposal IDs accounted for
        accounted_ids = [c["proposal_id"] for c in diag["accepted_details"]] + [c["proposal_id"] for c in diag["rejected_details"]]
        assert len(accounted_ids) == 5
        assert len(set(accounted_ids)) == 5

    # ------------------------------------------------------------------
    # 8. Capacity-Aware Execution Ordering (Tight Shed + Purchases)
    # ------------------------------------------------------------------
    def test_capacity_aware_execution_ordering(self):
        """When shed capacity is tight and selected purchases add units, freeing sells execute first."""
        # Shed has 96 units (capacity is 100).
        # We buy 1 COW (takes 1 slot) and 5 WHEAT (takes 5 slots) -> 96 + 6 = 102 (exceeds 100!).
        # We sell 10 CARROT -> frees 10 slots.
        ctx = {
            "hour": 0, "day": 10,
            "farm": MockFarm(0),
            "private": MockPrivate(shed={"MELON": 96}),
        }
        buys = [
            ["BUY_ANIMAL", "COW", 1],
            ["BUY_PRODUCT", "WHEAT", 5],
        ]
        sells = [
            ["SELL", "CARROT", 10],
        ]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)

        # Even at hour 0 (where purchases normally go first), the capacity hazard forces sells first!
        assert orders[0] == ["SELL", "CARROT", 10]
        assert orders[1:] == [["BUY_ANIMAL", "COW", 1], ["BUY_PRODUCT", "WHEAT", 5]]
        assert diag["shed_overflow_risk"] is True
        assert diag["emergency_execution"] is True

    # ------------------------------------------------------------------
    # 9. Upstream Purchase Ordering Preserved Within Purchase Subset
    # ------------------------------------------------------------------
    def test_upstream_purchase_tier_order_strictly_preserved(self):
        """Within the accepted purchases, OrderBuilder's emitted relative order is strictly preserved."""
        ctx = {"hour": 0, "day": 1}
        # Emitted in order: HIRE, BUY_LAND, BUY_SEED, BUY_ANIMAL
        buys = [
            ["HIRE"],
            ["BUY_LAND"],
            ["BUY_SEED", "CARROT", 5],
            ["BUY_ANIMAL", "COW", 1],
        ]
        sells = [["SELL", "MELON", 2]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        accepted_buys = [o for o in orders if o[0] != "SELL"]
        assert accepted_buys == buys

    # ------------------------------------------------------------------
    # 10. Shed Emergency Overrides Hour 0 Purchase Priority
    # ------------------------------------------------------------------
    def test_shed_emergency_overrides_hour0_purchase_priority(self):
        """Under shed pressure, P0 emergency sells take precedence over P2 purchases at hour 0."""
        ctx = {"hour": 0, "day": 10, "farm": MockFarm(0), "private": MockPrivate(shed={"MELON": SHED_SOFT_CAP + 5})}
        sell_details = {"pressure": True, "reason": "shed_pressure"}

        buys = [
            ["BUY_ANIMAL", "COW", 1],
            ["BUY_LAND"],
        ]
        sells = [
            ["SELL", "MELON", 10],
        ]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, sell_details, cap=2)
        assert orders[0] == ["SELL", "MELON", 10]
        assert diag["accepted_details"][0]["priority_class"] == P0_CRITICAL

    # ------------------------------------------------------------------
    # 11. Feed Starvation Wheat Buy Beats Normal Sells
    # ------------------------------------------------------------------
    def test_feed_starvation_wheat_buy_beats_normal_sells(self):
        """P0 starvation feed wheat buy beats P3 normal profit sells at non-hour 0."""
        ctx = {"hour": 1, "day": 10, "farm": MockFarm(n_animals=4), "private": MockPrivate(shed={"WHEAT": 0})}
        sell_details = {"urgency": 0}

        buys = [["BUY_PRODUCT", "WHEAT", 4]]
        sells = [["SELL", "MELON", 5]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, sell_details, cap=1)
        assert len(orders) == 1
        assert orders[0] == ["BUY_PRODUCT", "WHEAT", 4]
        assert diag["accepted_details"][0]["priority_class"] == P0_CRITICAL

    # ------------------------------------------------------------------
    # 12. Hard Conflict: Feed Wheat Buy Rejects Wheat Sell
    # ------------------------------------------------------------------
    def test_hard_conflict_critical_wheat_buy_rejects_wheat_sell(self):
        """Critical starvation wheat buy immediately rejects concurrent SELL WHEAT."""
        ctx = {"hour": 1, "day": 5, "farm": MockFarm(n_animals=3), "private": MockPrivate(shed={"WHEAT": 0})}
        buys = [["BUY_PRODUCT", "WHEAT", 5]]
        sells = [["SELL", "WHEAT", 2], ["SELL", "CARROT", 3]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert diag["rejection_reasons"].get("conflict_with_feed_requirement") == 1
        assert "conflict_resolution" in diag["change_reasons"]

    # ------------------------------------------------------------------
    # 13. Non-Conflicting Wheat Sell Allowed
    # ------------------------------------------------------------------
    def test_non_conflicting_wheat_sell_allowed(self):
        """When there is no critical wheat buy, wheat sell is accepted normally."""
        ctx = {"hour": 1, "day": 5, "farm": MockFarm(n_animals=0), "private": MockPrivate(shed={"WHEAT": 20})}
        buys = []
        sells = [["SELL", "WHEAT", 5]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert orders == [["SELL", "WHEAT", 5]]
        assert "conflict_with_feed_requirement" not in diag["rejection_reasons"]

    # ------------------------------------------------------------------
    # 14. Deduplication of Accidental Duplicate BUY_LAND
    # ------------------------------------------------------------------
    def test_deduplication_of_accidental_duplicate_land(self):
        """Two BUY_LAND orders in the same turn: only first kept, second rejected as duplicate."""
        ctx = {"hour": 0, "day": 5}
        buys = [["BUY_LAND"], ["BUY_LAND"]]
        sells = []

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert len(orders) == 1
        assert orders == [["BUY_LAND"]]
        assert diag["rejection_reasons"].get("duplicate") == 1

    # ------------------------------------------------------------------
    # 15. Day 29 Purchase Block
    # ------------------------------------------------------------------
    def test_day29_purchase_block(self):
        """On Day 29, BUY_SEED, BUY_LAND, BUY_ANIMAL, and BUY_PRODUCT FERTILIZER are blocked."""
        ctx = {"hour": 0, "day": 29}
        buys = [
            ["BUY_SEED", "CARROT", 5],
            ["BUY_LAND"],
            ["BUY_ANIMAL", "COW", 1],
            ["BUY_PRODUCT", "FERTILIZER", 2],
        ]
        sells = [["SELL", "MELON", 10]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert orders == [["SELL", "MELON", 10]]
        assert diag["rejection_reasons"].get("endgame_purchase_block") == 4
        assert "endgame_block" in diag["change_reasons"]

    # ------------------------------------------------------------------
    # 16. Day 29 Wheat Buy Exception
    # ------------------------------------------------------------------
    def test_day29_wheat_buy_exception(self):
        """BUY_PRODUCT WHEAT is NOT blocked by endgame_purchase_block on Day 29."""
        ctx = {"hour": 0, "day": 29, "farm": MockFarm(n_animals=2), "private": MockPrivate(shed={"WHEAT": 0})}
        buys = [["BUY_PRODUCT", "WHEAT", 2]]
        sells = [["SELL", "MELON", 5]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert ["BUY_PRODUCT", "WHEAT", 2] in orders
        assert "endgame_purchase_block" not in diag["rejection_reasons"]

    # ------------------------------------------------------------------
    # 17. Day 29 Final Liquidation P0
    # ------------------------------------------------------------------
    def test_day29_final_liquidation_p0(self):
        """On Day 29, all sells are classified as P0_CRITICAL."""
        ctx = {"hour": 5, "day": 29}
        buys = []
        sells = [["SELL", "MELON", 10], ["SELL", "WOOL", 5]]

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert len(orders) == 2
        for c in diag["accepted_details"]:
            assert c["priority_class"] == P0_CRITICAL

    # ------------------------------------------------------------------
    # 18. Fallback on Exception
    # ------------------------------------------------------------------
    def test_fallback_on_exception(self, monkeypatch):
        """When CentralPlanner raises unexpectedly, it falls back to MarketBrain.compose."""
        ctx = {"hour": 0, "day": 1}
        buys = [["HIRE"]]
        sells = [["SELL", "MELON", 2]]

        def broken_core(*args, **kwargs):
            raise RuntimeError("Simulated internal fault")

        monkeypatch.setattr(self.cp, "_plan_market_core", broken_core)
        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)

        legacy = MarketBrain.compose(buys, sells, purchases_first=True)
        assert orders == legacy
        assert diag["fallback_used"] is True
        assert "Simulated internal fault" in diag["error"]

    # ------------------------------------------------------------------
    # 19. Crowded Cross-Engine Scenarios (Scenarios A, B, C, D)
    # ------------------------------------------------------------------
    def test_crowded_scenario_a(self):
        """Scenario A: 5 hires/seeds/feed + 3 animal/land + 7 sells (15 total candidates)."""
        ctx = {"hour": 0, "day": 5, "farm": MockFarm(0), "private": MockPrivate(shed={"MELON": 20})}
        buys = [
            ["HIRE"],                                   # P1
            ["HIRE"],                                   # P1
            ["BUY_SEED", "CARROT", 5],                  # P2
            ["BUY_PRODUCT", "WHEAT", 10],               # P2
            ["BUY_SEED", "TOMATO", 3],                  # P2
            ["BUY_ANIMAL", "COW", 1],                   # P2
            ["BUY_ANIMAL", "SHEEP", 1],                 # P2
            ["BUY_LAND"],                               # P2
        ]
        sells = [
            ["SELL", "MELON", 3],                       # P4 (hour 0 without pressure)
            ["SELL", "CARROT", 4],                      # P4
            ["SELL", "TOMATO", 2],                      # P4
            ["SELL", "EGG", 3],                         # P4
            ["SELL", "MILK", 2],                        # P4
            ["SELL", "WOOL", 1],                        # P4
            ["SELL", "FERTILIZER", 5],                  # P4
        ]
        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert len(orders) == 10
        assert diag["total_candidates"] == 15
        assert diag["slot_pressure"] is True
        # All 8 purchases (P1, P2) should be accepted, along with top 2 sells (P4)
        accepted_sources = [c["source"] for c in diag["accepted_details"]]
        assert accepted_sources.count("purchase") == 8
        assert accepted_sources.count("sell") == 2

    def test_crowded_scenario_b(self):
        """Scenario B: Critical feed wheat + near-deadline land + animals + shed-pressure sells + normal sells."""
        ctx = {"hour": 1, "day": 19, "farm": MockFarm(n_animals=3), "private": MockPrivate(shed={"WHEAT": 0, "MELON": 70})}
        sell_details = {"pressure": True, "reason": "shed_pressure"}

        buys = [
            ["BUY_PRODUCT", "WHEAT", 5],                # P0 (starvation)
            ["BUY_LAND"],                               # P1 (near deadline Day 19)
            ["BUY_ANIMAL", "COW", 1],                   # P2
            ["BUY_SEED", "CARROT", 3],                  # P2
        ]
        sells = [
            ["SELL", "MELON", 10],                      # P0 (shed pressure)
            ["SELL", "CARROT", 5],                      # P0 (shed pressure)
            ["SELL", "TOMATO", 4],                      # P0 (shed pressure)
            ["SELL", "EGG", 2],                         # P0 (shed pressure)
            ["SELL", "MILK", 2],                        # P0 (shed pressure)
            ["SELL", "WOOL", 2],                        # P0 (shed pressure)
        ]
        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, sell_details, cap=7)
        # Cap is 7. Top candidates: P0 feed wheat buy (1) + P0 sells (6) = 7. All P0 orders must be accepted!
        accepted_kinds = [c["kind"] for c in diag["accepted_details"]]
        assert "feed_wheat" in accepted_kinds
        for c in diag["accepted_details"]:
            assert c["priority_class"] == P0_CRITICAL

    def test_crowded_scenario_c(self):
        """Scenario C: Day 29 + 10 liquidation sells + 4 invalid/non-payoff purchases."""
        ctx = {"hour": 1, "day": 29}
        buys = [
            ["BUY_LAND"],                               # blocked
            ["BUY_SEED", "CARROT", 5],                  # blocked
            ["BUY_ANIMAL", "COW", 1],                   # blocked
            ["BUY_PRODUCT", "FERTILIZER", 4],           # blocked
        ]
        sells = [["SELL", f"PROD_{i}", 2] for i in range(10)]
        for s in sells:
            s[1] = "MELON"  # make it a valid product

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert len(orders) == 10
        for o in orders:
            assert o[0] == "SELL"
        assert diag["rejection_reasons"].get("endgame_purchase_block") == 4

    def test_crowded_scenario_d(self):
        """Scenario D: Shed almost full + BUY_ANIMAL + BUY_PRODUCT + multiple sells."""
        ctx = {
            "hour": 0, "day": 12,
            "farm": MockFarm(0),
            "private": MockPrivate(shed={"MELON": 95}),
        }
        buys = [
            ["BUY_ANIMAL", "COW", 2],                   # 2 units into shed
            ["BUY_PRODUCT", "WHEAT", 6],                # 6 units into shed (total 95 + 8 = 103 > 100)
        ]
        sells = [
            ["SELL", "MELON", 10],                      # frees 10 units
            ["SELL", "MELON", 10],                      # frees 10 units
        ]
        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        # Capacity hazard -> sells MUST execute before purchases
        assert orders[0][0] == "SELL"
        assert orders[1][0] == "SELL"
        assert orders[2][0] == "BUY_ANIMAL"
        assert orders[3][0] == "BUY_PRODUCT"
        assert diag["shed_overflow_risk"] is True

    # ------------------------------------------------------------------
    # 20. Live Engine Integration
    # ------------------------------------------------------------------
    def test_agent_main_integration_with_central_planner(self):
        """Verify main._agent_decision executes with real observation using CentralPlanner."""
        import kaggle_environments
        from main import _agent_decision, get_central_planner_diagnostics
        env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": 42})
        env.reset(2)
        obs = env.state[0].observation
        res = _agent_decision(obs)
        assert "market" in res
        assert isinstance(res["market"], list)
        diag = get_central_planner_diagnostics()
        assert isinstance(diag, dict)
        assert "total_candidates" in diag
        assert "purchase_candidates" in diag
        assert "sell_candidates" in diag
        assert "slot_pressure" in diag

    # ------------------------------------------------------------------
    # 21. Historical Legacy Compose Semantics
    # ------------------------------------------------------------------
    def test_legacy_compose_market_semantics(self):
        """Verify authoritative historical legacy semantics across hours 0, 1, and 2+."""
        buys = [["BUY_SEED", "WHEAT", 5], ["BUY_LAND"]]
        sells = [["SELL", "MELON", 10], ["SELL", "CARROT", 4]]

        # Hour 0: purchases first
        res_h0 = legacy_compose_market(buys, sells, {"hour": 0}, cap=3)
        assert res_h0 == [["BUY_SEED", "WHEAT", 5], ["BUY_LAND"], ["SELL", "MELON", 10]]

        # Hour 1: purchases first (critical historical parity)
        res_h1 = legacy_compose_market(buys, sells, {"hour": 1}, cap=3)
        assert res_h1 == [["BUY_SEED", "WHEAT", 5], ["BUY_LAND"], ["SELL", "MELON", 10]]

        # Hour 2: sells first
        res_h2 = legacy_compose_market(buys, sells, {"hour": 2}, cap=3)
        assert res_h2 == [["SELL", "MELON", 10], ["SELL", "CARROT", 4], ["BUY_SEED", "WHEAT", 5]]

        # Hour 23: sells first
        res_h23 = legacy_compose_market(buys, sells, {"hour": 23}, cap=3)
        assert res_h23 == [["SELL", "MELON", 10], ["SELL", "CARROT", 4], ["BUY_SEED", "WHEAT", 5]]

    # ------------------------------------------------------------------
    # 22. Strict Proposal Structural Validation
    # ------------------------------------------------------------------
    def test_strict_proposal_validation_shapes(self):
        """Reject malformed candidate shapes fail-closed while valid proposals proceed."""
        ctx = {"hour": 0, "day": 10, "farm": MockFarm(0), "private": MockPrivate()}
        malformed_buys = [
            ["HIRE", 1],                          # invalid: HIRE must have len 1
            ["BUY_LAND", "SW"],                   # invalid: BUY_LAND must have len 1
            ["BUY_SEED"],                         # invalid: BUY_SEED must have len 3
            ["BUY_SEED", "WHEAT"],                # invalid: BUY_SEED missing qty
            ["BUY_SEED", "WHEAT", 5, "extra"],    # invalid: extra args
            ["BUY_SEED", "WHEAT", -2],            # invalid: negative qty
            ["BUY_SEED", "WHEAT", True],          # invalid: boolean qty
            ["BUY_ANIMAL", "COW"],                # invalid: missing qty
            ["BUY_PRODUCT", "WHEAT"],             # invalid: missing qty
            ["BUY_SEED", "WHEAT", 4],             # VALID
        ]
        malformed_sells = [
            ["SELL", "CARROT"],                   # invalid: missing qty
            ["SELL", "CARROT", "all"],            # invalid: non-int qty
            ["SELL", "CARROT", 0],                # invalid: non-positive qty
            ["SELL", "CARROT", False],            # invalid: boolean qty
            ["SELL", "CARROT", 3],                # VALID
        ]

        orders, diag = self.cp.plan_market(ctx, None, malformed_buys, None, malformed_sells, None, cap=10)
        assert len(orders) == 2
        assert ["BUY_SEED", "WHEAT", 4] in orders
        assert ["SELL", "CARROT", 3] in orders
        assert diag["total_candidates"] == len(malformed_buys) + len(malformed_sells)
        assert diag["rejection_reasons"].get("invalid_order") == 13

    # ------------------------------------------------------------------
    # 23. Fallback Conservation & Accounting
    # ------------------------------------------------------------------
    def test_fallback_exception_accounting(self, monkeypatch):
        """When arbitration raises, fallback strictly accounts for all candidates."""
        ctx = {"hour": 1, "day": 5, "farm": MockFarm(0), "private": MockPrivate()}
        buys = [["BUY_SEED", f"CROP_{i}", 1] for i in range(6)]
        sells = [["SELL", f"PROD_{i}", 1] for i in range(6)]
        total = len(buys) + len(sells)

        def bad_plan(*args, **kwargs):
            raise RuntimeError("Arbitration exploded")

        monkeypatch.setattr(self.cp, "_plan_market_core", bad_plan)

        orders, diag = self.cp.plan_market(ctx, None, buys, None, sells, None, cap=10)
        assert diag["fallback_used"] is True
        assert diag["fallback_reason"] == "central_planner_exception"
        assert diag["planner_error"] == "Arbitration exploded"
        assert len(orders) == 10
        assert len(diag["accepted_orders"]) == 10
        assert len(diag["rejected_orders"]) == 2
        assert len(diag["accepted_orders"]) + len(diag["rejected_orders"]) == total
        assert diag["rejection_reasons"] == {"fallback_slot_cap": 2}
        assert diag["selection_changed_from_legacy"] is False
        assert diag["execution_order_only_changed"] is False

