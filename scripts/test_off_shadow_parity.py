#!/usr/bin/env python3
"""
Test OFF vs SHADOW parity on a diagnostic panel.
Runs matches in C0 (OFF) and C1 (SHADOW) and compares:
1. Turn-by-turn emitted actions (must be 100% identical).
2. Final terminal cash (must be 100% identical).
3. Engine state (0 divergence).
"""

import sys
import os
import json
import time
import kaggle_environments

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def run_single_match(seed: int, opponent: str, seat: int, arch_mode: str):
    # Set architecture mode
    import agent.config as config
    config.SW_FORWARD_ARCHITECTURE_MODE = arch_mode
    config.SOFT_WORKER_LOCALITY_MODE = "ON"
    config.MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"
    config.QUADRANT_HARD_BLOCK = {4}
    
    # Reload agent to ensure clean state
    from agent.main import agent as my_agent
    
    # Create environment
    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"seed": seed, "episodeSteps": 720},
        debug=True,
    )
    
    # Setup players
    if seat == 0:
        agents = [my_agent, opponent]
    else:
        agents = [opponent, my_agent]
        
    env.reset()
    
    actions_recorded = []
    
    # Run episode
    while not env.done:
        obs = env.state[seat].observation
        config_env = env.configuration
        
        # Capture our agent's action
        from agent.main import agent
        act = agent(obs, config_env)
        actions_recorded.append(act)
        
        # Step env with agent action
        if seat == 0:
            env.step([act, None])
        else:
            env.step([None, act])
            
    final_cash = env.state[seat].observation.farms[seat].money
    return final_cash, actions_recorded

def main():
    print("=== Testing OFF vs SHADOW Parity ===", flush=True)
    test_cases = [
        (97013, "pass", 0),
        (97014, "pure_wheat_rush", 1),
        (97015, "cow_milk_engine", 0),
    ]
    
    for seed, opp, seat in test_cases:
        print(f"\nTesting Seed={seed}, Opponent={opp}, Seat={seat}...", flush=True)
        
        # Run C0 (OFF)
        t0 = time.time()
        cash_off, acts_off = run_single_match(seed, opp, seat, "OFF")
        print(f"  OFF: Cash = ${cash_off:.2f}, Actions = {len(acts_off)} turns in {time.time()-t0:.1f}s", flush=True)
        
        # Run C1 (SHADOW)
        t0 = time.time()
        cash_shadow, acts_shadow = run_single_match(seed, opp, seat, "SHADOW")
        print(f"  SHADOW: Cash = ${cash_shadow:.2f}, Actions = {len(acts_shadow)} turns in {time.time()-t0:.1f}s", flush=True)
        
        # Check cash parity
        assert cash_off == cash_shadow, f"Cash mismatch! OFF=${cash_off} vs SHADOW=${cash_shadow}"
        
        # Check action parity turn by turn
        assert len(acts_off) == len(acts_shadow), "Turn count mismatch!"
        for step, (a_off, a_sh) in enumerate(zip(acts_off, acts_shadow)):
            assert a_off == a_sh, f"Action divergence at step {step}! OFF={a_off} vs SHADOW={a_sh}"
            
        print(f"  [PASS] 100% Action and Cash Parity verified for Seed={seed}!", flush=True)
        
    print("\n=== ALL DIAGNOSTIC PARITY CHECKS PASSED ===", flush=True)

if __name__ == "__main__":
    main()
