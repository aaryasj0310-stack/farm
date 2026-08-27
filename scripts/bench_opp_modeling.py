"""Benchmark: Opponent Modeling ON vs OFF against 4 replay opponents."""
import json, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
_agent_dir = str(Path(__file__).resolve().parent.parent / "agent")
for _sub in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, os.path.join(_agent_dir, _sub))

import kaggle_environments
from price_forecast import PriceForecast
from macro_planner import MacroPlanner
from endgame_liquidator import EndgameLiquidator
from market_brain import MarketBrain
from order_builder import OrderBuilder
from task_scheduler import build_tasks, assign_tasks
from state_tracker import get_state, record_our_sale
from opponent_model import (
    snapshot_opponent_farm, detect_tile_deltas,
    forecast_opponent_production, update_opponent_shed_estimate,
    compute_opponent_sell_probabilities, summarize_opponent_commitments,
)
from opponent_advisor import OpponentAdvice, build_opponent_advice
from shop_adapter import demand_boosts

PASS_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}

REPLAY_DIR = Path(__file__).resolve().parent.parent / "replays" / "land buy roi based"
REPLAYS = [
    ("100976069", "Abin Biju"),
    ("100978383", "Arthur Merritt"),
    ("100980673", "aaronykchen"),
    ("100983008", "toshiconner"),
]


def load_replay_opp_actions(replay_id):
    path = REPLAY_DIR / f"{replay_id}.json"
    with open(path) as f:
        data = json.load(f)
    actions = []
    for step in data["steps"]:
        if isinstance(step, list) and len(step) >= 2:
            p1 = step[1]
            act = p1.get("action", PASS_ACTION) if isinstance(p1, dict) else PASS_ACTION
            if isinstance(act, list):
                act = PASS_ACTION
            actions.append(act)
        else:
            actions.append(PASS_ACTION)
    return actions


def make_replay_opponent(actions):
    """Replay opponent: returns the stored action dict directly."""
    _counter = [0]
    def agent_fn(obs, config=None):
        i = min(_counter[0], len(actions) - 1)
        _counter[0] += 1
        return actions[i]
    return agent_fn


def make_our_agent(use_opp_modeling=True):
    """Create our agent with optional opponent modeling."""
    fc = PriceForecast.load()
    planner = MacroPlanner(fc)
    builder = OrderBuilder()
    brain = MarketBrain(fc)
    liquidator = EndgameLiquidator(fc, brain)

    prev_snap = [None]
    est_shed = [None]

    def agent_fn(obs, config=None):
        ctx, mem = get_state(obs)
        if ctx is None:
            return dict(PASS_ACTION)

        opp_advice = OpponentAdvice()
        if use_opp_modeling:
            try:
                opp_farm = ctx.get("opponent_farm")
                if opp_farm is not None:
                    new_snap = snapshot_opponent_farm(opp_farm)
                    deltas = detect_tile_deltas(opp_farm, prev_snap[0])
                    prev_snap[0] = new_snap
                    forecast = forecast_opponent_production(opp_farm, ctx["day"])
                    opp_animals = sum(1 for t in opp_farm.iter_tiles() if t.is_animal)
                    opp_sales = mem.get("opp_sales_inferred", {})
                    est_shed[0] = update_opponent_shed_estimate(
                        est_shed[0], deltas, opp_sales,
                        opp_animals, ctx["day"], ctx["hour"],
                    )
                    sell_probs = compute_opponent_sell_probabilities(
                        opp_farm, est_shed[0], ctx, mem,
                    )
                    opp_state = {
                        "estimated_shed": est_shed[0],
                        "sell_probs": sell_probs,
                        "opp_sales_inferred": opp_sales,
                        "shed_pressure": sum(est_shed[0].values()) / 100.0,
                        "forecast": forecast,
                        "commitments": summarize_opponent_commitments(opp_farm),
                        "animal_counts": {t.animal: 1 for t in opp_farm.iter_tiles() if t.is_animal},
                    }
                    town_obj = ctx.get("town")
                    unlocked = getattr(town_obj, "unlocked_shops", None)
                    if unlocked is None and isinstance(town_obj, dict):
                        unlocked = town_obj.get("unlocked_shops", [])
                    boosts = demand_boosts(unlocked or [])
                    opp_advice = build_opponent_advice(opp_state, ctx, forecast, boosts=boosts)
            except Exception:
                opp_advice = OpponentAdvice()

        plan = planner.build(ctx, boosts={}, opp_advice=opp_advice)
        tasks = build_tasks(ctx, plan)
        asg = assign_tasks(tasks, ctx)

        purchase_orders, _ = builder.build(ctx, plan.intents)
        if ctx["day"] >= 28:
            sell_orders, _ = liquidator.plan(ctx, opp_advice=opp_advice)
        else:
            sell_orders, _ = brain.sell_orders(ctx, opp_advice=opp_advice)

        market = MarketBrain.compose(
            purchase_orders, sell_orders,
            purchases_first=(ctx["hour"] == 0))

        for order in market:
            if order[0] == "SELL":
                record_our_sale(order[1], order[2])

        n_units = 1 + len(ctx["farm"].hands)
        return {
            "farmer": list(asg["actions"].get(0, ["PASS"])),
            "hands": [list(asg["actions"].get(i, ["PASS"])) for i in range(1, n_units)],
            "market": market,
        }
    return agent_fn


def run_match(our_fn, opp_fn, seed=11):
    env = kaggle_environments.make(
        "kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"})
    env.run([our_fn, opp_fn])
    return env.state[0].get("reward", 0), env.state[1].get("reward", 0)


def main():
    print("=" * 95)
    print("OPPONENT MODELING BENCHMARK")
    print("=" * 95)

    all_results = []

    for replay_id, opp_name in REPLAYS:
        print(f"\n--- {opp_name} ({replay_id}) ---")
        opp_actions = load_replay_opp_actions(replay_id)
        opp_fn = make_replay_opponent(opp_actions)

        # Baseline (OFF)
        our_off = make_our_agent(use_opp_modeling=False)
        p0_off, p1_off = run_match(our_off, opp_fn, seed=11)
        print(f"  Baseline (OFF): P0=${p0_off:.0f}  P1=${p1_off:.0f}")

        # Active (ON)
        opp_fn2 = make_replay_opponent(opp_actions)  # fresh counter
        our_on = make_our_agent(use_opp_modeling=True)
        p0_on, p1_on = run_match(our_on, opp_fn2, seed=11)
        print(f"  Active  (ON):  P0=${p0_on:.0f}  P1=${p1_on:.0f}")

        delta = p0_on - p0_off
        print(f"  Delta: ${delta:+.0f}")
        all_results.append({
            "name": opp_name, "replay_id": replay_id,
            "baseline": p0_off, "active": p0_on, "delta": delta,
        })

    # Summary
    print("\n" + "=" * 95)
    print(f"{'Opponent':<22} {'Baseline':>10} {'Active':>10} {'Delta':>10} {'Result':>8}")
    print("-" * 95)
    for r in all_results:
        status = "WIN" if r["delta"] > 0 else ("TIE" if r["delta"] == 0 else "LOSS")
        print(f"{r['name']:<22} ${r['baseline']:>8.0f} ${r['active']:>8.0f} ${r['delta']:>+8.0f} {status:>8}")
    print("-" * 95)
    avg_b = sum(r["baseline"] for r in all_results) / len(all_results)
    avg_a = sum(r["active"] for r in all_results) / len(all_results)
    print(f"{'AVERAGE':<22} ${avg_b:>8.0f} ${avg_a:>8.0f} ${avg_a - avg_b:>+8.0f}")
    print("=" * 95)


if __name__ == "__main__":
    main()
