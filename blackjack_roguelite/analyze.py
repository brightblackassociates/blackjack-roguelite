"""
Metrics computation, experience quality evaluation, and reporting.
"""
from collections import Counter
from typing import List, Dict
from .config import GameConfig, ExperienceTarget
from .engine import RunResult


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_metrics(results: List[RunResult], config: GameConfig) -> Dict:
    total_runs = len(results)
    if total_runs == 0:
        return {}

    survived = sum(1 for r in results if r.survived)

    all_hands = []
    all_fights = []
    all_decisions = []
    act_damages: Dict[int, List[float]] = {}

    fights_per_act = config.run.fights_per_act + config.run.elites_per_act + 1

    for run in results:
        for i, fight in enumerate(run.fights):
            all_fights.append(fight)
            act = min(i // fights_per_act, config.run.acts - 1)
            act_damages.setdefault(act, []).append(fight.total_damage_dealt)

            for hand in fight.hands:
                all_hands.append(hand)
                all_decisions.extend(hand.decision_points)

    total_hands = len(all_hands)
    total_fights = len(all_fights)

    # Decision tension
    tense = sum(1 for d in all_decisions if d.is_tense)
    decision_tension = tense / len(all_decisions) if all_decisions else 0

    # Fight length
    fight_lengths = [len(f.hands) for f in all_fights]
    avg_fight_length = sum(fight_lengths) / len(fight_lengths) if fight_lengths else 0

    # Bust rates
    p_busts = sum(1 for h in all_hands if h.player_busted)
    e_busts = sum(1 for h in all_hands if h.enemy_busted)

    # Natural 21 rate
    nat21s = sum(1 for h in all_hands if h.player_natural)

    # Outcomes
    wins = sum(1 for h in all_hands if h.outcome == "win")
    losses = sum(1 for h in all_hands if h.outcome == "lose")
    pushes = sum(1 for h in all_hands if h.outcome == "push")
    folds = sum(1 for h in all_hands if h.outcome == "fold")

    # Close calls (within 2, not a push, neither busted)
    close = sum(
        1 for h in all_hands
        if not h.player_busted and not h.enemy_busted
        and abs(h.player_value - h.enemy_value) <= 2
        and h.outcome != "push"
    )

    # Damage
    avg_dmg_dealt = sum(h.damage_dealt for h in all_hands) / total_hands if total_hands else 0
    avg_dmg_taken = sum(h.damage_taken for h in all_hands) / total_hands if total_hands else 0

    # Companions
    total_captured = sum(len(r.companions_captured) for r in results)
    companion_hands = sum(1 for h in all_hands if h.companion_effects)

    # Snowball ratio
    last_act = config.run.acts - 1
    if act_damages.get(0) and act_damages.get(last_act):
        avg_a1 = sum(act_damages[0]) / len(act_damages[0])
        avg_a3 = sum(act_damages[last_act]) / len(act_damages[last_act])
        snowball = avg_a3 / avg_a1 if avg_a1 > 0 else 1.0
    else:
        snowball = 1.0

    # Fold rate
    fold_rate = folds / total_hands if total_hands else 0

    # Deck trim (avg cards removed per run)
    avg_cards_removed = sum(r.cards_removed for r in results) / total_runs

    # Enchantments
    avg_enchantments = sum(r.enchantments_applied for r in results) / total_runs

    # Power curve ratio: win rate in last act vs first act
    # This captures deck manipulation + companion growth together
    act_wins: Dict[int, List[int]] = {}
    for run in results:
        for i, fight in enumerate(run.fights):
            act = min(i // fights_per_act, config.run.acts - 1)
            for hand in fight.hands:
                if hand.outcome != "fold":
                    act_wins.setdefault(act, []).append(1 if hand.outcome == "win" else 0)

    last_act = config.run.acts - 1
    if act_wins.get(0) and act_wins.get(last_act):
        wr_a1 = sum(act_wins[0]) / len(act_wins[0])
        wr_a3 = sum(act_wins[last_act]) / len(act_wins[last_act])
        power_curve_ratio = wr_a3 / wr_a1 if wr_a1 > 0 else 1.0
    else:
        power_curve_ratio = 1.0

    # --- Highlights ---
    # Memorable moments (rare, unexpected, tell-your-friend worthy)
    MEMORABLE = {
        "natural_21", "enemy_natural_21",
        "close_win", "close_loss",
        "cruel_bust", "five_card",
        "companion_save", "clutch_win",
        "nine_lives",
    }
    # Routine ability events (happen every hand against that enemy type)
    # Tracked for info but don't count toward highlight rate.

    all_highlights = []
    for h in all_hands:
        all_highlights.extend(h.highlights)
    highlight_counts = Counter(all_highlights)

    # Only count memorable moments for the highlight rate
    memorable_hands = sum(
        1 for h in all_hands
        if any(hl in MEMORABLE for hl in h.highlights)
    )
    highlight_rate = memorable_hands / total_hands if total_hands else 0

    return {
        "total_runs": total_runs,
        "total_hands": total_hands,
        "total_fights": total_fights,
        "survival_rate": survived / total_runs,
        "decision_tension": decision_tension,
        "avg_fight_length": avg_fight_length,
        "player_bust_rate": p_busts / total_hands if total_hands else 0,
        "enemy_bust_rate": e_busts / total_hands if total_hands else 0,
        "natural_21_rate": nat21s / total_hands if total_hands else 0,
        "win_rate": wins / total_hands if total_hands else 0,
        "loss_rate": losses / total_hands if total_hands else 0,
        "push_rate": pushes / total_hands if total_hands else 0,
        "fold_rate": fold_rate,
        "close_call_rate": close / total_hands if total_hands else 0,
        "avg_damage_dealt": avg_dmg_dealt,
        "avg_damage_taken": avg_dmg_taken,
        "avg_companions_captured": total_captured / total_runs,
        "companion_effect_rate": companion_hands / total_hands if total_hands else 0,
        "snowball_ratio": snowball,
        "avg_encounters_completed": sum(r.encounters_completed for r in results) / total_runs,
        "avg_cards_removed": avg_cards_removed,
        "avg_enchantments": avg_enchantments,
        "power_curve_ratio": power_curve_ratio,
        # Highlights
        "highlight_rate": highlight_rate,
        "highlight_counts": dict(highlight_counts),
        "highlight_total": len(all_highlights),
    }


# ---------------------------------------------------------------------------
# Experience quality evaluation
# ---------------------------------------------------------------------------
METRIC_MAP = {
    "decision_tension": "decision_tension",
    "highlight_rate": "highlight_rate",
    "survival_rate": "survival_rate",
    "avg_fight_length": "avg_fight_length",
    "snowball_ratio": "snowball_ratio",
    "fold_rate": "fold_rate",
    "deck_trim": "avg_cards_removed",
    "power_curve_ratio": "power_curve_ratio",
}


def evaluate_targets(metrics: Dict, targets: List[ExperienceTarget]) -> Dict:
    results = {}
    for t in targets:
        key = METRIC_MAP.get(t.name)
        if not key or key not in metrics:
            continue
        raw = metrics[key]
        display = raw * 100 if t.unit == "%" else raw
        results[t.name] = {
            "target": t,
            "value": display,
            "in_range": t.target_min <= display <= t.target_max,
        }
    return results


# ---------------------------------------------------------------------------
# Recommendations engine
# ---------------------------------------------------------------------------
def generate_recommendations(metrics: Dict, target_results: Dict, config: GameConfig) -> List[str]:
    recs = []

    for name, result in target_results.items():
        if result["in_range"]:
            continue

        t = result["target"]
        v = result["value"]
        low = v < t.target_min

        if name == "survival_rate":
            if low:
                recs.append(f"Survival rate too low ({v:.1f}%). Consider:")
                recs.append(f"  - Increase player.starting_hp (now {config.player.starting_hp})")
                recs.append(f"  - Increase run.heal_between_acts_pct (now {config.run.heal_between_acts_pct})")
                recs.append(f"  - Decrease enemy HP values in ENEMY_TEMPLATES")
            else:
                recs.append(f"Survival rate too high ({v:.1f}%). Consider:")
                recs.append(f"  - Decrease player.starting_hp (now {config.player.starting_hp})")
                recs.append(f"  - Increase enemy HP values")

        elif name == "decision_tension":
            if low:
                recs.append(f"Decision tension too low ({v:.1f}%). Too many auto-pilot decisions. Consider:")
                recs.append(f"  - Enemy hit_thresholds may be too extreme (all 13 or all 18)")
                recs.append(f"  - Deck composition might make hits always safe or always deadly")
            else:
                recs.append(f"Decision tension very high ({v:.1f}%). Every hand is a coinflip. Consider:")
                recs.append(f"  - This might be fine (lots of interesting decisions)")
                recs.append(f"  - If it feels random, add more info sources (peek companions)")

        elif name == "highlight_rate":
            if low:
                recs.append(f"Highlight rate too low ({v:.1f}%). Not enough memorable moments. Consider:")
                recs.append(f"  - Add more enemy abilities that create visible events")
                recs.append(f"  - Increase companion effect magnitudes (more saves)")
                recs.append(f"  - Add more enemies with extreme thresholds for bust drama")
            else:
                recs.append(f"Highlight rate too high ({v:.1f}%). If everything is special, nothing is. Consider:")
                recs.append(f"  - Reduce enemy ability trigger rates")
                recs.append(f"  - Make highlights rarer but more impactful")

        elif name == "avg_fight_length":
            if low:
                recs.append(f"Fights too short ({v:.1f} hands). Consider:")
                recs.append(f"  - Increase enemy HP values")
            else:
                recs.append(f"Fights too long ({v:.1f} hands). Consider:")
                recs.append(f"  - Decrease enemy HP values")

        elif name == "snowball_ratio":
            if low:
                recs.append(f"No power growth ({v:.2f}x). Companions don't scale. Consider:")
                recs.append(f"  - Increase companion base_value / per_level")
                recs.append(f"  - Increase capture_chance (now {config.companion.capture_chance})")
            else:
                recs.append(f"Too much snowball ({v:.2f}x). Player becomes unstoppable. Consider:")
                recs.append(f"  - Decrease companion effect values")
                recs.append(f"  - Increase companion.xp_per_level (now {config.companion.xp_per_level})")

        elif name == "companion_impact":
            if low:
                recs.append(f"Companion impact too low ({v:.1f}%). Consider:")
                recs.append(f"  - Increase companion effect magnitudes in COMPANION_TEMPLATES")
                recs.append(f"  - Increase capture_chance (now {config.companion.capture_chance})")
            else:
                recs.append(f"Companion impact too high ({v:.1f}%). Consider:")
                recs.append(f"  - Decrease companion effect magnitudes")

        elif name == "strategy_skill_gap":
            if low:
                recs.append(f"Skill gap too small ({v:.1f}pp). Game feels random. Consider:")
                recs.append(f"  - Add more decision-relevant mechanics (peek, information)")
                recs.append(f"  - Make bust penalties harsher so mistakes cost more")
            else:
                recs.append(f"Skill gap too large ({v:.1f}pp). Might feel too solvable. Consider:")
                recs.append(f"  - Add more variance (random enemy abilities, events)")

        elif name == "fold_rate":
            if low:
                recs.append(f"Fold rate too low ({v:.1f}%). Players never fold. Consider:")
                recs.append(f"  - Increase fold_damage penalty or make raging enemies scarier")
            else:
                recs.append(f"Fold rate too high ({v:.1f}%). Players fold too much. Consider:")
                recs.append(f"  - Reduce fold_damage or increase fold risk")

        elif name == "deck_trim":
            if low:
                recs.append(f"Deck trim too low ({v:.1f} cards). Power curve is flat. Consider:")
                recs.append(f"  - Reward strategy may prefer healing too much")
                recs.append(f"  - Increase reward frequency or reduce min_deck_size")
            else:
                recs.append(f"Deck trim too high ({v:.1f} cards). Deck gets too small. Consider:")
                recs.append(f"  - Increase min_deck_size (now {config.reward.min_deck_size})")

        elif name == "power_curve_ratio":
            if low:
                recs.append(f"Power curve too flat ({v:.2f}x). Hands don't improve. Consider:")
                recs.append(f"  - Reward strategy not removing enough low cards")
                recs.append(f"  - Deck manipulation may need tuning")
            else:
                recs.append(f"Power curve too steep ({v:.2f}x). Late game too easy. Consider:")
                recs.append(f"  - Increase act_hp_multipliers to compensate")

    return recs


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------
def print_report(
    metrics: Dict,
    target_results: Dict,
    strategy_comparison: Dict = None,
    recommendations: List[str] = None,
):
    print()
    print("=" * 62)
    print("  BLACKJACK ROGUELITE -- SIMULATION REPORT")
    print("=" * 62)

    print(f"\n  Runs: {metrics['total_runs']}  |  "
          f"Hands: {metrics['total_hands']}  |  "
          f"Fights: {metrics['total_fights']}")

    # --- Core stats ---
    print(f"\n--- CORE STATS ---")
    print(f"  Survival Rate:            {metrics['survival_rate']*100:.1f}%")
    print(f"  Avg Encounters Completed: {metrics['avg_encounters_completed']:.1f} / "
          f"{3 * (3 + 1 + 1)}")
    print(f"  Avg Fight Length:         {metrics['avg_fight_length']:.1f} hands")

    # --- Hand outcomes ---
    print(f"\n--- HAND OUTCOMES ---")
    print(f"  Win:       {metrics['win_rate']*100:.1f}%")
    print(f"  Lose:      {metrics['loss_rate']*100:.1f}%")
    print(f"  Push:      {metrics['push_rate']*100:.1f}%")
    print(f"  Fold:      {metrics['fold_rate']*100:.1f}%")
    print(f"  Player Bust Rate:  {metrics['player_bust_rate']*100:.1f}%")
    print(f"  Enemy Bust Rate:   {metrics['enemy_bust_rate']*100:.1f}%")
    print(f"  Natural 21 Rate:   {metrics['natural_21_rate']*100:.1f}%")
    print(f"  Close Calls:       {metrics['close_call_rate']*100:.1f}%")

    # --- Damage ---
    print(f"\n--- DAMAGE ---")
    print(f"  Avg Dealt / Hand:  {metrics['avg_damage_dealt']:.1f}")
    print(f"  Avg Taken / Hand:  {metrics['avg_damage_taken']:.1f}")

    # --- Companions ---
    print(f"\n--- COMPANIONS ---")
    print(f"  Avg Captured / Run:    {metrics['avg_companions_captured']:.2f}")
    print(f"  Effect Trigger Rate:   {metrics['companion_effect_rate']*100:.1f}%")
    print(f"  Snowball (Act 3/Act 1): {metrics['snowball_ratio']:.2f}x")

    # --- Power Curve ---
    print(f"\n--- POWER CURVE ---")
    print(f"  Avg Cards Removed / Run:    {metrics['avg_cards_removed']:.1f}")
    print(f"  Avg Enchantments / Run:     {metrics['avg_enchantments']:.1f}")
    print(f"  Power Curve Ratio:          {metrics['power_curve_ratio']:.3f}x")

    # --- Highlights ---
    print(f"\n--- MEMORABLE MOMENTS ---")
    hc = metrics.get("highlight_counts", {})
    ht = metrics["total_hands"]
    print(f"  Highlight Rate:    {metrics['highlight_rate']*100:.1f}% of hands  (memorable only)")
    memorable_types = [
        ("natural_21", "Natural 21 (player)"),
        ("enemy_natural_21", "Natural 21 (enemy)"),
        ("close_win", "Win by 1"),
        ("close_loss", "Lose by 1"),
        ("cruel_bust", "Bust on 22"),
        ("five_card", "5+ card hand"),
        ("companion_save", "Companion save (unbust)"),
        ("clutch_win", "Clutch win (<20% HP)"),
        ("nine_lives", "Nine Lives triggered"),
    ]
    for key, label in memorable_types:
        count = hc.get(key, 0)
        if count > 0:
            pct = count / ht * 100
            print(f"    {label:28s}  {count:>6}  ({pct:.1f}%)")

    # --- Ability events (routine, not counted as highlights) ---
    ability_types = [
        ("shell_block", "Shell absorbed damage"),
        ("rage_stack", "Rage escalation"),
        ("poison_tick", "Poison tick"),
        ("drain_heal", "Lich drain heal"),
    ]
    has_abilities = any(hc.get(k, 0) > 0 for k, _ in ability_types)
    if has_abilities:
        print(f"\n  Ability Events (routine):")
        for key, label in ability_types:
            count = hc.get(key, 0)
            if count > 0:
                pct = count / ht * 100
                print(f"    {label:28s}  {count:>6}  ({pct:.1f}%)")

    # --- Experience qualities ---
    print(f"\n--- EXPERIENCE QUALITIES ---")
    for name, result in target_results.items():
        t = result["target"]
        v = result["value"]
        ok = result["in_range"]
        marker = "OK" if ok else "!!"

        if t.unit == "%":
            line = f"  {marker}  {t.description}: {v:.1f}%  [{t.target_min:.0f}-{t.target_max:.0f}%]"
        elif t.unit == "hands":
            line = f"  {marker}  {t.description}: {v:.1f}  [{t.target_min:.0f}-{t.target_max:.0f}]"
        elif t.unit == "cards":
            line = f"  {marker}  {t.description}: {v:.1f}  [{t.target_min:.0f}-{t.target_max:.0f}]"
        elif t.unit == "x":
            line = f"  {marker}  {t.description}: {v:.2f}x  [{t.target_min:.1f}-{t.target_max:.1f}x]"
        elif t.unit == "pp":
            line = f"  {marker}  {t.description}: {v:.1f}pp  [{t.target_min:.0f}-{t.target_max:.0f}pp]"
        else:
            line = f"  {marker}  {t.description}: {v:.1f}  [{t.target_min:.0f}-{t.target_max:.0f}]"
        print(line)

    # --- Strategy comparison ---
    if strategy_comparison:
        print(f"\n--- STRATEGY COMPARISON ---")
        for strat_name, survival in sorted(strategy_comparison.items(), key=lambda x: x[1]):
            bar = "#" * int(survival * 50)
            print(f"  {strat_name:15s}  {survival*100:5.1f}%  {bar}")

        basic = strategy_comparison.get("basic", 0)
        rand = strategy_comparison.get("random", 0)
        if basic and rand:
            gap = (basic - rand) * 100
            print(f"  Skill Gap (Basic vs Random): {gap:.1f}pp")

    # --- Recommendations ---
    if recommendations:
        print(f"\n--- RECOMMENDATIONS ---")
        for rec in recommendations:
            print(f"  {rec}")

    print()
    print("=" * 62)
