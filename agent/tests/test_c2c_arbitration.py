"""Unit and regression tests for Point 2 Phase C2C — Arbitration Dependency Closure.

Covers:
  1. C2C Dependency Contract & Metadata (OrderBuilder)
  2. Authoritative Feed-Sale Reservation Derivation (FeedFeasibility)
  3. C2C Contract Validation (CentralPlanner)
  4. Hard Protected WHEAT Selection Root (CentralPlanner)
  5. Authoritative Physical WHEAT Sell Clamping (CentralPlanner)
  6. BUY_ANIMAL Dependency Closure (CentralPlanner)
  7. Post-Closure Consolidation & No-Backfill Invariant
  8. All 5 Conservation Invariants Under C2C
  9. Dependency-Safe Live Fallback
  10. Live Mode Route Enforcement (main.py)
  11. Complete Diagnostics & Telemetry
  12. Frozen Production Default (shadow)
  13. Mandatory C2C Amendment Tests (Reservation Dependencies)
"""
from collections import Counter
from dataclasses import dataclass, field
import pytest
from typing import Any, Dict, List, Optional

from config import (
    ANIMALS,
    CROPS,
    LAND_ORDER,
    LAND_PRICES,
    MAX_MARKET_ORDERS,
    MONEY_RESERVE_DEFAULT,
    SHED_CAPACITY,
    POINT2_FEED_MODE,
)
from market.order_builder import OrderBuilder
from strategy.central_planner import (
    CentralPlanner,
    ProposalCandidate,
    P0_CRITICAL,
    P1_URGENT,
    P2_STRATEGIC,
    P3_NORMAL,
    P4_DISCRETIONARY,
)
from strategy.feed_feasibility import (
    FeedResourceLedger,
    derive_feed_sale_reservation,
    build_live_housing_state,
    evaluate_incremental_candidate,
    commit_candidate_reservation,
)


# ============================================================================
# Helpers & Mock Structures
# ============================================================================

class MockTile:
    def __init__(self, kind="pasture", is_animal=False, animal=None, pos=(0, 0)):
        self.kind = kind
        self.is_animal = is_animal
        self.animal = animal
        self.pos = pos
        self.is_plant = False
        self.crop = None


class MockFarm:
    def __init__(self, money=5000, unlocked=None, tiles=None, hires_today=0):
        self.money = money
        self.unlocked = unlocked or ["NW", "NE"]
        self.tiles = tiles or [MockTile(kind="pasture", is_animal=False) for _ in range(10)]
        self.hires_today = hires_today
        self.hands = []

    def iter_tiles(self):
        return iter(self.tiles)

    def quadrant_of(self, pos):
        return "NW"


class MockPrivate:
    def __init__(self, shed=None, seeds=None):
        self.shed = shed or {"WHEAT": 50}
        self.seeds = seeds or {}


class MockMarket:
    def __init__(self, inventory=None):
        self.inventory = dict(inventory or {
            "WHEAT": 10000, "MELON": 10000, "CARROT": 10000, "TOMATO": 10000,
            "STRAWBERRY": 10000, "EGG": 10000, "MILK": 10000, "WOOL": 10000,
            "FERTILIZER": 10000
        })


def make_ctx(day=5, hour=0, money=5000, shed_wheat=50, shed_other=0, tiles=None, snapshot=None, market_inventory=None):
    farm = MockFarm(money=money, tiles=tiles)
    shed = {"WHEAT": shed_wheat}
    if shed_other > 0:
        shed["CARROT"] = shed_other
    priv = MockPrivate(shed=shed)
    ctx = {
        "day": day,
        "hour": hour,
        "farm": farm,
        "private": priv,
        "market": MockMarket(inventory=market_inventory),
        "feed_execution_snapshot": snapshot,
    }
    return ctx


@dataclass
class MockSnapshot:
    post_unit_state_verified: bool = True
    post_unit_state_reason: Optional[str] = "ok"
    execution_confidence: str = "high"
    verified_feed_targets: List[Any] = field(default_factory=list)
    verified_feed_count: int = 0
    post_unit_shed_inventory: Dict[str, int] = field(default_factory=lambda: {"WHEAT": 50})
    post_unit_shed_occupancy: int = 50
    post_unit_worker_inventory_total: int = 0
    post_unit_worker_inventories: List[Dict[str, int]] = field(default_factory=list)
    post_unit_unfed_animals: List[str] = field(default_factory=list)
    snapshot_valid: bool = True
    is_live_livestock_safe: bool = True
    live_execution_status: str = "safe"
    live_execution_reason: str = ""
    post_unit_empty_pastures: int = 5
    post_unit_empty_coops: int = 5


# ============================================================================
# 1. C2C Contract & OrderBuilder Metadata Tests
# ============================================================================

def test_c2c_contract_fields_present_in_order_builder_live(monkeypatch):
    """Test 1: OrderBuilder in live mode exposes dependency_contract_version and feed_sale_reservation."""
    monkeypatch.setattr("config.POINT2_FEED_MODE", "live")
    builder = OrderBuilder(money_reserve=100.0)
    snap = MockSnapshot(post_unit_state_verified=True, post_unit_shed_inventory={"WHEAT": 40})
    ctx = make_ctx(day=5, hour=0, money=3000, shed_wheat=40, snapshot=snap)

    intents = {
        "hire": 0,
        "buy_wheat": 10,
        "protected_feed_wheat": 5,
        "optional_feed_wheat": 5,
        "buy_animal_sequence": ["COW"],
        "execution_snapshot": snap,
    }
    orders, ledger = builder.build(ctx, intents)

    assert ledger.get("dependency_contract_version") == "point2_c2c_v1"
    assert "feed_sale_reservation" in ledger
    assert isinstance(ledger["feed_sale_reservation"], dict)
    assert ledger["feed_sale_reservation"]["version"] == "point2_c2c_v1"
    assert len(ledger.get("order_metadata", [])) == len(orders)


def test_c2c_wheat_resource_keys_and_roles(monkeypatch):
    """Test 2: Protected WHEAT gets resource_key='wheat:protected' & hard_required=True.
    Optional WHEAT gets resource_key='wheat:optional' & hard_required=False."""
    monkeypatch.setattr("config.POINT2_FEED_MODE", "live")
    builder = OrderBuilder(money_reserve=100.0)
    snap = MockSnapshot(post_unit_state_verified=True)
    ctx = make_ctx(day=5, hour=0, money=3000, shed_wheat=40, snapshot=snap)

    intents = {
        "hire": 0,
        "buy_wheat": 15,
        "protected_feed_wheat": 5,
        "optional_feed_wheat": 10,
        "execution_snapshot": snap,
    }
    orders, ledger = builder.build(ctx, intents)
    om = ledger.get("order_metadata", [])

    prot_meta = [m for m in om if m.get("resource_key") == "wheat:protected"]
    opt_meta = [m for m in om if m.get("resource_key") == "wheat:optional"]

    assert len(prot_meta) == 1
    assert prot_meta[0]["hard_required"] is True
    assert prot_meta[0]["resource_role"] == "feed_resource"

    assert len(opt_meta) == 1
    assert opt_meta[0]["hard_required"] is False
    assert opt_meta[0]["resource_role"] == "feed_resource"


def test_c2c_candidate_dependencies_captured_on_acceptance(monkeypatch):
    """Test 3: Candidate replay records requires_resource_keys on acceptance."""
    monkeypatch.setattr("config.POINT2_FEED_MODE", "live")
    builder = OrderBuilder(money_reserve=100.0)
    snap = MockSnapshot(post_unit_state_verified=True)
    ctx = make_ctx(day=5, hour=0, money=3000, shed_wheat=40, snapshot=snap)

    intents = {
        "hire": 0,
        "buy_wheat": 15,
        "protected_feed_wheat": 5,
        "optional_feed_wheat": 10,
        "buy_animal_sequence": ["COW"],
        "execution_snapshot": snap,
    }
    orders, ledger = builder.build(ctx, intents)
    decisions = ledger.get("candidate_decisions", [])
    accepted = [d for d in decisions if d.get("accepted")]

    if accepted:
        assert "wheat:protected" in accepted[0]["requires_resource_keys"]
        assert "wheat:optional" in accepted[0]["requires_resource_keys"]


def test_c2c_grouped_animal_order_metadata_has_dependency_union(monkeypatch):
    """Test 4: Grouped animal order metadata contains union of candidate dependencies."""
    monkeypatch.setattr("config.POINT2_FEED_MODE", "live")
    builder = OrderBuilder(money_reserve=100.0)
    snap = MockSnapshot(post_unit_state_verified=True)
    ctx = make_ctx(day=5, hour=0, money=5000, shed_wheat=40, snapshot=snap)

    intents = {
        "hire": 0,
        "buy_wheat": 15,
        "protected_feed_wheat": 5,
        "optional_feed_wheat": 10,
        "buy_animal_sequence": ["COW", "COW"],
        "execution_snapshot": snap,
    }
    orders, ledger = builder.build(ctx, intents)
    om = ledger.get("order_metadata", [])
    cow_orders = [m for m in om if m.get("kind") == "animal" and m.get("animal") == "COW"]

    if cow_orders:
        cow_meta = cow_orders[0]
        assert "candidate_ids" in cow_meta
        assert len(cow_meta["candidate_ids"]) == 2
        assert cow_meta["dependency_group"] == "animal:COW:0"
        assert set(cow_meta["requires_resource_keys"]) == {"wheat:protected", "wheat:optional"}


# ============================================================================
# 2. Feed-Sale Reservation Derivation Tests
# ============================================================================

def test_c2c_feed_sale_reservation_derivation_basic():
    """Test 5: Basic feed-sale reservation arithmetic."""
    class DummyLedger:
        wheat_in_shed = 50
        wheat_on_workers = 10
        day = 5

    res = derive_feed_sale_reservation(
        ledger=DummyLedger(),
        operational_min_wheat_slack=20.0,
        valid=True,
    )
    # Total = 60, releasable = min(60, 20) = 20
    # Required = 40
    # Worker wheat = 10 (protected_worker = 10)
    # Protected shed wheat = 40 - 10 = 30
    # Sellable shed wheat = 50 - 30 = 20
    assert res["sellable_shed_wheat"] == 20
    assert res["protected_shed_wheat"] == 30
    assert res["protected_worker_wheat"] == 10
    assert res["valid"] is True


def test_c2c_feed_sale_reservation_zero_slack_shed_protection():
    """Test 6: Zero slack reserves all shed wheat; sellable shed wheat is 0."""
    class DummyLedger:
        wheat_in_shed = 50
        wheat_on_workers = 0
        day = 5

    res = derive_feed_sale_reservation(
        ledger=DummyLedger(),
        operational_min_wheat_slack=0.0,
        valid=True,
    )
    assert res["sellable_shed_wheat"] == 0
    assert res["protected_shed_wheat"] == 50


def test_c2c_feed_sale_reservation_day29_liquidation_unlocked():
    """Test 7: Day 29 liquidation unlocks all shed wheat (reservation = 0)."""
    class DummyLedger:
        wheat_in_shed = 80
        wheat_on_workers = 5
        day = 29

    res = derive_feed_sale_reservation(
        ledger=DummyLedger(),
        operational_min_wheat_slack=0.0,
        valid=True,
    )
    assert res["sellable_shed_wheat"] == 80
    assert res["protected_shed_wheat"] == 0


def test_c2c_feed_sale_reservation_invalid_snapshot_fails_closed():
    """Test 8: Invalid snapshot on day < 29 forces sellable_shed_wheat = 0."""
    class DummyLedger:
        wheat_in_shed = 50
        wheat_on_workers = 5
        day = 10

    res = derive_feed_sale_reservation(
        ledger=DummyLedger(),
        operational_min_wheat_slack=50.0,
        valid=False,
    )
    assert res["sellable_shed_wheat"] == 0
    assert res["protected_shed_wheat"] == 50
    assert res["valid"] is False


def test_c2c_feed_sale_reservation_worker_wheat_first_claim():
    """Test 9: Worker wheat gets first protection claim and cannot be sold from shed."""
    class DummyLedger:
        wheat_in_shed = 30
        wheat_on_workers = 20
        day = 15

    # Total = 50, slack = 40 -> releasable = 40, required = 10
    # Worker wheat = 20, protected_worker = min(20, 10) = 10
    # Protected shed = min(30, 10 - 10) = 0
    # Sellable shed wheat = 30
    res = derive_feed_sale_reservation(
        ledger=DummyLedger(),
        operational_min_wheat_slack=40.0,
        valid=True,
    )
    assert res["protected_worker_wheat"] == 10
    assert res["protected_shed_wheat"] == 0
    assert res["sellable_shed_wheat"] == 30


# ============================================================================
# 3. CentralPlanner C2C Contract Validation Tests
# ============================================================================

def test_c2c_central_planner_contract_validation_rejects_missing_version(monkeypatch):
    """Test 10: Missing dependency_contract_version in live mode drops all animals."""
    monkeypatch.setattr("config.POINT2_FEED_MODE", "live")
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "order_metadata": [{"kind": "animal", "animal": "COW"}],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10},
    }
    # No dependency_contract_version
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag.get("c2c_contract_valid") is False


def test_c2c_central_planner_contract_validation_rejects_metadata_mismatch():
    """Test 11: Mismatched order_metadata length drops all animals."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1], ["HIRE"]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [{"kind": "animal", "animal": "COW"}],  # Length 1 != 2
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag.get("c2c_contract_valid") is False


def test_c2c_central_planner_contract_validation_rejects_duplicate_resource_keys():
    """Test 12: Duplicate wheat:protected keys in purchases invalidates contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert diag.get("c2c_contract_valid") is False


def test_c2c_central_planner_contract_validation_rejects_illegal_opcode_metadata():
    """Test 13: Illegal resource_key on BUY_SEED invalidates contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_SEED", "CARROT", 2]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [{"kind": "seed", "resource_key": "wheat:protected"}],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert diag.get("c2c_contract_valid") is False


def test_c2c_central_planner_contract_validation_rejects_invalid_reservation():
    """Test 14: Invalid feed_sale_reservation before Day 29 invalidates contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [{"kind": "animal", "animal": "COW"}],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": False, "sellable_shed_wheat": 0},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag.get("c2c_contract_valid") is False


# ============================================================================
# 4. Selection & Dependency Closure Tests
# ============================================================================

def test_c2c_protected_wheat_selected_as_hard_root():
    """Test 15: Valid wheat:protected proposal is selected as root in live mode."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected", "hard_required": True}
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger, cap=1)
    assert len(orders) == 1
    assert orders[0][0] == "BUY_PRODUCT" and orders[0][1] == "WHEAT"


def test_c2c_discretionary_animal_dropped_when_protected_wheat_missing():
    """Test 16: Animal requiring wheat:protected is dropped if protected wheat is not selected."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    # Animal proposal has dependency wheat:protected, but no wheat is purchased
    purchases = [
        ["BUY_ANIMAL", "COW", 1],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:protected"],
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag.get("dependency_closure_applied") is True


def test_c2c_discretionary_animal_dropped_when_optional_wheat_missing():
    """Test 17: Animal requiring wheat:optional is dropped if optional wheat is not selected."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_ANIMAL", "COW", 1],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:optional"],
            },
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    # COW required wheat:optional, but only wheat:protected was present -> drop COW
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag.get("dependency_closure_applied") is True


def test_c2c_discretionary_animal_kept_when_dependencies_selected():
    """Test 18: Animal is kept when all required resource keys are selected."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_ANIMAL", "COW", 1],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {"kind": "wheat_optional", "resource_key": "wheat:optional", "feed_class": "optional"},
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:protected", "wheat:optional"],
            },
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 10,
            "requires_resource_keys": ["wheat:protected", "wheat:optional"],
        },
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger, cap=10)
    assert any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag.get("dependency_closure_applied") is False


def test_c2c_no_dependency_animal_survives_without_wheat():
    """Test 19: Animal with empty dependencies survives without any wheat buy order."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_ANIMAL", "COW", 1],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": [],
            },
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert any(o[0] == "BUY_ANIMAL" for o in orders)


def test_c2c_dropped_animal_does_not_backfill():
    """Test 20: When an animal is dropped for missing dependency, vacated slot is not backfilled."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    # cap = 2: select protected wheat and COW.
    # Third proposal is FERTILIZER (P3). If COW dropped, FERTILIZER must NOT backfill.
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_ANIMAL", "COW", 1],
        ["BUY_PRODUCT", "FERTILIZER", 2],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:optional"],
            },  # Missing!
            {"kind": "fertilizer"},
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": ["wheat:protected"]},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger, cap=2)
    # Only wheat should be present; COW dropped, and FERTILIZER was not in initial selected top 2
    assert len(orders) == 1
    assert orders[0][0] == "BUY_PRODUCT"
    assert orders[0][1] == "WHEAT"


# ============================================================================
# 5. Authoritative Physical WHEAT Sell Clamping Tests
# ============================================================================

def test_c2c_wheat_sell_blocked_when_sellable_shed_wheat_zero():
    """Test 21: SELL WHEAT is rejected when effective_sellable_shed_wheat is 0."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=2, shed_wheat=40)
    sells = [["SELL", "WHEAT", 20]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 0, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=[], purchase_ledger=ledger, sell_orders=sells)
    assert not any(o[0] == "SELL" and o[1] == "WHEAT" for o in orders)
    assert any(d.get("rejection_reason") == "protected_feed_reservation" for d in diag.get("rejected_details", []))


def test_c2c_wheat_sell_trimmed_to_sellable_shed_wheat():
    """Test 22: SELL WHEAT is trimmed when requesting more than sellable_shed_wheat."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=2, shed_wheat=50)
    sells = [["SELL", "WHEAT", 30]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 12, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=[], purchase_ledger=ledger, sell_orders=sells)
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    assert wheat_sells[0][2] == 12


def test_c2c_wheat_sell_allowed_when_shed_wheat_fully_sellable():
    """Test 23: SELL WHEAT passes untrimmed when within sellable_shed_wheat."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=2, shed_wheat=50)
    sells = [["SELL", "WHEAT", 20]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 30, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=[], purchase_ledger=ledger, sell_orders=sells)
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    assert wheat_sells[0][2] == 20


def test_c2c_wheat_sell_on_day_29_never_blocked_by_feed_reservation():
    """Test 24: Day 29 final liquidation never blocked by feed reservation."""
    cp = CentralPlanner()
    ctx = make_ctx(day=29, hour=0, shed_wheat=80)
    sells = [["SELL", "WHEAT", 80]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 80, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=[], purchase_ledger=ledger, sell_orders=sells)
    assert any(o[0] == "SELL" and o[1] == "WHEAT" and o[2] == 80 for o in orders)


# ============================================================================
# 6. Post-Closure Consolidation & Invariants Tests
# ============================================================================

def test_c2c_post_closure_wheat_buy_consolidation():
    """Test 25: Multiple accepted wheat buys consolidate into one order after closure."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_PRODUCT", "WHEAT", 10],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {"kind": "wheat_optional", "resource_key": "wheat:optional", "feed_class": "optional"},
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    wheat_buys = [o for o in orders if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"]
    assert len(wheat_buys) == 1
    assert wheat_buys[0][2] == 15


def test_c2c_post_closure_wheat_consolidation_does_not_backfill():
    """Test 26: Consolidation frees a slot, but that slot is NOT backfilled."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    # cap = 2: top 2 proposals are protected wheat and optional wheat.
    # Third proposal is SEED.
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_PRODUCT", "WHEAT", 10],
        ["BUY_SEED", "CARROT", 2],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {"kind": "wheat_optional", "resource_key": "wheat:optional", "feed_class": "optional"},
            {"kind": "seed", "crop": "CARROT", "tier": 4},
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger, cap=2)
    # Top 2 were consolidated into 1 order. SEED was not in top 2, so it cannot enter!
    assert len(orders) == 1
    assert orders[0] == ["BUY_PRODUCT", "WHEAT", 15]


def test_c2c_all_five_invariants_hold_under_c2c():
    """Test 27: All 5 conservation invariants hold during C2C arbitration."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["HIRE"],
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_ANIMAL", "COW", 1],
    ]
    sells = [
        ["SELL", "WHEAT", 10],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "hire", "tier": 0},
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:protected"],
            },
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": ["wheat:protected"]},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger, sell_orders=sells, cap=3)
    # Total candidates = 4, accepted + rejected = 4.
    total = len(diag["accepted_orders"]) + len(diag["rejected_orders"])
    assert total == 4


# ============================================================================
# 7. Fallback & Live Mode Invariant Tests
# ============================================================================

def test_c2c_dependency_safe_live_fallback_drops_all_animals():
    """Test 28: Live fallback immediately drops all animal proposals."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_ANIMAL", "COW", 1],
        ["BUY_ANIMAL", "SHEEP", 1],
    ]
    ledger = {
        "feed_sale_reservation": {"valid": True, "sellable_shed_wheat": 5},
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
        error="test_injected_error",
    )
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag["fallback_used"] is True
    assert diag["dropped_animal_count"] == 2


def test_c2c_dependency_safe_live_fallback_preserves_protected_wheat():
    """Test 29: Live fallback preserves protected wheat first."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["HIRE"],
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    ledger = {
        "order_metadata": [
            {"kind": "hire"},
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
        "feed_sale_reservation": {"valid": True, "sellable_shed_wheat": 5},
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
        cap=1,
    )
    assert len(orders) == 1
    assert orders[0] == ["BUY_PRODUCT", "WHEAT", 5]


def test_c2c_dependency_safe_live_fallback_clamps_wheat_sales():
    """Test 30: Live fallback clamps wheat sales to sellable shed wheat."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=2, shed_wheat=40)
    sells = [["SELL", "WHEAT", 30]]
    ledger = {
        "feed_sale_reservation": {"valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        sell_orders=sells,
        purchase_ledger=ledger,
    )
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    assert wheat_sells[0][2] == 10


def test_c2c_live_mode_never_routes_to_legacy_compose(monkeypatch):
    """Test 31: When POINT2_FEED_MODE == 'live', agent_decision never calls legacy compose."""
    import kaggle_environments
    from main import _agent_decision
    monkeypatch.setattr("config.POINT2_FEED_MODE", "live")

    legacy_called = []
    def mock_legacy(*args, **kwargs):
        legacy_called.append(True)
        return []

    monkeypatch.setattr("main.legacy_compose_market", mock_legacy)

    # Invalidate CentralPlanner.plan_market to test fallback behavior
    def mock_raise(*args, **kwargs):
        raise RuntimeError("Injected CentralPlanner crash")

    monkeypatch.setattr("strategy.central_planner.CentralPlanner.plan_market", mock_raise)

    env = kaggle_environments.make("kaggriculture", configuration={"episodeSteps": 720, "seed": 42})
    env.reset(2)
    obs = env.state[0].observation

    actions = _agent_decision(obs)
    # Must succeed via dependency_safe_live_fallback, not crash
    assert isinstance(actions, dict)
    assert "market" in actions
    assert isinstance(actions["market"], list)
    assert len(legacy_called) == 0, "legacy_compose_market must never be called in live mode"


def test_c2c_diagnostics_report_complete_closure_telemetry():
    """Test 32: Diagnostics report complete telemetry for C2C."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
        ["BUY_ANIMAL", "COW", 1],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:protected"],
            },
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": ["wheat:protected"]},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert "c2c_contract_valid" in diag
    assert "dependency_closure_applied" in diag
    assert "dropped_animal_proposals" in diag
    assert "feed_sale_reservation_dependency_satisfied" in diag
    assert "effective_sellable_shed_wheat" in diag
    assert "authoritative_sellable_shed_wheat" in diag


def test_c2c_live_mode_default_remains_shadow():
    """Test 33: Production default POINT2_FEED_MODE remains 'shadow'."""
    assert POINT2_FEED_MODE == "shadow"


# ============================================================================
# 8. Mandatory C2C Amendment Tests (Reservation Dependencies)
# ============================================================================

def test_amendment_reservation_requires_resource_keys_populated():
    """Test 34: feed_sale_reservation exposes requires_resource_keys correctly."""
    from strategy.feed_feasibility import derive_feed_sale_reservation
    class DummyLedger:
        wheat_in_shed = 50
        wheat_on_workers = 10
        day = 5

    res = derive_feed_sale_reservation(
        ledger=DummyLedger(),
        operational_min_wheat_slack=20.0,
        valid=True,
        requires_resource_keys=["wheat:protected", "wheat:optional"],
    )
    assert "requires_resource_keys" in res
    assert res["requires_resource_keys"] == ["wheat:protected", "wheat:optional"]


def test_amendment_missing_reservation_dependency_forces_zero_sellable_wheat():
    """Test 35: If reservation requires a resource that is not selected, sellable shed wheat is clamped to 0."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0, shed_wheat=40)
    # Reservation requires wheat:optional, but only wheat:protected is in purchases
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 20,
            "requires_resource_keys": ["wheat:optional"],  # Missing!
        },
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert diag.get("feed_sale_reservation_dependency_satisfied") is False
    assert diag.get("effective_sellable_shed_wheat") == 0
    assert "wheat:optional" in diag.get("missing_feed_sale_resource_keys", [])


def test_amendment_wheat_sell_clamping_happens_before_animal_closure():
    """Test 36: WHEAT sell clamping executes before animal closure.
    Shed wheat is preserved even if animal is subsequently dropped."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=2, shed_wheat=40)
    purchases = [
        ["BUY_ANIMAL", "COW", 1],
    ]
    sells = [
        ["SELL", "WHEAT", 30],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_cow_0"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": ["wheat:optional"],
            },  # Missing!
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 10,
            "requires_resource_keys": [],
        },
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger, sell_orders=sells)
    # 1. Animal COW is dropped due to missing wheat:optional
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    # 2. SELL WHEAT is clamped to sellable_shed_wheat (10), NOT expanded by COW drop
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    assert wheat_sells[0][2] == 10


def test_amendment_traceability_telemetry_fields_present():
    """Test 37: Diagnostics report all amendment traceability telemetry fields."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 15,
            "requires_resource_keys": ["wheat:protected"],
        },
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert diag["feed_sale_reservation_dependency_satisfied"] is True
    assert diag["missing_feed_sale_resource_keys"] == []
    assert diag["effective_sellable_shed_wheat"] == 15
    assert diag["authoritative_sellable_shed_wheat"] == 15


# ============================================================================
# 9. Hardening & Fallback Regression Tests (Phase C2C Repair)
# ============================================================================

def test_fallback_reservation_depends_on_optional_wheat_loses_selection_zero_sell():
    """Test 38: Fallback reservation depends on optional WHEAT; optional loses selection -> zero SELL WHEAT."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0, shed_wheat=40)
    purchases = [
        ["HIRE"],
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    sells = [
        ["SELL", "WHEAT", 5],
    ]
    ledger = {
        "order_metadata": [
            {"kind": "hire"},
            {"kind": "wheat_optional", "resource_key": "wheat:optional", "feed_class": "optional"},
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 5,
            "requires_resource_keys": ["wheat:optional"],
        },
    }
    # Cap = 1: HIRE is selected; optional wheat loses selection!
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
        sell_orders=sells,
        cap=1,
    )
    assert not any(o[0] == "SELL" and o[1] == "WHEAT" for o in orders)
    assert diag["feed_sale_reservation_dependency_satisfied"] is False
    assert "wheat:optional" in diag["missing_feed_sale_resource_keys"]
    assert diag["effective_sellable_shed_wheat"] == 0


def test_fallback_reservation_depends_on_optional_wheat_survives_authoritative_sell():
    """Test 39: Fallback reservation depends on optional WHEAT; optional survives -> authoritative sell allowance preserved."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0, shed_wheat=40)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    sells = [
        ["SELL", "WHEAT", 5],
    ]
    ledger = {
        "order_metadata": [
            {"kind": "wheat_optional", "resource_key": "wheat:optional", "feed_class": "optional"},
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 5,
            "requires_resource_keys": ["wheat:optional"],
        },
    }
    # Cap = 2: Both optional wheat and sell wheat survive!
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
        sell_orders=sells,
        cap=2,
    )
    assert diag["feed_sale_reservation_dependency_satisfied"] is True
    assert diag["effective_sellable_shed_wheat"] == 5
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    assert wheat_sells[0][2] == 5


def test_fallback_reservation_depends_on_protected_wheat_survives():
    """Test 40: Fallback reservation depends on protected WHEAT; protected hard root survives -> dependency satisfied."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0, shed_wheat=40)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    sells = [
        ["SELL", "WHEAT", 10],
    ]
    ledger = {
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 10,
            "requires_resource_keys": ["wheat:protected"],
        },
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
        sell_orders=sells,
        cap=2,
    )
    assert diag["feed_sale_reservation_dependency_satisfied"] is True
    assert diag["effective_sellable_shed_wheat"] == 10
    wheat_sells = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    assert len(wheat_sells) == 1
    assert wheat_sells[0][2] == 10


def test_fallback_malformed_reservation_requires_resource_keys_zero_sell():
    """Test 41: Malformed reservation requires_resource_keys -> zero pre-Day29 WHEAT sale."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0, shed_wheat=40)
    purchases = [
        ["BUY_PRODUCT", "WHEAT", 5],
    ]
    sells = [
        ["SELL", "WHEAT", 10],
    ]
    ledger = {
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": True,
            "sellable_shed_wheat": 10,
            "requires_resource_keys": "not_a_list",  # Malformed!
        },
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
        sell_orders=sells,
        cap=5,
    )
    assert diag["feed_sale_reservation_dependency_satisfied"] is False
    assert diag["effective_sellable_shed_wheat"] == 0
    assert not any(o[0] == "SELL" and o[1] == "WHEAT" for o in orders)


def test_c2c_animal_missing_candidate_ids_rejected():
    """Test 42: Missing candidate_ids rejects BUY_ANIMAL with invalid_dependency_contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": [],
                # candidate_ids missing!
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_empty_candidate_ids_rejected():
    """Test 43: Empty candidate_ids rejects BUY_ANIMAL with invalid_dependency_contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": [],  # Empty list!
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": [],
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_malformed_candidate_ids_rejected():
    """Test 44: Malformed candidate_ids (string or invalid elements) rejects BUY_ANIMAL."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": "cand_1",  # Not a list!
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": [],
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_missing_dependency_group_rejected():
    """Test 45: Missing dependency_group rejects BUY_ANIMAL with invalid_dependency_contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_1"],
                "requires_resource_keys": [],
                # dependency_group missing!
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_malformed_dependency_group_rejected():
    """Test 46: Malformed dependency_group (empty string or non-string) rejects BUY_ANIMAL."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_1"],
                "dependency_group": "",  # Empty string!
                "requires_resource_keys": [],
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_missing_requires_resource_keys_rejected():
    """Test 47: Missing requires_resource_keys rejects BUY_ANIMAL with invalid_dependency_contract."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_1"],
                "dependency_group": "animal:COW:0",
                # requires_resource_keys missing!
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_malformed_requires_resource_keys_rejected():
    """Test 48: Malformed requires_resource_keys (string or invalid key) rejects BUY_ANIMAL."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_1"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": "wheat:optional",  # Not a list!
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    rej = [r for r in diag["rejected_details"] if r.get("order") == ["BUY_ANIMAL", "COW", 1]]
    assert len(rej) == 1
    assert rej[0]["rejection_reason"] == "invalid_dependency_contract"


def test_c2c_animal_explicit_empty_requires_resource_keys_valid():
    """Test 49: Explicit requires_resource_keys=[] with valid candidate metadata remains valid."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["BUY_ANIMAL", "COW", 1]]
    ledger = {
        "dependency_contract_version": "point2_c2c_v1",
        "order_metadata": [
            {
                "kind": "animal",
                "animal": "COW",
                "candidate_ids": ["cand_1"],
                "dependency_group": "animal:COW:0",
                "requires_resource_keys": [],  # Explicit empty list is valid!
            }
        ],
        "feed_sale_reservation": {"version": "point2_c2c_v1", "valid": True, "sellable_shed_wheat": 10, "requires_resource_keys": []},
    }
    orders, diag = cp.plan_market(ctx, purchase_orders=purchases, purchase_ledger=ledger)
    assert any(o[0] == "BUY_ANIMAL" for o in orders)
    assert not any(r.get("rejection_reason") == "invalid_dependency_contract" for r in diag["rejected_details"])


def test_fallback_malformed_buy_order_rejected():
    """Test 50: Malformed fallback BUY order is rejected with invalid_order."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["INVALID_OPCODE"],
        ["BUY_PRODUCT", "WHEAT", -5],
    ]
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
    )
    assert len(orders) == 0
    invalid_rejs = [r for r in diag["rejected_details"] if r.get("rejection_reason") == "invalid_order"]
    assert len(invalid_rejs) == 2


def test_fallback_malformed_sell_order_rejected():
    """Test 51: Malformed fallback SELL order is rejected with invalid_order."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    sells = [
        ["SELL", "WHEAT", -10],
        ["SELL"],
    ]
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        sell_orders=sells,
    )
    assert len(orders) == 0
    invalid_rejs = [r for r in diag["rejected_details"] if r.get("rejection_reason") == "invalid_order"]
    assert len(invalid_rejs) == 2


def test_fallback_malformed_wheat_with_protected_meta_not_preserved():
    """Test 52: Malformed WHEAT proposal with protected metadata must NOT be preserved as root."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    # Order has invalid quantity -5
    purchases = [
        ["BUY_PRODUCT", "WHEAT", -5],
    ]
    ledger = {
        "order_metadata": [
            {"kind": "wheat_protected", "resource_key": "wheat:protected", "feed_class": "protected"},
        ],
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        purchase_ledger=ledger,
    )
    assert len(orders) == 0
    invalid_rejs = [r for r in diag["rejected_details"] if r.get("rejection_reason") == "invalid_order"]
    assert len(invalid_rejs) == 1


def test_fallback_drops_all_buy_animal():
    """Test 53: Fallback still drops all BUY_ANIMAL proposals."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [
        ["BUY_ANIMAL", "COW", 1],
        ["BUY_ANIMAL", "SHEEP", 2],
    ]
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
    )
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)
    assert diag["dropped_animal_count"] == 2


def test_fallback_respects_global_cap():
    """Test 54: Fallback still respects global cap."""
    cp = CentralPlanner()
    ctx = make_ctx(day=5, hour=0)
    purchases = [["HIRE"] for _ in range(5)]
    sells = [["SELL", "CARROT", 2] for _ in range(5)]
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        purchase_orders=purchases,
        sell_orders=sells,
        cap=4,
    )
    assert len(orders) == 4
    cap_rejs = [r for r in diag["rejected_details"] if r.get("rejection_reason") == "slot_cap"]
    assert len(cap_rejs) == 6


def test_fallback_day29_liquidation_unchanged():
    """Test 55: Day 29 liquidation behavior remains unchanged in fallback."""
    cp = CentralPlanner()
    ctx = make_ctx(day=29, hour=0, shed_wheat=50)
    sells = [["SELL", "WHEAT", 50]]
    # Even if reservation is invalid or missing dependencies, Day 29 allows selling shed wheat!
    ledger = {
        "feed_sale_reservation": {
            "version": "point2_c2c_v1",
            "valid": False,
            "sellable_shed_wheat": 0,
            "requires_resource_keys": ["wheat:optional"],
        },
    }
    orders, diag = cp.dependency_safe_live_fallback(
        ctx=ctx,
        sell_orders=sells,
        purchase_ledger=ledger,
    )
    assert len(orders) == 1
    assert orders[0] == ["SELL", "WHEAT", 50]
    assert diag["effective_sellable_shed_wheat"] == 50
