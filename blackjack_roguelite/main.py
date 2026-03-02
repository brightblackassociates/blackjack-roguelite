#!/usr/bin/env python3
"""
Blackjack Roguelite -- Simulation Runner

Usage:
    python main.py                     # Default: 1000 runs, basic strategy
    python main.py --runs 5000         # More runs for tighter confidence
    python main.py --strategy smart    # Try a specific strategy
    python main.py --compare           # Compare all strategies side-by-side
    python main.py --no-companions     # Strip companions to see their impact
"""
import argparse
import time

from .config import GameConfig
from .simulate import (
    Simulator, STRATEGIES_BY_NAME,
    NeverCaptureStrategy, AlwaysCaptureStrategy,
)
from .analyze import (
    compute_metrics, evaluate_targets,
    generate_recommendations, print_report,
)


def main():
    parser = argparse.ArgumentParser(description="Blackjack Roguelite Simulator")
    parser.add_argument(
        "--runs", type=int, default=1000,
        help="Number of simulation runs (default: 1000)",
    )
    parser.add_argument(
        "--strategy",
        choices=["random", "conservative", "basic", "aggressive", "smart"],
        default="basic",
        help="Player strategy (default: basic)",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Compare all strategies",
    )
    parser.add_argument(
        "--no-companions", action="store_true",
        help="Disable companion capture",
    )
    args = parser.parse_args()

    config = GameConfig()
    capture_strat = AlwaysCaptureStrategy()

    if args.no_companions:
        config.companion.capture_chance = 0.0
        capture_strat = NeverCaptureStrategy()

    sim = Simulator(config)
    strategy = STRATEGIES_BY_NAME[args.strategy]

    # --- Main simulation ---
    t0 = time.time()
    print(f"Running {args.runs} simulations with '{strategy.name}' strategy...")
    results = sim.run(args.runs, strategy, capture_strat)
    metrics = compute_metrics(results, config)
    target_results = evaluate_targets(metrics, config.experience_targets)
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.2f}s")

    # --- Strategy comparison ---
    strategy_comparison = None
    if args.compare:
        print("Comparing all strategies...")
        all_results = sim.compare_strategies(args.runs)
        strategy_comparison = {}
        for sname, sresults in all_results.items():
            sm = compute_metrics(sresults, config)
            strategy_comparison[sname] = sm["survival_rate"]

        # Companion impact: compare with vs without companions
        print("Running no-companion baseline...")
        nc_config = GameConfig()
        nc_config.companion.capture_chance = 0.0
        nc_sim = Simulator(nc_config)
        nc_results = nc_sim.run(args.runs, strategy, NeverCaptureStrategy())
        nc_metrics = compute_metrics(nc_results, config)

        if nc_metrics["avg_damage_dealt"] > 0:
            impact = (
                (metrics["avg_damage_dealt"] - nc_metrics["avg_damage_dealt"])
                / nc_metrics["avg_damage_dealt"]
            )
        else:
            impact = 0

        # Find companion_impact target
        ci_target = next(
            (t for t in config.experience_targets if t.name == "companion_impact"),
            None,
        )
        if ci_target:
            target_results["companion_impact"] = {
                "target": ci_target,
                "value": impact * 100,
                "in_range": ci_target.target_min <= impact * 100 <= ci_target.target_max,
            }

        # Skill gap
        basic_sr = strategy_comparison.get("basic", 0)
        rand_sr = strategy_comparison.get("random", 0)
        gap = (basic_sr - rand_sr) * 100
        sg_target = next(
            (t for t in config.experience_targets if t.name == "strategy_skill_gap"),
            None,
        )
        if sg_target:
            target_results["strategy_skill_gap"] = {
                "target": sg_target,
                "value": gap,
                "in_range": sg_target.target_min <= gap <= sg_target.target_max,
            }

    # --- Recommendations ---
    recommendations = generate_recommendations(metrics, target_results, config)

    # --- Report ---
    print_report(metrics, target_results, strategy_comparison, recommendations)


if __name__ == "__main__":
    main()
