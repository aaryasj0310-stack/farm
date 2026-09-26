"""Authoritative Multi-Resource Commitment Ledger.

Part of the SW-First Forward Architecture Redesign (Phase A & A-R).
Provides time-indexed accounting across future hours/days for:
1. Cash (HARD, CONSERVATIVE, SPECULATIVE inflow categories; zero double-reservation)
2. Feed (Physical accessibility, strict harvest causality, daily animal liabilities, same-day physical chains)
3. Market Orders (Engine-exact 10-order cap per (day, hour) turn with command-specific slot costs)
4. Storage (Physically causal worker-level state, intraday timeline, deposit/sell chains, midnight auto-drop & discard)
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from config import CROPS, FARMER_SPAWN, SHED_ACCESS_TILES, TURNS_PER_DAY
from state.observation_parser import crop_age


class InflowConfidence(str, Enum):
    """Classification of future cash inflows."""
    HARD = "HARD"                  # Mechanically settled cash in farm wallet
    CONSERVATIVE = "CONSERVATIVE"  # Physically harvested inventory in shed/carriers at floor/drip price
    SPECULATIVE = "SPECULATIVE"    # In-ground crops, unlaid eggs, uncollected wool, future model projections


@dataclass
class DatedCashLiability:
    """A dated monetary obligation."""
    day: int
    hour: int
    amount: float
    purpose: str
    is_hard: bool = True           # Hard = feed/land/mandatory hires; Soft = discretionary investments


@dataclass
class DatedCashInflow:
    """An anticipated future cash inflow."""
    day: int
    hour: int
    amount: float
    confidence: InflowConfidence
    source: str


@dataclass
class DatedFeedLiability:
    """Daily feed requirement for an animal."""
    day: int
    hour_deadline: int             # Must be fed before hour 23
    animal_pos: Tuple[int, int]
    species: str
    amount: int = 1


@dataclass
class WorkerStorageState:
    """Worker-level inventory and spatial accessibility state."""
    worker_id: int
    pos: Tuple[int, int]
    inventory: Dict[str, int] = field(default_factory=dict)
    carried_total: int = 0
    distance_to_shed: int = 0
    earliest_deposit_hour: int = 0


@dataclass
class InGroundWheatHarvest:
    """Authoritative in-ground wheat harvest tracking with engine-exact timing."""
    planted_day: int = 0
    current_age: int = 0
    tile_pos: Tuple[int, int] = (0, 0)
    earliest_harvest_day: int = 0      # planted_day + 2 (first_yield_day)
    max_maturity_day: int = 0          # planted_day + 4 (max_yield_day)
    expected_yield: int = 6
    is_harvestable_now: bool = False
    is_mature_now: bool = False
    day: int = 0
    hour: int = 0

    def __post_init__(self) -> None:
        if self.day != 0 and self.max_maturity_day == 0:
            self.max_maturity_day = self.day
        if self.max_maturity_day != 0 and self.day == 0:
            self.day = self.max_maturity_day
        if self.earliest_harvest_day == 0 and self.max_maturity_day != 0:
            self.earliest_harvest_day = self.max_maturity_day


@dataclass
class MarketSlotAllocation:
    """Reservation of market order capacity (maximum 10 commands per player per turn)."""
    command_type: str              # HIRE, BUY_PRODUCT, BUY_LAND, BUY_ANIMAL, SELL
    slots_consumed: int
    details: Dict[str, Any] = field(default_factory=dict)


class ResourceLedger:
    """Authoritative, unified multi-resource ledger with engine-exact causality."""

    def __init__(self, current_day: int = 0, current_hour: int = 0) -> None:
        self.day: int = current_day
        self.hour: int = current_hour

        # Cash Ledger
        self.cash_on_hand: float = 0.0
        self.safety_reserve: float = 300.0
        self.dated_liabilities: List[DatedCashLiability] = []
        self.dated_inflows: List[DatedCashInflow] = []

        # Feed Ledger
        self.shed_wheat: int = 0
        self.worker_carried_wheat: int = 0
        self.in_ground_wheat: List[InGroundWheatHarvest] = []
        self.feed_liabilities: List[DatedFeedLiability] = []

        # Market Order Ledger
        # Maps (day, hour) -> list of allocated slots (max 10 total slots per turn)
        self.turn_order_allocations: Dict[Tuple[int, int], List[MarketSlotAllocation]] = {}

        # Storage Ledger
        self.shed_capacity: int = 100
        self.current_shed_occupancy: int = 0
        self.current_worker_carried_units: int = 0
        self.goods_in_shed: Dict[str, int] = {}
        self.workers: List[WorkerStorageState] = []

    def update_from_observation(self, ctx: Dict[str, Any]) -> None:
        """Synchronize ledger with ground-truth engine observation using authoritative helpers."""
        self.day = ctx.get("day", 0)
        self.hour = ctx.get("hour", 0)
        farm = ctx.get("farm")
        private = ctx.get("private")

        # 1. Cash
        self.cash_on_hand = float(getattr(farm, "money", 0.0)) if farm else 0.0

        # 2. Shed Storage
        shed_dict = getattr(private, "shed", {}) if private else {}
        self.goods_in_shed = {k: int(v) for k, v in shed_dict.items() if int(v) > 0}
        self.shed_wheat = int(shed_dict.get("WHEAT", 0))
        self.current_shed_occupancy = sum(self.goods_in_shed.values())

        # 3. Worker State & Carried Inventories
        self.workers.clear()
        carried_wheat = 0
        carried_total = 0
        inventories = getattr(private, "inventories", []) if private else []

        if farm:
            farmer_pos = tuple(getattr(farm, "farmer", (4, 4)) or (4, 4))
            farmer_inv = inventories[0] if len(inventories) > 0 and isinstance(inventories[0], dict) else {}
            farmer_clean_inv = {k: int(v) for k, v in farmer_inv.items() if int(v) > 0}
            farmer_dist = min(abs(farmer_pos[0] - sx) + abs(farmer_pos[1] - sy) for (sx, sy) in SHED_ACCESS_TILES)
            farmer_tot = sum(farmer_clean_inv.values())
            self.workers.append(
                WorkerStorageState(
                    worker_id=0,
                    pos=farmer_pos,
                    inventory=farmer_clean_inv,
                    carried_total=farmer_tot,
                    distance_to_shed=farmer_dist,
                    earliest_deposit_hour=min(24, self.hour + farmer_dist),
                )
            )
            carried_wheat += int(farmer_clean_inv.get("WHEAT", 0))
            carried_total += farmer_tot

            hands = getattr(farm, "hands", []) or []
            for h_idx, h_pos in enumerate(hands):
                w_id = h_idx + 1
                pos = tuple(h_pos) if h_pos is not None else (4, 4)
                h_inv = inventories[w_id] if len(inventories) > w_id and isinstance(inventories[w_id], dict) else {}
                h_clean_inv = {k: int(v) for k, v in h_inv.items() if int(v) > 0}
                h_dist = min(abs(pos[0] - sx) + abs(pos[1] - sy) for (sx, sy) in SHED_ACCESS_TILES)
                h_tot = sum(h_clean_inv.values())
                self.workers.append(
                    WorkerStorageState(
                        worker_id=w_id,
                        pos=pos,
                        inventory=h_clean_inv,
                        carried_total=h_tot,
                        distance_to_shed=h_dist,
                        earliest_deposit_hour=min(24, self.hour + h_dist),
                    )
                )
                carried_wheat += int(h_clean_inv.get("WHEAT", 0))
                carried_total += h_tot

        self.worker_carried_wheat = carried_wheat
        self.current_worker_carried_units = carried_total

        # 4. In-ground Wheat Tracking using Authoritative crop_age and planted_day
        self.in_ground_wheat.clear()
        if farm:
            for t in farm.iter_tiles():
                is_plant = getattr(t, "is_plant", False) or getattr(t, "kind", None) == "PLANT"
                crop_name = getattr(t, "crop", None)
                if is_plant and crop_name == "WHEAT":
                    planted_day = getattr(t, "planted_day", None)
                    if planted_day is not None:
                        c_age = crop_age(t, self.day)
                        p_day = planted_day
                    else:
                        c_age = 0
                        p_day = self.day

                    earliest_h = p_day + 2  # first_yield_day = 2
                    max_m = p_day + 4       # max_yield_day = 4
                    is_harv = (self.day >= earliest_h)
                    is_mat = (self.day >= max_m)
                    curr_units = int(getattr(t, "yield_units", 0) or 0)

                    if is_mat:
                        exp_yield = 6 if curr_units == 0 else max(6, curr_units)
                    elif is_harv:
                        exp_yield = max(2, curr_units)
                    else:
                        exp_yield = 6

                    self.in_ground_wheat.append(
                        InGroundWheatHarvest(
                            planted_day=p_day,
                            current_age=c_age,
                            tile_pos=t.pos if hasattr(t, "pos") else (t.x, t.y),
                            earliest_harvest_day=earliest_h,
                            max_maturity_day=max_m,
                            expected_yield=exp_yield,
                            is_harvestable_now=is_harv,
                            is_mature_now=is_mat,
                        )
                    )

        # 5. Animal Feed Liabilities
        self.feed_liabilities.clear()
        if farm:
            for t in farm.iter_tiles():
                if (getattr(t, "is_animal", False) or getattr(t, "kind", None) == "PASTURE") and getattr(t, "animal", None):
                    fed_today = bool(getattr(t, "fed_today", False))
                    pos = t.pos if hasattr(t, "pos") else (t.x, t.y)
                    sp = getattr(t, "animal", "COW")
                    if not fed_today:
                        self.feed_liabilities.append(
                            DatedFeedLiability(
                                day=self.day,
                                hour_deadline=23,
                                animal_pos=pos,
                                species=sp,
                                amount=1,
                            )
                        )
                    # And subsequent days in rolling horizon
                    for fut_day in range(self.day + 1, min(30, self.day + 7)):
                        self.feed_liabilities.append(
                            DatedFeedLiability(
                                day=fut_day,
                                hour_deadline=23,
                                animal_pos=pos,
                                species=sp,
                                amount=1,
                            )
                        )

        # 6. Prune expired liabilities and inflows
        self.dated_liabilities = [
            l for l in self.dated_liabilities
            if (l.day > self.day) or (l.day == self.day and l.hour >= self.hour)
        ]
        self.dated_inflows = [
            inf for inf in self.dated_inflows
            if (inf.day > self.day) or (inf.day == self.day and inf.hour >= self.hour)
        ]

    # --- Cash Ledger Management ---

    def reserve_dated_liquidity(self, day: int, hour: int, amount: float, purpose: str, is_hard: bool = True) -> bool:
        """Reserve cash for a future dated obligation without dipping below safety reserve."""
        temp_candidate = DatedCashLiability(day, hour, amount, purpose, is_hard)
        test_liabilities = self.dated_liabilities + [temp_candidate]

        checkpoints = {(day, hour)} | {(l.day, l.hour) for l in self.dated_liabilities}
        for inf in self.dated_inflows:
            checkpoints.add((inf.day, inf.hour))

        sorted_checkpoints = sorted(list(checkpoints))
        for (cd, ch) in sorted_checkpoints:
            cash = self.cash_on_hand - self.safety_reserve
            for inf in self.dated_inflows:
                if (inf.day < cd) or (inf.day == cd and inf.hour <= ch):
                    if inf.confidence in (InflowConfidence.HARD, InflowConfidence.CONSERVATIVE):
                        cash += inf.amount
                    elif not is_hard and inf.confidence == InflowConfidence.SPECULATIVE:
                        cash += inf.amount
            for liab in test_liabilities:
                if (liab.day < cd) or (liab.day == cd and liab.hour <= ch):
                    cash -= liab.amount
            if cash < 0:
                return False

        self.dated_liabilities.append(temp_candidate)
        return True

    def register_inflow(self, day: int, hour: int, amount: float, confidence: InflowConfidence, source: str) -> None:
        """Register an anticipated future cash inflow."""
        self.dated_inflows.append(DatedCashInflow(day, hour, amount, confidence, source))

    def project_available_cash(self, target_day: int, target_hour: int, include_speculative: bool = False) -> float:
        """Calculate conservative net liquidity available at (target_day, target_hour)."""
        cash = self.cash_on_hand - self.safety_reserve

        for inf in self.dated_inflows:
            if (inf.day < target_day) or (inf.day == target_day and inf.hour <= target_hour):
                if inf.confidence in (InflowConfidence.HARD, InflowConfidence.CONSERVATIVE):
                    cash += inf.amount
                elif include_speculative and inf.confidence == InflowConfidence.SPECULATIVE:
                    cash += inf.amount

        for liab in self.dated_liabilities:
            if (liab.day < target_day) or (liab.day == target_day and liab.hour <= target_hour):
                cash -= liab.amount

        return max(0.0, cash)

    def get_uncommitted_discretionary_cash(self) -> float:
        """Return currently uncommitted liquid capital available for immediate investment."""
        total_committed = sum(l.amount for l in self.dated_liabilities if l.is_hard)
        return max(0.0, self.cash_on_hand - self.safety_reserve - total_committed)

    # --- Feed Ledger Management ---

    def get_accessible_wheat_now(self) -> int:
        """Wheat immediately physically reachable (in shed or carried by a worker)."""
        return self.shed_wheat + self.worker_carried_wheat

    def get_projected_mature_wheat(self, day: int) -> int:
        """Total in-ground wheat reaching full maturity on specified day."""
        return sum(
            h.expected_yield for h in self.in_ground_wheat
            if h.max_maturity_day == day
        )

    def evaluate_same_day_harvest_feed_feasibility(
        self,
        wheat_harvest: InGroundWheatHarvest,
        animal_pos: Tuple[int, int],
        current_hour: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> Tuple[bool, int, Dict[str, Any]]:
        """Evaluate if in-ground wheat can physically complete HARVEST -> FEED before H23.

        Model:
        Worker pos -> Wheat pos (move) -> HARVEST (1) -> Animal pos (move) -> FEED (1).
        """
        cur_h = self.hour if current_hour is None else current_hour
        if self.day < wheat_harvest.earliest_harvest_day:
            return False, 999, {"reason": "wheat_not_harvestable_today"}

        candidate_workers = [
            w for w in self.workers
            if w.carried_total < 20 and (worker_id is None or w.worker_id == worker_id)
        ]
        if not candidate_workers:
            return False, 999, {"reason": "no_worker_available"}

        best_completion = 999
        best_worker = None

        for w in candidate_workers:
            dist_to_wheat = abs(w.pos[0] - wheat_harvest.tile_pos[0]) + abs(w.pos[1] - wheat_harvest.tile_pos[1])
            dist_to_animal = abs(wheat_harvest.tile_pos[0] - animal_pos[0]) + abs(wheat_harvest.tile_pos[1] - animal_pos[1])
            actions_needed = dist_to_wheat + 1 + dist_to_animal + 1
            completion = cur_h + actions_needed
            if completion < best_completion:
                best_completion = completion
                best_worker = w.worker_id

        feasible = (best_completion <= 23)
        return feasible, best_completion, {
            "feasible": feasible,
            "completion_hour": best_completion,
            "best_worker": best_worker,
            "deadline": 23,
        }

    def evaluate_shed_feed_feasibility(
        self,
        animal_pos: Tuple[int, int],
        current_hour: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> Tuple[bool, int, Dict[str, Any]]:
        """Evaluate physical chain: Worker pos -> travel to shed -> PICKUP WHEAT -> travel to animal -> FEED.

        Requires self.shed_wheat > 0.
        """
        cur_h = self.hour if current_hour is None else current_hour
        if self.shed_wheat <= 0:
            return False, 999, {"reason": "no_shed_wheat_available"}

        candidate_workers = self.workers
        if worker_id is not None:
            candidate_workers = [w for w in self.workers if w.worker_id == worker_id]
        if not candidate_workers:
            return False, 999, {"reason": "no_worker_available"}

        best_completion = 999
        best_worker = None

        for w in candidate_workers:
            min_travel = min(
                abs(w.pos[0] - sx) + abs(w.pos[1] - sy) + abs(sx - animal_pos[0]) + abs(sy - animal_pos[1])
                for sx, sy in SHED_ACCESS_TILES
            )
            # travel to shed + 1 (PICKUP) + travel to animal + 1 (FEED)
            actions_needed = min_travel + 1 + 1
            completion = cur_h + actions_needed
            if completion < best_completion:
                best_completion = completion
                best_worker = w.worker_id

        feasible = (best_completion <= 23)
        return feasible, best_completion, {
            "feasible": feasible,
            "completion_hour": best_completion,
            "best_worker": best_worker,
            "mode": "SHED_PICKUP_FEED",
            "deadline": 23,
        }

    def evaluate_carried_feed_feasibility(
        self,
        animal_pos: Tuple[int, int],
        current_hour: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> Tuple[bool, int, Dict[str, Any]]:
        """Evaluate physical chain: Worker carrying wheat -> travel to animal -> FEED.

        Only workers who currently carry at least 1 wheat in their backpack are eligible.
        Distant workers whose travel exceeds remaining hours are deemed infeasible.
        """
        cur_h = self.hour if current_hour is None else current_hour
        candidate_workers = [
            w for w in self.workers
            if w.inventory.get("WHEAT", 0) > 0 and (worker_id is None or w.worker_id == worker_id)
        ]
        if not candidate_workers:
            return False, 999, {"reason": "no_worker_carrying_wheat"}

        best_completion = 999
        best_worker = None

        for w in candidate_workers:
            dist_to_animal = abs(w.pos[0] - animal_pos[0]) + abs(w.pos[1] - animal_pos[1])
            # travel to animal + 1 (FEED)
            actions_needed = dist_to_animal + 1
            completion = cur_h + actions_needed
            if completion < best_completion:
                best_completion = completion
                best_worker = w.worker_id

        feasible = (best_completion <= 23)
        return feasible, best_completion, {
            "feasible": feasible,
            "completion_hour": best_completion,
            "best_worker": best_worker,
            "mode": "CARRIED_FEED",
            "deadline": 23,
        }

    def evaluate_same_day_harvest_shed_deposit_feasibility(
        self,
        wheat_harvest: InGroundWheatHarvest,
        current_hour: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> Tuple[bool, int, Dict[str, Any]]:
        """Evaluate physical chain: Worker pos -> travel to wheat -> HARVEST -> travel to shed -> PLACE.

        Product must enter the shed before it is market-accessible.
        Includes 1 action for HARVEST and 1 action for PLACE.
        """
        cur_h = self.hour if current_hour is None else current_hour
        if self.day < wheat_harvest.earliest_harvest_day:
            return False, 999, {"reason": "wheat_not_harvestable_today"}

        candidate_workers = self.workers
        if worker_id is not None:
            candidate_workers = [w for w in self.workers if w.worker_id == worker_id]
        if not candidate_workers:
            return False, 999, {"reason": "no_worker_available"}

        best_completion = 999
        best_worker = None

        for w in candidate_workers:
            dist_to_wheat = abs(w.pos[0] - wheat_harvest.tile_pos[0]) + abs(w.pos[1] - wheat_harvest.tile_pos[1])
            dist_wheat_to_shed = min(abs(wheat_harvest.tile_pos[0] - sx) + abs(wheat_harvest.tile_pos[1] - sy) for sx, sy in SHED_ACCESS_TILES)
            # travel to wheat + 1 (HARVEST) + travel to shed + 1 (PLACE)
            actions_needed = dist_to_wheat + 1 + dist_wheat_to_shed + 1
            completion = cur_h + actions_needed
            if completion < best_completion:
                best_completion = completion
                best_worker = w.worker_id

        feasible = (best_completion <= 23)
        return feasible, best_completion, {
            "feasible": feasible,
            "completion_hour": best_completion,
            "best_worker": best_worker,
            "mode": "HARVEST_PLACE_SHED",
            "deadline": 23,
        }

    def evaluate_feed_feasibility_for_animal(
        self,
        animal_pos: Tuple[int, int],
        current_hour: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> Tuple[bool, str, int, Dict[str, Any]]:
        """Determine most efficient physically causal method to feed an animal today.

        Hierarchy:
        1. Carried wheat (worker carrying wheat -> travel -> FEED)
        2. Shed wheat (worker -> shed -> PICKUP -> animal -> FEED)
        3. Harvest wheat (worker -> wheat -> HARVEST -> animal -> FEED)
        """
        # 1. Carried wheat
        ok_c, comp_c, det_c = self.evaluate_carried_feed_feasibility(animal_pos, current_hour, worker_id)
        if ok_c:
            return True, "CARRIED_FEED", comp_c, det_c

        # 2. Shed wheat
        ok_s, comp_s, det_s = self.evaluate_shed_feed_feasibility(animal_pos, current_hour, worker_id)
        if ok_s:
            return True, "SHED_PICKUP_FEED", comp_s, det_s

        # 3. Same-day mature wheat
        best_h_comp = 999
        best_h_det = {}
        for h in self.in_ground_wheat:
            if h.earliest_harvest_day <= self.day:
                ok_h, comp_h, det_h = self.evaluate_same_day_harvest_feed_feasibility(
                    h, animal_pos, current_hour, worker_id
                )
                if ok_h and comp_h < best_h_comp:
                    best_h_comp = comp_h
                    best_h_det = det_h

        if best_h_comp <= 23:
            return True, "HARVEST_FEED", best_h_comp, best_h_det

        return False, "NONE", 999, {"reason": "no_physically_causal_feed_route"}

    def get_projected_accessible_wheat(self, day: int, hour: int = 23) -> int:
        """Wheat physically accessible for feeding or selling by (day, hour).

        Causal invariants:
        1. Future wheat maturing on day > target_day provides 0 accessible units today.
        2. Today's in-ground wheat counts only if physically harvestable and full physical chain completes before hour.
           For shed access: move + HARVEST (1) + move + PLACE (1) <= hour - current_hour.
        """
        if day < self.day:
            return 0

        if day == self.day:
            # Immediately accessible in shed
            accessible = self.shed_wheat
            # Carried wheat accessible if worker can reach shed and PLACE before hour
            for w in self.workers:
                w_wheat = w.inventory.get("WHEAT", 0)
                if w_wheat > 0:
                    dist_to_shed = min(abs(w.pos[0] - sx) + abs(w.pos[1] - sy) for (sx, sy) in SHED_ACCESS_TILES)
                    # move to shed + 1 (PLACE) <= remaining hours
                    if (self.hour + dist_to_shed + 1) <= hour:
                        accessible += w_wheat

            # Same-day in-ground wheat that can complete HARVEST -> PLACE before hour
            if self.workers:
                for h in self.in_ground_wheat:
                    if h.earliest_harvest_day <= self.day:
                        dist_to_wheat = min(abs(w.pos[0] - h.tile_pos[0]) + abs(w.pos[1] - h.tile_pos[1]) for w in self.workers)
                        dist_wheat_to_shed = min(abs(h.tile_pos[0] - sx) + abs(h.tile_pos[1] - sy) for (sx, sy) in SHED_ACCESS_TILES)
                        # move + 1 (HARVEST) + move + 1 (PLACE)
                        if (self.hour + dist_to_wheat + 1 + dist_wheat_to_shed + 1) <= hour:
                            accessible += h.expected_yield
            return accessible

        # For future days: cumulative carryover plus mature harvests from prior days
        cumulative = self.shed_wheat + self.worker_carried_wheat
        for offset in range(day - self.day + 1):
            check_d = self.day + offset
            if check_d < day:
                # Add mature harvests from check_d
                cumulative += self.get_projected_mature_wheat(check_d)
                # Subtract daily demand on check_d
                daily_demand = sum(1 for liab in self.feed_liabilities if liab.day == check_d)
                cumulative = max(0, cumulative - daily_demand)

        return cumulative

    def get_aggregate_wheat_inventory(self) -> int:
        """Explicit alias for total physical wheat inventory (shed + carried)."""
        return self.shed_wheat + self.worker_carried_wheat

    def project_feed_balance(self, horizon_days: int = 5) -> Dict[str, Any]:
        """Project daily feed surplus/deficit over next N days enforcing strict harvest causality and physical routing.

        Near-term (Day 0) executes physical route assignment:
        - Carried wheat by specific workers
        - Shed wheat pickup + delivery
        - Same-day in-ground wheat harvest + delivery
        - Animal deadlines and competition for wheat and worker hours
        """
        daily_projection = {}

        # 1. Day 0 Physical Route Simulation
        today_liabs = [l for l in self.feed_liabilities if l.day == self.day]
        today_demand = len(today_liabs)

        sim_shed_wheat = max(0, self.shed_wheat)
        sim_workers = {
            w.worker_id: {
                "pos": w.pos,
                "avail_hour": self.hour,
                "wheat": max(0, w.inventory.get("WHEAT", 0)),
                "carried_total": w.carried_total,
            }
            for w in self.workers
        }
        sim_harvests = [
            {
                "tile_pos": h.tile_pos,
                "remaining_yield": max(0, h.expected_yield),
            }
            for h in self.in_ground_wheat
            if h.earliest_harvest_day <= self.day
        ]

        day_0_feasible = True
        fed_count = 0
        unfed_reasons = []
        assigned_routes = []

        # Sort today's obligations by hour_deadline (most urgent first)
        sorted_today_liabs = sorted(today_liabs, key=lambda l: l.hour_deadline)

        for liab in sorted_today_liabs:
            a_pos = liab.animal_pos
            deadline = liab.hour_deadline
            best_route = None
            best_completion = 999

            # Evaluate each worker's physical ability to feed this animal
            for w_id, w_state in sim_workers.items():
                w_pos = w_state["pos"]
                w_hour = w_state["avail_hour"]

                # Route 1: Worker has wheat in backpack
                if w_state["wheat"] > 0:
                    dist = abs(w_pos[0] - a_pos[0]) + abs(w_pos[1] - a_pos[1])
                    comp = w_hour + dist + 1  # travel + 1 (FEED)
                    if comp <= deadline and comp < best_completion:
                        best_completion = comp
                        best_route = ("CARRIED", w_id, None, comp)

                # Route 2: Worker uses shed wheat
                if sim_shed_wheat > 0:
                    min_shed_travel = min(
                        abs(w_pos[0] - sx) + abs(w_pos[1] - sy) + abs(sx - a_pos[0]) + abs(sy - a_pos[1])
                        for sx, sy in SHED_ACCESS_TILES
                    )
                    comp = w_hour + min_shed_travel + 1 + 1  # travel shed + 1 (PICKUP) + travel animal + 1 (FEED)
                    if comp <= deadline and comp < best_completion:
                        best_completion = comp
                        best_route = ("SHED", w_id, None, comp)

                # Route 3: Worker harvests mature in-ground wheat today
                free_space = max(0, 20 - w_state["carried_total"])
                if free_space > 0:
                    for h_idx, h_state in enumerate(sim_harvests):
                        if h_state["remaining_yield"] > 0:
                            h_pos = h_state["tile_pos"]
                            dist_to_wheat = abs(w_pos[0] - h_pos[0]) + abs(w_pos[1] - h_pos[1])
                            dist_wheat_to_animal = abs(h_pos[0] - a_pos[0]) + abs(h_pos[1] - a_pos[1])
                            comp = w_hour + dist_to_wheat + 1 + dist_wheat_to_animal + 1  # travel wheat + 1 (HARVEST) + travel animal + 1 (FEED)
                            if comp <= deadline and comp < best_completion:
                                best_completion = comp
                                best_route = ("HARVEST", w_id, h_idx, comp)

            if best_route is not None:
                route_type, chosen_w_id, chosen_h_idx, comp = best_route
                fed_count += 1
                if route_type == "CARRIED":
                    sim_workers[chosen_w_id]["wheat"] -= 1
                    sim_workers[chosen_w_id]["carried_total"] = max(0, sim_workers[chosen_w_id]["carried_total"] - 1)
                elif route_type == "SHED":
                    sim_shed_wheat -= 1
                elif route_type == "HARVEST":
                    # Multi-unit wheat harvest respecting worker backpack capacity (max 20 units total)
                    h_rem = sim_harvests[chosen_h_idx]["remaining_yield"]
                    free_sp = max(0, 20 - sim_workers[chosen_w_id]["carried_total"])
                    collected = min(h_rem, free_sp)
                    if collected >= 1:
                        sim_harvests[chosen_h_idx]["remaining_yield"] -= collected
                        # 1 unit consumed for feeding, remaining carried in backpack
                        retained = collected - 1
                        sim_workers[chosen_w_id]["wheat"] += retained
                        sim_workers[chosen_w_id]["carried_total"] += retained
                    else:
                        sim_harvests[chosen_h_idx]["remaining_yield"] -= 1

                sim_workers[chosen_w_id]["pos"] = a_pos
                sim_workers[chosen_w_id]["avail_hour"] = comp
                assigned_routes.append({
                    "animal_pos": a_pos,
                    "deadline": deadline,
                    "route_type": route_type,
                    "worker_id": chosen_w_id,
                    "completion_hour": comp,
                })
            else:
                day_0_feasible = False
                unfed_reasons.append(f"Animal at {a_pos} (deadline H{deadline}) has no feasible physical feeding route")

        if today_demand > 0 and fed_count < today_demand:
            day_0_feasible = False

        # Remaining physical inventory at end of Day 0
        rem_carried = sum(w["wheat"] for w in sim_workers.values())
        rem_inventory_day_0 = sim_shed_wheat + rem_carried

        daily_projection[self.day] = {
            "opening_balance": self.shed_wheat + self.worker_carried_wheat,
            "harvest_inflow": 0,
            "feed_demand": today_demand,
            "closing_balance": rem_inventory_day_0 if day_0_feasible else -len(unfed_reasons),
            "is_solvent": day_0_feasible,
            "unfed_reasons": unfed_reasons,
            "assigned_routes": assigned_routes,
        }

        # 2. Future days projection (conservative, non-double-counted)
        running_balance = max(0, rem_inventory_day_0)
        for offset in range(1, horizon_days):
            check_day = self.day + offset
            if check_day >= 30:
                break
            harvest_inflow = self.get_projected_mature_wheat(check_day)
            feed_demand = sum(1 for liab in self.feed_liabilities if liab.day == check_day)
            closing = running_balance + harvest_inflow - feed_demand
            is_solv = (closing >= 0) and day_0_feasible
            daily_projection[check_day] = {
                "opening_balance": running_balance,
                "harvest_inflow": harvest_inflow,
                "feed_demand": feed_demand,
                "closing_balance": closing,
                "is_solvent": is_solv,
            }
            running_balance = max(0, closing)

        min_bal = min((d["closing_balance"] for d in daily_projection.values()), default=rem_inventory_day_0)
        is_safe = all(d["is_solvent"] for d in daily_projection.values())

        return {
            "current_accessible": self.shed_wheat + self.worker_carried_wheat,
            "daily": daily_projection,
            "min_projected_balance": min_bal,
            "is_feed_safe": is_safe,
            "day_0_feasible": day_0_feasible,
            "unfed_reasons": unfed_reasons,
        }

    # --- Market Order Capacity Management ---

    def can_reserve_market_slots(self, day: int, hour: int, slots_needed: int) -> bool:
        """Check if market turn has sufficient unused order slots (maximum 10 commands per turn)."""
        existing = sum(
            alloc.slots_consumed
            for alloc in self.turn_order_allocations.get((day, hour), [])
        )
        return (existing + slots_needed) <= 10

    def allocate_market_slots(
        self,
        day: int,
        hour: int,
        command_type: str,
        slots_consumed: int,
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Allocate order slots on a specific market turn (day, hour)."""
        if not self.can_reserve_market_slots(day, hour, slots_consumed):
            return False

        key = (day, hour)
        if key not in self.turn_order_allocations:
            self.turn_order_allocations[key] = []
        self.turn_order_allocations[key].append(
            MarketSlotAllocation(command_type, slots_consumed, details or {})
        )
        return True

    def get_market_slots_remaining(self, day: int, hour: int) -> int:
        """Return free market order slots for (day, hour)."""
        existing = sum(
            alloc.slots_consumed
            for alloc in self.turn_order_allocations.get((day, hour), [])
        )
        return max(0, 10 - existing)

    # --- Storage Ledger Management ---

    def project_storage_headroom(self) -> int:
        """Return conservative available shed space accounting for carried goods."""
        shed_free = max(0, self.shed_capacity - self.current_shed_occupancy)
        net_headroom = shed_free - self.current_worker_carried_units
        return max(0, net_headroom)

    def project_storage_timeline(
        self,
        horizon_hours: int = 24,
        planned_sales: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Project physical storage timeline from current hour through midnight.

        Models the execution sequence:
        HARVEST -> worker inventory -> movement to shed -> PLACE -> shed inventory
        -> market SELL -> cash -> midnight auto-drop of remaining worker inventory -> overflow discard.
        """
        sales = planned_sales or []
        sales_by_hour: Dict[int, int] = {}
        wheat_sales_by_hour: Dict[int, int] = {}
        orders_by_hour: Dict[int, int] = {}
        for s in sales:
            h = s.get("hour", 0)
            q = int(s.get("quantity", 0))
            prod = str(s.get("product", "")).upper()
            sales_by_hour[h] = sales_by_hour.get(h, 0) + q
            if prod == "WHEAT":
                wheat_sales_by_hour[h] = wheat_sales_by_hour.get(h, 0) + q
            orders_by_hour[h] = orders_by_hour.get(h, 0) + 1

        timeline: Dict[int, Dict[str, Any]] = {}
        shed_occ = self.current_shed_occupancy
        worker_carried = copy.deepcopy({w.worker_id: dict(w.inventory) for w in self.workers})

        expected_overflow = 0
        discarded_products: Dict[str, int] = {}
        overflow_workers: List[int] = []

        total_wheat_sold_timeline = 0
        for h in range(self.hour, min(24, self.hour + horizon_hours)):
            # 1. Worker deposits at shed if reaching shed at hour h
            for w in self.workers:
                w_id = w.worker_id
                if w.earliest_deposit_hour == h and w_id in worker_carried:
                    items = worker_carried[w_id]
                    tot = sum(items.values())
                    if tot > 0:
                        # Deposit into shed up to capacity
                        avail = max(0, self.shed_capacity - shed_occ)
                        dep = min(tot, avail)
                        shed_occ += dep
                        # Conserve inventory: deduct deposited items from worker_carried[w_id], leaving undeposited remainder
                        remaining_to_dep = dep
                        new_inv = {}
                        for prod, cnt in items.items():
                            if remaining_to_dep > 0:
                                take = min(cnt, remaining_to_dep)
                                remaining_to_dep -= take
                                if cnt - take > 0:
                                    new_inv[prod] = cnt - take
                            else:
                                new_inv[prod] = cnt
                        worker_carried[w_id] = new_inv

            # 2. Market sales from shed (cannot sell from backpack!)
            sold = sales_by_hour.get(h, 0)
            actual_sold = 0
            if sold > 0:
                actual_sold = min(shed_occ, sold)
                shed_occ -= actual_sold

            w_sold_h = min(actual_sold, wheat_sales_by_hour.get(h, 0))
            total_wheat_sold_timeline += w_sold_h

            total_carried_now = sum(sum(inv.values()) for inv in worker_carried.values())
            timeline[h] = {
                "shed_occupancy": shed_occ,
                "worker_carried": total_carried_now,
                "sales": sold,
                "actual_sold": actual_sold,
            }

        # 3. Midnight auto-transfer of remaining backpack goods into shed
        remaining_carried = sum(sum(inv.values()) for inv in worker_carried.values())
        potential_midnight_shed = shed_occ + remaining_carried

        rescue_relief_units = 0
        try:
            from config import get_midnight_storage_dump_mode
            rescue_mode = (get_midnight_storage_dump_mode() == "RESCUE")
        except Exception:
            try:
                from agent.config import get_midnight_storage_dump_mode
                rescue_mode = (get_midnight_storage_dump_mode() == "RESCUE")
            except Exception:
                rescue_mode = True

        # Production Controller Parity for Storage Rescue:
        # - Rescue only active at Hour 23, Day < 29
        # - Triggers only when projected midnight load (shed + carried) > 98
        # - Deducts specifically from available WHEAT in shed (not non-wheat sales)
        # - Enforces feed reserve: max(10, animals * 2)
        # - Enforces market order limit: cannot execute if 10 orders already planned for Hour 23
        orders_at_h23 = orders_by_hour.get(23, 0)
        rescue_eligible = (
            rescue_mode and
            self.day < 29 and
            self.hour <= 23 and
            potential_midnight_shed > 98 and
            orders_at_h23 < 10
        )
        if rescue_eligible:
            anim_cnt = len({l.animal_pos for l in self.feed_liabilities if l.day == self.day})
            if anim_cnt == 0:
                anim_cnt = len({l.animal_pos for l in self.feed_liabilities})
            safe_w = max(10, anim_cnt * 2)
            shed_w = max(0, self.shed_wheat - total_wheat_sold_timeline)
            can_sell_w = max(0, shed_w - safe_w)
            needed_relief = potential_midnight_shed - 98
            rescue_relief_units = min(can_sell_w, needed_relief)
            if rescue_relief_units > 0:
                shed_occ -= rescue_relief_units
                potential_midnight_shed -= rescue_relief_units
                if 23 in timeline:
                    timeline[23]["sales"] += rescue_relief_units
                    timeline[23]["actual_sold"] += rescue_relief_units
                    timeline[23]["shed_occupancy"] -= rescue_relief_units

        if potential_midnight_shed > self.shed_capacity:
            expected_overflow = potential_midnight_shed - self.shed_capacity
            # Identify discarded products and workers
            overflow_rem = expected_overflow
            for w_id, inv in worker_carried.items():
                if sum(inv.values()) > 0:
                    overflow_workers.append(w_id)
                for prod, cnt in inv.items():
                    if overflow_rem <= 0:
                        break
                    disc = min(cnt, overflow_rem)
                    discarded_products[prod] = discarded_products.get(prod, 0) + disc
                    overflow_rem -= disc
            final_shed = self.shed_capacity
            final_carried = 0
        else:
            expected_overflow = 0
            final_shed = potential_midnight_shed
            final_carried = 0
        initial_carried = sum(sum(w.inventory.values()) for w in self.workers)
        initial_physical_total = self.current_shed_occupancy + initial_carried
        total_sold = sum(entry["actual_sold"] for entry in timeline.values())
        final_physical_total = final_shed + final_carried
        inventory_conserved = (initial_physical_total - total_sold - expected_overflow == final_physical_total)
        peak_shed = max((entry["shed_occupancy"] for entry in timeline.values()), default=self.current_shed_occupancy)
        peak_carried = max((entry["worker_carried"] for entry in timeline.values()), default=initial_carried)

        return {
            "initial_shed_occupancy": self.current_shed_occupancy,
            "initial_worker_carried": initial_carried,
            "peak_usage": peak_shed,
            "peak_shed_occupancy": peak_shed,
            "peak_carried_units": peak_carried,
            "final_projected_shed": final_shed,
            "final_projected_carried": final_carried,
            "expected_overflow": expected_overflow,
            "rescue_relief_units": rescue_relief_units,
            "discarded_products": discarded_products,
            "overflow_workers": overflow_workers,
            "is_storage_safe": (expected_overflow == 0),
            "timeline": timeline,
            "inventory_conserved": inventory_conserved,
        }

    def snapshot(self) -> Dict[str, Any]:
        """Return immutable deep-copy summary for telemetry."""
        return {
            "day": self.day,
            "hour": self.hour,
            "cash_on_hand": self.cash_on_hand,
            "safety_reserve": self.safety_reserve,
            "discretionary_cash": self.get_uncommitted_discretionary_cash(),
            "total_hard_liabilities": sum(l.amount for l in self.dated_liabilities if l.is_hard),
            "accessible_wheat": self.get_accessible_wheat_now(),
            "shed_wheat": self.shed_wheat,
            "worker_wheat": self.worker_carried_wheat,
            "shed_occupancy": self.current_shed_occupancy,
            "feed_safe": self.project_feed_balance(horizon_days=3)["is_feed_safe"],
            "storage_safe": self.project_storage_timeline()["is_storage_safe"],
        }
