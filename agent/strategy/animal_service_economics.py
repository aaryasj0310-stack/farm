"""Phase M0-F: Adaptive Animal CARE & Feed-Bank Economics Model.

Authoritative forward simulator and economic evaluator for animal servicing:
1. Exact future production schedules (COW, SHEEP, GOOSE).
2. Care bank accumulation, realization, and max-held clipping.
3. Strict survival constraints (consecutive_unfed == 1 -> MANDATORY FEED).
4. Marginal economic value calculation (expected product value vs wheat + labor opportunity costs).
5. Comprehensive telemetry tracking for audit and experiments.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Tuple

ANIMALS_SPEC = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

PRODUCT_BASE_PRICES = {
    "WHEAT": 25.0,
    "EGG": 50.0,
    "MILK": 160.0,
    "WOOL": 200.0,
}

_TELEMETRY: Dict[str, Any] = {
    "animal_days_evaluated": 0,
    "feed_actions_baseline": 0,
    "feed_actions_treatment": 0,
    "feed_actions_skipped": 0,
    "care_actions_baseline": 0,
    "care_actions_treatment": 0,
    "care_actions_skipped": 0,
    "wheat_units_saved": 0,
    "worker_actions_saved": 0,
    "care_bonus_generated": 0,
    "care_bonus_realized": 0,
    "care_bonus_clipped": 0,
    "reasons_feed_skipped": {},
    "reasons_care_skipped": {},
    "species_stats": {
        sp: {
            "feed_baseline": 0, "feed_treatment": 0, "feed_skipped": 0,
            "care_baseline": 0, "care_treatment": 0, "care_skipped": 0,
            "bonus_generated": 0, "bonus_realized": 0, "bonus_clipped": 0,
            "yield_produced": 0,
        }
        for sp in ("COW", "SHEEP", "GOOSE")
    },
    "ledger": [],
}


def reset_animal_service_telemetry() -> None:
    global _TELEMETRY
    _TELEMETRY = {
        "animal_days_evaluated": 0,
        "feed_actions_baseline": 0,
        "feed_actions_treatment": 0,
        "feed_actions_skipped": 0,
        "care_actions_baseline": 0,
        "care_actions_treatment": 0,
        "care_actions_skipped": 0,
        "wheat_units_saved": 0,
        "worker_actions_saved": 0,
        "care_bonus_generated": 0,
        "care_bonus_realized": 0,
        "care_bonus_clipped": 0,
        "reasons_feed_skipped": {},
        "reasons_care_skipped": {},
        "species_stats": {
            sp: {
                "feed_baseline": 0, "feed_treatment": 0, "feed_skipped": 0,
                "care_baseline": 0, "care_treatment": 0, "care_skipped": 0,
                "bonus_generated": 0, "bonus_realized": 0, "bonus_clipped": 0,
                "yield_produced": 0,
            }
            for sp in ("COW", "SHEEP", "GOOSE")
        },
        "ledger": [],
    }


def get_animal_service_telemetry() -> Dict[str, Any]:
    return copy.deepcopy(_TELEMETRY)


def get_animal_service_mode() -> str:
    try:
        from config import get_animal_service_economics_mode as _cfg_mode
        return _cfg_mode()
    except Exception:
        try:
            from agent.config import get_animal_service_economics_mode as _cfg_mode
            return _cfg_mode()
        except Exception:
            return "OFF"


def is_adaptive_animal_service_enabled() -> bool:
    return get_animal_service_mode() == "LIVE"


def is_animal_service_shadow() -> bool:
    return get_animal_service_mode() == "SHADOW"


def is_production_day(species: str, placed_day: int, day: int) -> bool:
    """True if this animal produces at end-of-day refresh on `day`."""
    spec = ANIMALS_SPEC.get(species)
    if not spec:
        return False
    next_day = day + 1
    days_since_first = next_day - placed_day - spec["first_yield_day"]
    return days_since_first >= 0 and days_since_first % spec["interval"] == 0


def get_future_production_days(species: str, placed_day: int, from_day: int, max_day: int = 29) -> List[int]:
    """List of all future calendar days on which this animal will refresh production."""
    prods = []
    for d in range(from_day, max_day + 1):
        if is_production_day(species, placed_day, d):
            prods.append(d)
    return prods


def next_production_day(species: str, placed_day: int, current_day: int) -> Optional[int]:
    """Return the next calendar day when production occurs, or None if none remain."""
    future = get_future_production_days(species, placed_day, current_day)
    return future[0] if future else None


def evaluate_animal_service_opportunity(
    tile: Any,
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Authoritative evaluation of whether an animal should be FEEDed and/or CAREd today.

    Returns dict with decisions:
      - should_feed: bool
      - feed_reason: str
      - should_care: bool
      - care_reason: str
      - metrics: dict
    """
    species = getattr(tile, "animal", None)
    if species not in ANIMALS_SPEC:
        return {
            "should_feed": False, "feed_reason": "NOT_ANIMAL",
            "should_care": False, "care_reason": "NOT_ANIMAL",
            "metrics": {},
        }

    spec = ANIMALS_SPEC[species]
    day = int(ctx.get("day", 0))
    placed_day = int(getattr(tile, "placed_day", 0))
    consecutive_unfed = int(getattr(tile, "consecutive_unfed", 0))
    pending_bonus = int(getattr(tile, "pending_care_bonus", 0))
    yield_units = int(getattr(tile, "yield_units", 0))
    max_held = int(spec["max_held"])
    interval = int(spec["interval"])
    prod_name = spec["product"]

    prod_today = is_production_day(species, placed_day, day)
    future_prods = get_future_production_days(species, placed_day, day)

    # -------------------------------------------------------------
    # 1. FEED Decision
    # -------------------------------------------------------------
    # Rule 1: Survival Guarantee (HARD CONSTRAINT)
    # If consecutive_unfed >= 1, MUST FEED today to prevent escape at midnight!
    if consecutive_unfed >= 1:
        should_feed = True
        feed_reason = "MANDATORY_SURVIVAL_FEED"

    # Rule 2: Production Day Realization
    # On a production day, feeding consumes the accumulated care bank and produces base yield.
    elif prod_today:
        should_feed = True
        feed_reason = "REALIZE_BANK_ON_PRODUCTION_DAY" if pending_bonus > 0 else "BASE_PRODUCTION_DAY_FEED"

    # Rule 3: Off-production day
    else:
        # Check if next production day exists
        next_prod = future_prods[0] if future_prods else None
        if next_prod is None:
            # No future production days remain in season -> feeding off-day is pure waste
            should_feed = False
            feed_reason = "NO_FUTURE_PRODUCTION"
        else:
            # Next production day exists.
            # Can we skip feed today without losing needed production capacity?
            # Max bonus needed to reach max_held is: max(0, max_held - 1 - yield_units)
            needed_bonus = max(0, max_held - 1 - yield_units)
            if pending_bonus >= needed_bonus and needed_bonus > 0:
                # Care bank is ALREADY sufficient to max out production!
                # Banking another care bonus would clip and be destroyed!
                should_feed = False
                feed_reason = "CARE_BANK_ALREADY_SUFFICIENT"
            elif species == "GOOSE":
                # Geese produce every day (interval 1), off-production day doesn't exist once day >= 4
                should_feed = True
                feed_reason = "GOOSE_DAILY_FEED"
            else:
                # For COW and SHEEP off-production days:
                # Skipping feed saves 1 wheat + 1 worker action, but consecutive_unfed becomes 1.
                # Must be fed tomorrow (survival mandatory tomorrow).
                # If tomorrow is a production day, tomorrow's feed is mandatory anyway!
                # If next_prod == day + 1: tomorrow is production day.
                # If we skip today, consecutive_unfed becomes 1, and tomorrow we feed and harvest.
                # Does skipping today hurt tomorrow's production?
                # Tomorrow's bonus consumes pending_bonus.
                # Skipping today only means we don't ADD +1 to pending_bonus today.
                if pending_bonus >= max_held - 1:
                    should_feed = False
                    feed_reason = "CARE_BANK_MAXED"
                else:
                    # Off-day feeding is optional. Let's see if adding +1 care bonus is economically worth 1 wheat + 1 labor.
                    # Price of milk ($160) or wool ($200) vs wheat ($25).
                    # A single unit of milk/wool is worth 6-8x wheat!
                    # BUT only if it doesn't clip!
                    if yield_units + 1 + pending_bonus + 1 > max_held:
                        should_feed = False
                        feed_reason = "CARE_BONUS_WOULD_CLIP"
                    else:
                        should_feed = True
                        feed_reason = "CARE_BANK_ACCUMULATION"

    # -------------------------------------------------------------
    # 2. CARE Decision
    # -------------------------------------------------------------
    # Rule 1: CARE requires fed_today to bank!
    if not should_feed:
        should_care = False
        care_reason = "UNFED_ANIMAL_CANNOT_BANK_CARE"

    # Rule 2: Next realizable production day check
    # If today is a production day, today's CARE banks for the NEXT production day after today.
    # If today is off-day, today's CARE banks for the next production day (>= day).
    else:
        target_prod_days = [d for d in future_prods if d > day] if prod_today else future_prods
        if not target_prod_days:
            should_care = False
            care_reason = "NO_FUTURE_PRODUCTION_EVENT"
        else:
            # Check max-held clipping
            # In the next production: yield = min(max_held, yield_units + 1 + pending_bonus + (1 if care else 0))
            if prod_today:
                # On production day, existing pending_bonus is consumed TODAY.
                # So for the NEXT cycle, pending_bonus starts at 0!
                # Today's CARE will be the 1st unit in the new bank.
                # Will next production cycle clip? Only if yield_units is already at max_held and never harvested.
                if yield_units >= max_held:
                    should_care = False
                    care_reason = "EXISTING_YIELD_AT_MAX_HELD"
                else:
                    should_care = True
                    care_reason = "BANK_FOR_NEXT_CYCLE"
            else:
                # Off-production day:
                effective_yield_projected = yield_units + 1 + pending_bonus + 1
                if effective_yield_projected > max_held:
                    should_care = False
                    care_reason = "CARE_CLIPS_MAX_HELD"
                elif day >= 28:
                    should_care = False
                    care_reason = "ENDGAME_TOO_LATE"
                else:
                    should_care = True
                    care_reason = "CARE_PROFITABLE"

    metrics = {
        "species": species,
        "day": day,
        "placed_day": placed_day,
        "prod_today": prod_today,
        "consecutive_unfed": consecutive_unfed,
        "yield_units": yield_units,
        "pending_bonus": pending_bonus,
        "max_held": max_held,
        "future_prod_count": len(future_prods),
    }

    return {
        "should_feed": should_feed,
        "feed_reason": feed_reason,
        "should_care": should_care,
        "care_reason": care_reason,
        "metrics": metrics,
    }


def record_animal_service_audit(
    species: str,
    day: int,
    hour: int,
    prod_today: bool,
    baseline_feed: bool,
    adaptive_feed: bool,
    feed_reason: str,
    baseline_care: bool,
    adaptive_care: bool,
    care_reason: str,
    yield_before: int,
    bank_before: int,
    consecutive_unfed: int,
    wheat_price: float = 25.0,
    prod_price: float = 160.0,
) -> None:
    """Record turn-by-turn audit ledger comparing baseline vs adaptive servicing."""
    global _TELEMETRY
    _TELEMETRY["animal_days_evaluated"] += 1
    sp_stats = _TELEMETRY["species_stats"].setdefault(species, {
        "feed_baseline": 0, "feed_treatment": 0, "feed_skipped": 0,
        "care_baseline": 0, "care_treatment": 0, "care_skipped": 0,
        "bonus_generated": 0, "bonus_realized": 0, "bonus_clipped": 0,
        "yield_produced": 0,
    })

    if baseline_feed:
        _TELEMETRY["feed_actions_baseline"] += 1
        sp_stats["feed_baseline"] += 1
    if adaptive_feed:
        _TELEMETRY["feed_actions_treatment"] += 1
        sp_stats["feed_treatment"] += 1
    else:
        _TELEMETRY["feed_actions_skipped"] += 1
        _TELEMETRY["wheat_units_saved"] += 1
        sp_stats["feed_skipped"] += 1
        _TELEMETRY["reasons_feed_skipped"][feed_reason] = _TELEMETRY["reasons_feed_skipped"].get(feed_reason, 0) + 1

    if baseline_care:
        _TELEMETRY["care_actions_baseline"] += 1
        sp_stats["care_baseline"] += 1
    if adaptive_care:
        _TELEMETRY["care_actions_treatment"] += 1
        sp_stats["care_treatment"] += 1
        _TELEMETRY["care_bonus_generated"] += 1
        sp_stats["bonus_generated"] += 1
    else:
        _TELEMETRY["care_actions_skipped"] += 1
        _TELEMETRY["worker_actions_saved"] += 1
        sp_stats["care_skipped"] += 1
        _TELEMETRY["reasons_care_skipped"][care_reason] = _TELEMETRY["reasons_care_skipped"].get(care_reason, 0) + 1

    # Record ledger event (keep manageable size)
    if len(_TELEMETRY["ledger"]) < 1000:
        _TELEMETRY["ledger"].append({
            "species": species,
            "day": day,
            "hour": hour,
            "prod_today": prod_today,
            "feed": {"baseline": baseline_feed, "adaptive": adaptive_feed, "reason": feed_reason},
            "care": {"baseline": baseline_care, "adaptive": adaptive_care, "reason": care_reason},
            "yield_before": yield_before,
            "bank_before": bank_before,
            "consecutive_unfed": consecutive_unfed,
        })
