#!/usr/bin/env python3
"""
Rapid parameter sweep: test multiple configs in one shot.
Shows which knobs move which metrics.
"""
import copy
from .config import GameConfig, ENEMY_TEMPLATES, COMPANION_TEMPLATES
from .simulate import (
    Simulator, BasicStrategy, SmartStrategy, RandomStrategy,
    AlwaysCaptureStrategy, NeverCaptureStrategy,
    SmartRewardStrategy, HealFirstRewardStrategy, RemoveFirstRewardStrategy,
)
from .analyze import compute_metrics


def scale_enemy_hp(factor):
    """Return modified ENEMY_TEMPLATES with HP scaled by factor."""
    scaled = {}
    for k, v in ENEMY_TEMPLATES.items():
        e = dict(v)
        e["hp"] = max(1, int(v["hp"] * factor))
        scaled[k] = e
    return scaled


def scale_companion_values(factor):
    """Return modified COMPANION_TEMPLATES with base_value scaled."""
    scaled = {}
    for k, v in COMPANION_TEMPLATES.items():
        c = dict(v)
        c["base_value"] = v["base_value"] * factor
        c["per_level"] = v["per_level"] * factor
        scaled[k] = c
    return scaled


def run_scenario(label, config, enemy_templates=None, companion_templates=None,
                 runs=1000, strategy=None, reward_strategy=None):
    """Run a scenario and return key metrics."""
    import config as cfg_module

    # Temporarily swap templates
    orig_enemies = cfg_module.ENEMY_TEMPLATES
    orig_companions = cfg_module.COMPANION_TEMPLATES
    if enemy_templates:
        cfg_module.ENEMY_TEMPLATES = enemy_templates
    if companion_templates:
        cfg_module.COMPANION_TEMPLATES = companion_templates

    sim = Simulator(config)
    basic = strategy or BasicStrategy()
    rand = RandomStrategy()

    results_basic = sim.run(runs, basic, AlwaysCaptureStrategy(), reward_strategy)
    results_rand = sim.run(runs, rand, AlwaysCaptureStrategy(), reward_strategy)

    # No-companion baseline
    nc_config = copy.deepcopy(config)
    nc_config.companion.capture_chance = 0.0
    nc_sim = Simulator(nc_config)
    results_nc = nc_sim.run(runs, basic, NeverCaptureStrategy(), reward_strategy)

    m = compute_metrics(results_basic, config)
    m_rand = compute_metrics(results_rand, config)
    m_nc = compute_metrics(results_nc, config)

    # Restore
    cfg_module.ENEMY_TEMPLATES = orig_enemies
    cfg_module.COMPANION_TEMPLATES = orig_companions

    skill_gap = (m["survival_rate"] - m_rand["survival_rate"]) * 100
    comp_impact = 0
    if m_nc["avg_damage_dealt"] > 0:
        comp_impact = ((m["avg_damage_dealt"] - m_nc["avg_damage_dealt"]) / m_nc["avg_damage_dealt"]) * 100

    return {
        "label": label,
        "survival": m["survival_rate"] * 100,
        "avg_enc": m["avg_encounters_completed"],
        "fight_len": m["avg_fight_length"],
        "win_rate": m["win_rate"] * 100,
        "loss_rate": m["loss_rate"] * 100,
        "tension": m["decision_tension"] * 100,
        "highlight": m["highlight_rate"] * 100,
        "skill_gap": skill_gap,
        "comp_impact": comp_impact,
        "avg_dmg_dealt": m["avg_damage_dealt"],
        "avg_dmg_taken": m["avg_damage_taken"],
        "bust_rate": m["player_bust_rate"] * 100,
        "snowball": m["snowball_ratio"],
        "fold_rate": m["fold_rate"] * 100,
        "cards_removed": m["avg_cards_removed"],
        "enchantments": m["avg_enchantments"],
        "power_curve": m["power_curve_ratio"],
    }


def print_sweep(results):
    print()
    print("=" * 120)
    print("  PARAMETER SWEEP RESULTS")
    print("=" * 120)
    print()

    # Header
    cols = [
        ("Scenario", 30),
        ("Surv%", 6),
        ("AvgEnc", 7),
        ("FightL", 7),
        ("Win%", 6),
        ("Tens%", 6),
        ("Skill", 6),
        ("Comp%", 6),
        ("Snow", 5),
        ("Fold%", 6),
        ("Trim", 5),
        ("Ench", 5),
        ("PwrC", 5),
    ]
    header = "  ".join(f"{name:>{w}}" for name, w in cols)
    print(header)
    print("-" * len(header))

    for r in results:
        vals = [
            f"{r['label']:>30}",
            f"{r['survival']:>5.1f}%",
            f"{r['avg_enc']:>6.1f}",
            f"{r['fight_len']:>6.1f}",
            f"{r['win_rate']:>5.1f}%",
            f"{r['tension']:>5.1f}%",
            f"{r['skill_gap']:>5.1f}",
            f"{r['comp_impact']:>5.1f}%",
            f"{r['snowball']:>5.2f}",
            f"{r['fold_rate']:>5.1f}%",
            f"{r['cards_removed']:>5.1f}",
            f"{r['enchantments']:>5.1f}",
            f"{r['power_curve']:>5.3f}",
        ]
        print("  ".join(vals))

    # Target ranges for reference
    print()
    print("  Targets: Surv 20-40% | FightL 3-6 | Tens 30-50% | Skill 10-30pp | Comp 20-45%")
    print("           Snow 1.2-2.0x | Fold 5-15% | Trim 4-10 | PwrC 1.05-1.15x")
    print("=" * 120)


def main():
    runs = 800  # Lower for speed during sweep

    scenarios = []

    # --- Current baseline (new compressed HP + multiplicative companions) ---
    cfg = GameConfig()
    scenarios.append(run_scenario("Baseline (40 HP)", cfg, runs=runs))

    # --- Smart strategy with folding ---
    cfg2 = GameConfig()
    scenarios.append(run_scenario("Smart + fold", cfg2, runs=runs, strategy=SmartStrategy()))

    # --- Deck manipulation comparison: remove-first vs heal-first ---
    cfg3 = GameConfig()
    scenarios.append(run_scenario(
        "Remove-first rewards", cfg3, runs=runs,
        reward_strategy=RemoveFirstRewardStrategy(),
    ))

    cfg4 = GameConfig()
    scenarios.append(run_scenario(
        "Heal-first rewards", cfg4, runs=runs,
        reward_strategy=HealFirstRewardStrategy(),
    ))

    # --- No deck manipulation (heal only) ---
    cfg5 = GameConfig()
    cfg5.reward.min_deck_size = 52  # Effectively disable removal
    scenarios.append(run_scenario("No deck manipulation", cfg5, runs=runs))

    # --- Act scaling comparison ---
    cfg6 = GameConfig()
    cfg6.run.act_hp_multipliers = [1.0, 1.0, 1.0]  # No scaling
    scenarios.append(run_scenario("No act HP scaling", cfg6, runs=runs))

    # --- Tuning explorations ---
    cfg7 = GameConfig()
    cfg7.player.starting_hp = 50
    scenarios.append(run_scenario("HP 50", cfg7, runs=runs))

    cfg8 = GameConfig()
    cfg8.player.starting_hp = 60
    scenarios.append(run_scenario("HP 60", cfg8, runs=runs))

    cfg9 = GameConfig()
    cfg9.damage.damage_subtract = 13
    scenarios.append(run_scenario("Subtract 13", cfg9, runs=runs))

    cfg10 = GameConfig()
    cfg10.damage.damage_subtract = 12
    scenarios.append(run_scenario("Subtract 12", cfg10, runs=runs))

    print_sweep(scenarios)


if __name__ == "__main__":
    main()
