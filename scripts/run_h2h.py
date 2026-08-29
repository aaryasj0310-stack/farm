import os
import sys
import time
import importlib.util
from kaggle_environments import make

def load_agent(path: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod.agent

def main():
    our_agent_path = os.path.abspath("submission/main.py")
    root_agent_path = os.path.abspath("submission.py")

    print(f"Loading Our Agent from: {our_agent_path}")
    our_agent = load_agent(our_agent_path, "our_agent_mod")
    print(f"Loading Root Agent from: {root_agent_path}")
    root_agent = load_agent(root_agent_path, "root_agent_mod")

    seeds = [42, 303, 777]
    scores_our = []
    scores_root = []

    for s_idx, seed in enumerate(seeds, 1):
        # Game 1: Our Agent as P0, Root Agent as P1
        print(f"\n{'='*70}")
        print(f"MATCH {2*s_idx - 1} (Seed {seed}): Our Agent (P0) vs Root submission.py (P1)")
        print(f"{'='*70}")
        env = make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"}, debug=True)
        t0 = time.time()
        env.run([our_agent, root_agent])
        dur = time.time() - t0
        
        last_obs = env.steps[-1][0].observation
        p0_farm = last_obs["farms"][0]
        p1_farm = last_obs["farms"][1]
        p0_money = p0_farm["money"]
        p1_money = p1_farm["money"]
        scores_our.append(p0_money)
        scores_root.append(p1_money)
        
        print(f"  Final Results after 720 steps ({dur:.1f}s):")
        print(f"    Our Agent (P0):          ${p0_money:,.2f} | Quadrants: {p0_farm.get('unlocked_quadrants', [])} | Hands: {len(p0_farm.get('hands', []))}")
        print(f"    Root submission.py (P1): ${p1_money:,.2f} | Quadrants: {p1_farm.get('unlocked_quadrants', [])} | Hands: {len(p1_farm.get('hands', []))}")
        winner = "Our Agent (P0)" if p0_money > p1_money else ("Root submission.py (P1)" if p1_money > p0_money else "Tie")
        diff = abs(p0_money - p1_money)
        print(f"    -> WINNER: {winner} by +${diff:,.2f}")

        # Game 2: Root Agent as P0, Our Agent as P1
        print(f"\n{'='*70}")
        print(f"MATCH {2*s_idx} (Seed {seed}): Root submission.py (P0) vs Our Agent (P1)")
        print(f"{'='*70}")
        env = make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"}, debug=True)
        t0 = time.time()
        env.run([root_agent, our_agent])
        dur = time.time() - t0
        
        last_obs = env.steps[-1][0].observation
        p0_farm = last_obs["farms"][0]
        p1_farm = last_obs["farms"][1]
        p0_money = p0_farm["money"]
        p1_money = p1_farm["money"]
        scores_root.append(p0_money)
        scores_our.append(p1_money)
        
        print(f"  Final Results after 720 steps ({dur:.1f}s):")
        print(f"    Root submission.py (P0): ${p0_money:,.2f} | Quadrants: {p0_farm.get('unlocked_quadrants', [])} | Hands: {len(p0_farm.get('hands', []))}")
        print(f"    Our Agent (P1):          ${p1_money:,.2f} | Quadrants: {p1_farm.get('unlocked_quadrants', [])} | Hands: {len(p1_farm.get('hands', []))}")
        winner = "Our Agent (P1)" if p1_money > p0_money else ("Root submission.py (P0)" if p0_money > p1_money else "Tie")
        diff = abs(p1_money - p0_money)
        print(f"    -> WINNER: {winner} by +${diff:,.2f}")

    avg_our = sum(scores_our) / len(scores_our)
    avg_root = sum(scores_root) / len(scores_root)
    wins_our = sum(1 for o, r in zip(scores_our, scores_root) if o > r)
    wins_root = sum(1 for o, r in zip(scores_our, scores_root) if r > o)

    print(f"\n{'='*70}")
    print(f"TOURNAMENT SUMMARY ({len(scores_our)} Matches)")
    print(f"{'='*70}")
    print(f"Our Agent:          Avg Score = ${avg_our:,.2f} | Wins = {wins_our}/{len(scores_our)} ({wins_our/len(scores_our)*100:.1f}%)")
    print(f"Root submission.py: Avg Score = ${avg_root:,.2f} | Wins = {wins_root}/{len(scores_root)} ({wins_root/len(scores_root)*100:.1f}%)")

if __name__ == "__main__":
    main()
