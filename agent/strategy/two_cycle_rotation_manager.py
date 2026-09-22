"""Kaggriculture P5.1 — Two-Cycle Carrot Rotation Manager.

Manages the lifecycle of two-cycle carrot rotations on NW+NE core tiles on Days 21-23:
Cycle 1: Planted Day D in {21, 22, 23}, harvested Day D+3 intraday.
Cycle 2: Planted Day D+3 intraday (<=17), harvested Day D+6 (Days 27, 28, or 29).

Enforces:
1. Sequential Day-by-Day Collective Feed Safety Ledger (prevents starvation, preserves feed buffer).
2. Confirmed action state machine (tracks observation: planting, planting-day watering, harvest).
3. Hour 0 Seed Pre-Ordering & P1 Urgency flag for market arbitration.
4. Tile reservation to prevent same-day wheat queue competition in MacroPlanner.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import os
import sys
from typing import Dict, List, Optional, Set, Tuple, Any

# Engine constants mirror
CROPS = {
    "WHEAT":  dict(seed=10, first_yield_day=2, max_yield_day=4, max_yield=6, window_start=2),
    "CARROT": dict(seed=20, first_yield_day=2, max_yield_day=3, max_yield=4, window_start=2),
}
FEED_WHEAT_BUFFER_DAYS = 2.0


class RotationPhase(str, Enum):
    IDLE = "IDLE"
    C1_RESERVED = "C1_RESERVED"       # Approved on Day D in [21..23]; seed ordered; tile reserved
    C1_PLANTED = "C1_PLANTED"         # Observed planted with CARROT on Day D
    C1_WATERED_D0 = "C1_WATERED_D0"   # Confirmed watered on planting day D
    C1_GROWING = "C1_GROWING"         # Days D+1, D+2, D+3 growing & bonus watering
    C2_RESERVED = "C2_RESERVED"       # Day D+3 Hour 0: C2 seed ordered; tile reserved for C2 replant
    C1_HARVESTED = "C1_HARVESTED"     # Day D+3 intraday: C1 harvested, tile EMPTY, awaiting replant
    C2_PLANTED = "C2_PLANTED"         # Day D+3 intraday (<=17): observed planted with CARROT
    C2_WATERED_D0 = "C2_WATERED_D0"   # Confirmed watered on planting day D+3
    C2_GROWING = "C2_GROWING"         # Days D+4, D+5, D+6 growing & bonus watering
    COMPLETED = "COMPLETED"           # Day D+6: C2 harvested and realized
    FAILED = "FAILED"                 # Aborted due to missed seed, missed planting, or missed water


@dataclass
class RotationRecord:
    pos: Tuple[int, int]
    c1_plant_day: int
    phase: RotationPhase = RotationPhase.C1_RESERVED
    c1_planted_confirmed: bool = False
    c1_d0_watered_confirmed: bool = False
    c1_harvested_confirmed: bool = False
    c2_plant_day: Optional[int] = None
    c2_planted_confirmed: bool = False
    c2_d0_watered_confirmed: bool = False
    c2_harvested_confirmed: bool = False
    failure_reason: Optional[str] = None
    log: List[str] = field(default_factory=list)

    def transition(self, new_phase: RotationPhase, reason: str = ""):
        self.phase = new_phase
        self.log.append(f"-> {new_phase.value} ({reason})")


class TwoCycleRotationManager:
    def __init__(self):
        self.rotations: Dict[Tuple[int, int], RotationRecord] = {}
        self.committed_c1_this_day: int = 0
        self.last_day: int = -1

    def reset(self):
        """Cleanly reset all rotation state between matches."""
        self.rotations.clear()
        self.committed_c1_this_day = 0
        self.last_day = -1

    def get_active_rotation_tiles(self) -> Set[Tuple[int, int]]:
        """Tiles currently under active management that must NOT be claimed by generic wheat."""
        active = set()
        for pos, rec in self.rotations.items():
            if rec.phase not in (RotationPhase.IDLE, RotationPhase.COMPLETED, RotationPhase.FAILED):
                active.add(pos)
        return active

    def get_c2_replant_tiles(self) -> List[Tuple[int, int]]:
        """Tiles where C1 has been harvested (or is empty) and C2 CARROT must be planted."""
        replant = []
        for pos, rec in self.rotations.items():
            if rec.phase in (RotationPhase.C2_RESERVED, RotationPhase.C1_HARVESTED):
                replant.append(pos)
        return replant

    def get_c2_maturing_today_count(self, day: int) -> int:
        """Count of C1 rotations that reach max yield today (Day D+3) and need C2 seed pre-ordered."""
        count = 0
        for pos, rec in self.rotations.items():
            if rec.phase in (RotationPhase.C1_WATERED_D0, RotationPhase.C1_GROWING):
                if rec.c1_plant_day + 3 == day:
                    count += 1
        return count

    def get_pending_plant_tiles(self, day: int, hour: int) -> List[Tuple[int, int]]:
        """Returns tiles that are reserved for CARROT planting (C1 or C2) and need to be in plant_queue."""
        pending = []
        if hour > 17:
            return pending
        for pos, rec in self.rotations.items():
            if rec.phase == RotationPhase.C1_RESERVED and day == rec.c1_plant_day:
                pending.append(pos)
            elif rec.phase == RotationPhase.C1_HARVESTED and day <= rec.c1_plant_day + 3:
                pending.append(pos)
        return pending

    def update_from_observation(self, ctx: Dict[str, Any]):
        """Update rotation state machine based on authoritative engine observations."""
        day = ctx.get("day", 0)
        hour = ctx.get("hour", 0)
        farm = ctx.get("farm")
        if farm is None:
            return

        if day != self.last_day:
            self.last_day = day
            self.committed_c1_this_day = 0

        for pos, rec in list(self.rotations.items()):
            tx, ty = pos
            tile = farm.tiles[ty][tx]
            is_plant = getattr(tile, "is_plant", False)
            crop = getattr(tile, "crop", "")
            watered = getattr(tile, "watered_today", False)
            kind = getattr(tile, "kind", "NONE")
            is_empty = (kind == "EMPTY" or (not is_plant and not getattr(tile, "is_animal", False)))

            # State transitions
            if rec.phase == RotationPhase.C1_RESERVED:
                if is_plant and crop == "CARROT":
                    rec.c1_planted_confirmed = True
                    if watered:
                        rec.c1_d0_watered_confirmed = True
                        rec.transition(RotationPhase.C1_WATERED_D0, f"Planted & watered D{day} H{hour:02d}")
                    else:
                        rec.transition(RotationPhase.C1_PLANTED, f"Planted D{day} H{hour:02d}")
                elif day > rec.c1_plant_day:
                    rec.failure_reason = f"C1 plant missed on Day {rec.c1_plant_day}"
                    rec.transition(RotationPhase.FAILED, rec.failure_reason)

            elif rec.phase == RotationPhase.C1_PLANTED:
                if watered:
                    rec.c1_d0_watered_confirmed = True
                    rec.transition(RotationPhase.C1_WATERED_D0, f"Watered D0 D{day} H{hour:02d}")
                elif day > rec.c1_plant_day:
                    rec.failure_reason = f"C1 missed planting-day water on Day {rec.c1_plant_day}"
                    rec.transition(RotationPhase.FAILED, rec.failure_reason)

            elif rec.phase == RotationPhase.C1_WATERED_D0:
                if day > rec.c1_plant_day:
                    rec.transition(RotationPhase.C1_GROWING, f"Advancing to growing on Day {day}")

            elif rec.phase == RotationPhase.C1_GROWING:
                # On Day D+3 at Hour 0: C1 is maturing today
                if day == rec.c1_plant_day + 3 and hour == 0:
                    rec.transition(RotationPhase.C2_RESERVED, f"C1 maturing today on Day {day}, pre-ordering C2 seed")
                elif day > rec.c1_plant_day + 3 and is_empty:
                    # Harvested without hitting H00 in growing
                    rec.c1_harvested_confirmed = True
                    rec.transition(RotationPhase.C1_HARVESTED, f"C1 harvested D{day} H{hour:02d}")

            elif rec.phase == RotationPhase.C2_RESERVED:
                if is_empty:
                    rec.c1_harvested_confirmed = True
                    rec.transition(RotationPhase.C1_HARVESTED, f"C1 harvested D{day} H{hour:02d}")
                elif is_plant and crop == "CARROT" and rec.c1_harvested_confirmed:
                    # Already replanted
                    rec.c2_plant_day = day
                    rec.c2_planted_confirmed = True
                    if watered:
                        rec.c2_d0_watered_confirmed = True
                        rec.transition(RotationPhase.C2_WATERED_D0, f"C2 planted & watered D{day} H{hour:02d}")
                    else:
                        rec.transition(RotationPhase.C2_PLANTED, f"C2 planted D{day} H{hour:02d}")

            elif rec.phase == RotationPhase.C1_HARVESTED:
                if is_plant and crop == "CARROT":
                    rec.c2_plant_day = day
                    rec.c2_planted_confirmed = True
                    if watered:
                        rec.c2_d0_watered_confirmed = True
                        rec.transition(RotationPhase.C2_WATERED_D0, f"C2 planted & watered D{day} H{hour:02d}")
                    else:
                        rec.transition(RotationPhase.C2_PLANTED, f"C2 planted D{day} H{hour:02d}")
                elif is_plant and crop == "WHEAT":
                    rec.failure_reason = f"Tile hijacked by wheat on D{day} H{hour:02d}"
                    rec.transition(RotationPhase.FAILED, rec.failure_reason)
                elif day > rec.c1_plant_day + 3 and hour > 17 and is_empty:
                    # Missed replant deadline
                    rec.failure_reason = f"C2 replant deadline missed (empty at D{day} H{hour:02d})"
                    rec.transition(RotationPhase.FAILED, rec.failure_reason)

            elif rec.phase == RotationPhase.C2_PLANTED:
                if watered:
                    rec.c2_d0_watered_confirmed = True
                    rec.transition(RotationPhase.C2_WATERED_D0, f"C2 watered D0 D{day} H{hour:02d}")
                elif day > (rec.c2_plant_day or day):
                    rec.failure_reason = f"C2 missed planting-day water on Day {rec.c2_plant_day}"
                    rec.transition(RotationPhase.FAILED, rec.failure_reason)

            elif rec.phase == RotationPhase.C2_WATERED_D0:
                if day > (rec.c2_plant_day or day):
                    rec.transition(RotationPhase.C2_GROWING, f"C2 growing on Day {day}")

            elif rec.phase == RotationPhase.C2_GROWING:
                c2_harvest_day = (rec.c2_plant_day or (rec.c1_plant_day + 3)) + 3
                if day >= c2_harvest_day:
                    if is_empty or (is_plant and getattr(tile, "yield_units", 0) == 0 and day > c2_harvest_day):
                        rec.c2_harvested_confirmed = True
                        rec.transition(RotationPhase.COMPLETED, f"C2 harvested and realized D{day} H{hour:02d}")

    def evaluate_sequential_feed_safety(
        self,
        ctx: Dict[str, Any],
        proposed_wheat_tiles: List[Tuple[int, int]],
    ) -> List[Tuple[int, int]]:
        """Sequentially evaluates candidate wheat tiles against the engine-exact day-by-day feed ledger.
        Returns the subset of candidate tiles that can be safely converted to CARROT.
        """
        day = ctx.get("day", 0)
        farm = ctx.get("farm")
        priv = ctx.get("private")
        if not farm or not priv:
            return []

        # 1. Base supply: current liquid wheat stock
        shed_wheat = int(priv.shed.get("WHEAT", 0)) if hasattr(priv, "shed") else 0
        worker_wheat = sum(int(inv.get("WHEAT", 0)) for inv in getattr(priv, "inventories", []))
        initial_stock = float(shed_wheat + worker_wheat)

        # 2. Herd feed demand per day
        animals = [t for t in farm.iter_tiles() if getattr(t, "is_animal", False)]
        wheat_animals = [a for a in animals if getattr(a, "animal", "") in ("COW", "SHEEP")]
        herd_size = len(wheat_animals)
        if herd_size == 0:
            # Zero wheat livestock: 100% feed safe for all core tiles
            return list(proposed_wheat_tiles)

        # 3. Future harvests from EXISTING in-ground wheat tiles
        future_harvests = defaultdict(float)
        for t in farm.iter_tiles():
            if getattr(t, "is_plant", False) and getattr(t, "crop", "") == "WHEAT":
                p_day = getattr(t, "planted_day", day)
                h_day = p_day + 4
                if h_day <= 28:
                    bonus_days = sum(1 for k in (2, 3, 4) if p_day + k <= 28)
                    fert_until = getattr(t, "fertilized_until_day", -1)
                    if fert_until >= h_day:
                        y = min(6.0, 1.0 + 2.0 * bonus_days)
                    else:
                        y = min(4.0, 1.0 + 1.0 * bonus_days)
                    future_harvests[h_day] += y

        # 4. Include proposed baseline wheat plantings that will harvest on Day day+4
        cand_harvest_day = day + 4
        unconverted_wheat_count = len(proposed_wheat_tiles)
        if cand_harvest_day <= 28:
            future_harvests[cand_harvest_day] += unconverted_wheat_count * 4.0

        # Helper to test ledger feasibility
        def is_ledger_safe(harvest_map) -> bool:
            b = initial_stock
            safety_buf = float(herd_size * FEED_WHEAT_BUFFER_DAYS)
            for d in range(day, 29):
                b += harvest_map.get(d, 0.0)
                # Feed demand on day d
                if d == day:
                    unfed = sum(1 for a in wheat_animals if not getattr(a, "fed_today", False))
                    demand = unfed
                else:
                    demand = herd_size
                b -= demand
                if b < safety_buf:
                    return False
            return True

        proposed_wheat_tiles = [p for p in proposed_wheat_tiles if p not in self.rotations]
        admitted_tiles = []
        current_harvests = dict(future_harvests)

        for pos in proposed_wheat_tiles:
            # Test removing 1 wheat planting (4 units on cand_harvest_day)
            trial_harvests = dict(current_harvests)
            if cand_harvest_day <= 28:
                trial_harvests[cand_harvest_day] = max(0.0, trial_harvests.get(cand_harvest_day, 0.0) - 4.0)

            if is_ledger_safe(trial_harvests):
                admitted_tiles.append(pos)
                current_harvests = trial_harvests
            else:
                # Feed boundary reached; reject remaining candidates
                break

        return admitted_tiles

    def commit_c1_candidates(
        self,
        day: int,
        admitted_tiles: List[Tuple[int, int]],
    ):
        """Commit approved tiles to Cycle 1."""
        for pos in admitted_tiles:
            if pos in self.rotations:
                continue
            rec = RotationRecord(pos=pos, c1_plant_day=day, phase=RotationPhase.C1_RESERVED)
            rec.log.append(f"Committed C1 on Day {day}")
            self.rotations[pos] = rec
            self.committed_c1_this_day += 1


# Global module singleton
_ROTATION_MANAGER: Optional[TwoCycleRotationManager] = None

def get_rotation_manager() -> TwoCycleRotationManager:
    global _ROTATION_MANAGER
    if _ROTATION_MANAGER is None:
        _ROTATION_MANAGER = TwoCycleRotationManager()
    return _ROTATION_MANAGER

def reset_rotation_manager():
    global _ROTATION_MANAGER
    if _ROTATION_MANAGER is not None:
        _ROTATION_MANAGER.reset()
